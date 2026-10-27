#!/usr/bin/env python3
"""AST-level survey of llmwikify src tree.

Independent re-verification of docs/designs/code-reuse-optimization.md claims:
  1. exact clone detection (structure hash, names/literals/positions stripped)
  2. pure-forwarding function detection
  3. import cycle detection (module-level SCC)
  4. layer violation check (kernel -> apps etc.)
  5. module fan-in / fan-out
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "llmwikify"
LAYERS = ("interfaces", "apps", "kernel", "foundation")


# ---------------------------------------------------------------- normalizer
class Norm(ast.NodeTransformer):
    """Strip names, literals and positions -> pure structural shape.

    Callee names are preserved: ``run_init(...)`` and ``run_ingest(...)``
    are different APIs even though their bodies are isomorphic, and
    collapsing them would manufacture fake clone groups.
    """

    def __init__(self) -> None:
        self.keep_names: set[int] = set()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.keep_names.add(id(node.func))
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        if id(node) in self.keep_names:
            return node
        return ast.copy_location(ast.Name(id="V", ctx=ast.Load()), node)

    def visit_arg(self, node):
        return ast.copy_location(ast.arg(arg="a"), node)

    def visit_Attribute(self, node):
        # Keep the attribute name (the called symbol) — it is part of the
        # clone's API. Only the receiver object is normalized away.
        self.generic_visit(node)
        if isinstance(node.value, ast.Name):
            node.value = ast.copy_location(ast.Name(id="V", ctx=ast.Load()), node)
        return node

    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value=node.value.__class__.__name__), node)

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.name = "f"
        node.decorator_list = []
        node.returns = None
        node.type_comment = None
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_keyword(self, node):
        self.generic_visit(node)
        node.arg = "k"
        return node

    def visit_ExceptHandler(self, node):
        self.generic_visit(node)
        node.name = "e"
        return node

    def visit_Global(self, node):
        return ast.copy_location(ast.Global(names=["g"]), node)

    def visit_Nonlocal(self, node):
        return ast.copy_location(ast.Nonlocal(names=["g"]), node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        node.name = "C"
        node.decorator_list = []
        node.bases = [ast.copy_location(ast.Name(id="B", ctx=ast.Load()), node)]
        node.keywords = []
        return node

    def visit_Lambda(self, node):
        self.generic_visit(node)
        node.args = ast.copy_location(ast.arguments(
            args=[ast.arg(arg="a")], posonlyargs=[], kwonlyargs=[],
            kw_defaults=[], defaults=[]), node)
        return node


def shape_hash(node) -> str:
    tree = Norm().visit(ast.parse(ast.unparse(node)))
    ast.fix_missing_locations(tree)
    return hashlib.sha1(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def src_lines(node) -> int:
    """Physical lines the node occupies (body-only for functions)."""
    end = getattr(node, "end_lineno", node.lineno) or node.lineno
    return end - node.lineno + 1


def payload_lines(fn) -> int:
    """Lines of *executable payload*, excluding the signature and docstring.

    A clone group's "waste" should be measured on real code, not on
    docstrings: three Protocol stubs that all say ``...`` are not
    duplicated logic just because their docstrings are long.
    """
    body = fn.body
    start_idx = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        start_idx = 1
    if not body or start_idx >= len(body):
        return 0
    first = body[start_idx]
    end = getattr(fn, "end_lineno", first.lineno) or first.lineno
    return max(0, end - first.lineno + 1)


# ---------------------------------------------------------------- collection
def iter_funcs(tree):
    """Yield (qualname, node) for every function/method in the module."""
    out = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}{child.name}"
                out.append((q, child))
                walk(child, q + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree)
    return out


def collect() -> list[dict]:
    files = []
    for py in sorted(SRC.rglob("*.py")):
        rel = py.relative_to(REPO)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"!! SyntaxError {rel}: {e}", file=sys.stderr)
            continue
        files.append((rel, py, tree))
    return files


# ---------------------------------------------------------------- 1. clones
def detect_clones(files) -> list[dict]:
    buckets: dict[str, list[tuple]] = defaultdict(list)
    for rel, _py, tree in files:
        for qual, fn in iter_funcs(tree):
            if len(fn.body) == 0:
                continue
            buckets[shape_hash(fn)].append((rel, qual, fn))

    clones = []
    for h, group in buckets.items():
        if len(group) < 2:
            continue
        lines = src_lines(group[0][2])
        payload = payload_lines(group[0][2])
        # only report groups that are not trivially tiny
        if lines < 4:
            continue
        total_waste = lines * (len(group) - 1)
        payload_waste = payload * (len(group) - 1)
        clones.append({
            "hash": h[:12],
            "lines_each": lines,
            "payload_each": payload,
            "copies": len(group),
            "wasted": total_waste,
            "payload_wasted": payload_waste,
            "sites": [f"{rel}:{fn.lineno} {qual}" for rel, qual, fn in group],
        })
    clones.sort(key=lambda c: -c["payload_wasted"])
    return clones


# ---------------------------------------------------------------- 2. forwarders
def is_pure_forward(fn) -> tuple[bool, str]:
    """Function body is a single return of a call -> pure forwarding."""
    body = fn.body
    if len(body) != 1:
        return False, ""
    stmt = body[0]
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False, ""
    v = stmt.value
    if not isinstance(v, ast.Call):
        return False, ""
    func = v.func
    if isinstance(func, ast.Attribute):
        target = func.value
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            return True, f"{target.value.id}.{target.attr}.{func.attr}"
        if isinstance(target, ast.Name):
            return True, f"{target.id}.{func.attr}"
    return False, ""


def detect_forwarders(files) -> dict:
    per_file = defaultdict(lambda: {"total_lines": 0, "fwd_lines": 0, "fwd_count": 0, "real_count": 0})
    detail = []
    for rel, _py, tree in files:
        for qual, fn in iter_funcs(tree):
            ok, callee = is_pure_forward(fn)
            lines = src_lines(fn)
            key = str(rel)
            per_file[key]["total_lines"] += lines
            if ok:
                per_file[key]["fwd_lines"] += lines
                per_file[key]["fwd_count"] += 1
                detail.append((str(rel), fn.lineno, qual, callee, lines))
            else:
                per_file[key]["real_count"] += 1
    return {"per_file": dict(per_file), "detail": detail}


# ---------------------------------------------------------------- 3. cycles
def module_name(rel: Path) -> str:
    parts = list(rel.parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def detect_imports(files) -> dict[str, set[str]]:
    """module -> set of intra-package modules it imports."""
    g: dict[str, set[str]] = defaultdict(set)
    for rel, _py, tree in files:
        mod = module_name(rel)
        pkg = mod.rsplit(".", 1)[0] if "." in mod else mod
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("llmwikify"):
                        g[mod].add(a.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import
                    base = pkg.split(".")
                    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                    target = ".".join(base + ([node.module] if node.module else []))
                    g[mod].add(target)
                elif node.module and node.module.startswith("llmwikify"):
                    g[mod].add(node.module)
    return g


def scc_cycles(g: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan SCC on module import graph."""
    index = {}
    low = {}
    stack = []
    onstack = set()
    counter = [0]
    out = []

    for root in list(g):
        if root in index:
            continue
        work = [(root, iter(g.get(root, ())))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        onstack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in g:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    onstack.add(nxt)
                    work.append((nxt, iter(g.get(nxt, ()))))
                    advanced = True
                    break
                elif nxt in onstack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return out


# ---------------------------------------------------------------- 4. layers
def layer_of_module(mod: str) -> str | None:
    parts = mod.split(".")
    if len(parts) >= 2 and parts[0] == "llmwikify" and parts[1] in LAYERS:
        return parts[1]
    return None


def detect_layer_violations(files) -> list[tuple]:
    out = []
    for rel, _py, tree in files:
        mod = module_name(rel)
        layer = layer_of_module(mod)
        if layer is None:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                targets = [node.module]
            for t in targets:
                tl = layer_of_module(t)
                if tl is None or tl == layer:
                    continue
                if layer == "kernel" and tl in ("apps", "interfaces"):
                    out.append((str(rel), node.lineno, layer, tl, t))
                if layer == "foundation" and tl in ("kernel", "apps", "interfaces"):
                    out.append((str(rel), node.lineno, layer, tl, t))
                if layer == "apps" and tl == "interfaces":
                    out.append((str(rel), node.lineno, layer, tl, t))
    return out


def detect_root_deps(files) -> list[tuple]:
    """kernel (or any layer) importing the package root `llmwikify` itself."""
    out = []
    for rel, _py, tree in files:
        mod = module_name(rel)
        layer = layer_of_module(mod)
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                targets = [node.module]
            for t in targets:
                if t == "llmwikify":
                    out.append((str(rel), node.lineno, layer or "?", t))
    return out


# ---------------------------------------------------------------- 5. fan-in
def compute_fan(files) -> tuple[dict, dict]:
    g = detect_imports(files)
    fan_in = defaultdict(set)
    fan_out = defaultdict(set)
    for a, deps in g.items():
        fan_out[a] |= deps
        for b in deps:
            fan_in[b].add(a)
    return dict(fan_in), dict(fan_out)


# ---------------------------------------------------------------- main
def main() -> None:
    files = collect()
    print(f"# parsed {len(files)} modules under {SRC}\n")

    out = {}

    print("=" * 72)
    print("1. EXACT CLONES (AST structure hash, >=4 lines)")
    print("=" * 72)
    clones = detect_clones(files)
    total_waste = sum(c["wasted"] for c in clones)
    for c in clones[:20]:
        print(
            f"\n[{c['hash']}] {c['lines_each']}L x{c['copies']}  "
            f"payload={c['payload_each']}L/group  "
            f"waste_doc={c['wasted']}L  waste_payload={c['payload_wasted']}L"
        )
        for s in c["sites"]:
            print(f"    {s}")
    print(f"\n-- total clone waste: {total_waste} lines across {len(clones)} groups")
    total_payload = sum(c["payload_wasted"] for c in clones)
    print(
        f"-- total clone waste (payload only, excl. docstrings): "
        f"{total_payload} lines across {len(clones)} groups"
    )
    out["clones"] = clones
    out["clone_waste_total"] = total_waste
    out["clone_payload_waste_total"] = total_payload

    print()
    print("=" * 72)
    print("2. FORWARDING LAYERS")
    print("=" * 72)
    fwd = detect_forwarders(files)
    rows = []
    for f, d in fwd["per_file"].items():
        if d["fwd_lines"] > 0:
            rows.append((f, d))
    rows.sort(key=lambda r: -r[1]["fwd_lines"])
    print(f"{'file':<58} {'tot':>6} {'fwdL':>6} {'#fwd':>5} {'#real':>6}")
    tf = 0
    for f, d in rows:
        tf += d["fwd_lines"]
        print(f"{f:<58} {d['total_lines']:>6} {d['fwd_lines']:>6} {d['fwd_count']:>5} {d['real_count']:>6}")
    print(f"-- total forwarding lines: {tf}")
    out["forwarders"] = {"per_file": rows, "total_fwd_lines": tf}

    print()
    print("=" * 72)
    print("3. IMPORT CYCLES (module SCC)")
    print("=" * 72)
    g = detect_imports(files)
    cycles = scc_cycles(g)
    for c in cycles:
        print(f"  cycle ({len(c)}): {', '.join(c)}")
    print(f"-- {len(cycles)} cycles")
    out["cycles"] = cycles

    print()
    print("=" * 72)
    print("4. LAYER VIOLATIONS")
    print("=" * 72)
    lv = detect_layer_violations(files)
    for v in lv:
        print(f"  {v[0]}:{v[1]}  {v[2]} -> {v[3]}  ({v[4]})")
    print(f"-- {len(lv)} violations")
    out["layer_violations"] = lv

    print()
    print("=" * 72)
    print("4b. IMPORTS OF PACKAGE ROOT `llmwikify`")
    print("=" * 72)
    rd = detect_root_deps(files)
    for v in rd:
        print(f"  {v[0]}:{v[1]}  layer={v[2]}  -> {v[3]}")
    print(f"-- {len(rd)} root imports")
    out["root_deps"] = rd

    print()
    print("=" * 72)
    print("5. MODULE FAN-IN (top 25)")
    print("=" * 72)
    fan_in, fan_out = compute_fan(files)
    for m, deps in sorted(fan_in.items(), key=lambda kv: -len(kv[1]))[:25]:
        print(f"  {len(deps):>4}  {m}")
    out["fan_in_top"] = [(m, len(d)) for m, d in sorted(fan_in.items(), key=lambda kv: -len(kv[1]))[:30]]

    # Optional JSON dump: `python scripts/clone_survey.py [out.json]`
    if len(sys.argv) > 1:
        out_path = Path(sys.argv[1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"\n[written] {out_path}")
    else:
        print("\n[tip] pass an output path to also dump JSON, e.g. `clone_survey.py out.json`")

if __name__ == "__main__":
    main()
