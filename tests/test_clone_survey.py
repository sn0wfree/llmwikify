"""Tests for scripts/clone_survey.py.

The script is the AST-level evidence tool behind
``docs/designs/code-reuse-optimization.md`` and
``docs/designs/codebase-survey.md``. Its numbers are cited in review
decisions, so every detector it has needs a regression net — including
the layer-violation detector, which silently returned ``[]`` for every
input because ``module_name()`` already yields a fully-qualified
``llmwikify.*`` name and the caller prepended ``"llmwikify."`` a second
time (``llmwikify.llmwikify.kernel.x`` → no layer → skipped).
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "clone_survey.py"


@pytest.fixture(scope="module")
def cs():
    """The survey script, imported as a module (not an installed package)."""
    spec = importlib.util.spec_from_file_location("clone_survey", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk(root: Path, rel: str, body: str):
    """Write a file and return the (rel, path, tree) triple the API expects."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return (Path(rel), p, ast.parse(body))


def _fn(src: str):
    """Parse a snippet and return its single function definition."""
    return ast.parse(src).body[0]


# ─── normalizer / hashing ─────────────────────────────────────────────


def test_shape_hash_ignores_identifier_names(cs) -> None:
    """Renamed locals/params must not change the structural hash."""
    a = _fn("def f(x):\n    y = x + 1\n    return y\n")
    b = _fn("def g(z):\n    w = z + 1\n    return w\n")
    assert cs.shape_hash(a) == cs.shape_hash(b)


def test_shape_hash_differs_on_different_structure(cs) -> None:
    a = _fn("def f(x):\n    y = x + 1\n    return y\n")
    b = _fn("def f(x):\n    if x:\n        return 1\n    return 2\n")
    assert cs.shape_hash(a) != cs.shape_hash(b)


def test_shape_hash_keeps_callee_names(cs) -> None:
    """Callee identity is part of the API — collapsing it invents clones.

    ``run_init(...)`` and ``run_ingest(...)`` have isomorphic bodies but
    are different calls; the tool must not merge them.
    """
    a = _fn("def f():\n    return run_init(1)\n")
    b = _fn("def g():\n    return run_ingest(1)\n")
    assert cs.shape_hash(a) != cs.shape_hash(b)


def test_shape_hash_distinguishes_literal_types(cs) -> None:
    """Literal *values* are normalized to their type — but types differ."""
    a = _fn("def f():\n    return 1\n")
    b = _fn("def g():\n    return 'x'\n")
    assert cs.shape_hash(a) != cs.shape_hash(b)


def test_shape_hash_ignores_function_name(cs) -> None:
    a = _fn("def alpha():\n    return 1\n")
    b = _fn("def beta():\n    return 1\n")
    assert cs.shape_hash(a) == cs.shape_hash(b)


# ─── line accounting ──────────────────────────────────────────────────


def test_src_lines_counts_physical_lines(cs) -> None:
    fn = _fn("def f():\n    a = 1\n    b = 2\n    return a\n")
    assert cs.src_lines(fn) == 4


def test_payload_lines_excludes_docstring(cs) -> None:
    """Docstrings must not count as duplicated *logic*."""
    fn = _fn('def f():\n    """Doc."""\n    a = 1\n    return a\n')
    assert cs.payload_lines(fn) == 2
    assert cs.src_lines(fn) == 4


def test_payload_lines_counts_ellipsis_stub_as_one_line(cs) -> None:
    """A Protocol stub body is ``...`` — one payload line, not real logic."""
    fn = _fn('def f(self):\n    """Doc."""\n    ...\n')
    assert cs.payload_lines(fn) == 1


def test_iter_funcs_finds_nested_methods(cs) -> None:
    tree = ast.parse(
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
        "    def n(self):\n"
        "        return 2\n"
        "def top():\n"
        "    return 3\n"
    )
    quals = [q for q, _ in cs.iter_funcs(tree)]
    assert "C.m" in quals
    assert "C.n" in quals
    assert "top" in quals


# ─── clone detection ──────────────────────────────────────────────────

_CLONE_BODY = """
def {name}(items):
    total = 0
    for it in items:
        total += it.value
    return total
"""


def test_detect_clones_finds_cross_file_clone(cs, tmp_path) -> None:
    files = [
        _mk(tmp_path, "src/llmwikify/apps/a.py", _CLONE_BODY.format(name="alpha")),
        _mk(tmp_path, "src/llmwikify/kernel/b.py", _CLONE_BODY.format(name="beta")),
    ]
    clones = cs.detect_clones(files)
    assert len(clones) == 1
    c = clones[0]
    assert c["copies"] == 2
    assert len(c["sites"]) == 2
    assert c["payload_wasted"] > 0


def test_detect_clones_skips_tiny_functions(cs, tmp_path) -> None:
    """Groups below the 4-line floor are noise, not waste."""
    body = "def {name}(x):\n    return x\n"
    files = [
        _mk(tmp_path, "src/llmwikify/apps/a.py", body.format(name="alpha")),
        _mk(tmp_path, "src/llmwikify/kernel/b.py", body.format(name="beta")),
    ]
    assert cs.detect_clones(files) == []


def test_detect_clones_does_not_merge_different_callees(cs, tmp_path) -> None:
    a = "def f(x):\n    return run_init(x)\n    return run_init(x)\n"
    b = "def g(x):\n    return run_ingest(x)\n    return run_ingest(x)\n"
    files = [
        _mk(tmp_path, "src/llmwikify/apps/a.py", a),
        _mk(tmp_path, "src/llmwikify/kernel/b.py", b),
    ]
    assert cs.detect_clones(files) == []


# ─── forwarder detection ──────────────────────────────────────────────


def test_is_pure_forward_detects_method_forward(cs) -> None:
    fn = _fn("def f(self):\n    return self.db.create(x)\n")
    ok, callee = cs.is_pure_forward(fn)
    assert ok
    assert callee == "self.db.create"


def test_is_pure_forward_detects_attribute_forward(cs) -> None:
    fn = _fn("def f(self):\n    return self.helper(x)\n")
    ok, callee = cs.is_pure_forward(fn)
    assert ok
    assert callee == "self.helper"


def test_is_pure_forward_rejects_real_logic(cs) -> None:
    fn = _fn("def f(self):\n    x = 1\n    return x\n")
    ok, _ = cs.is_pure_forward(fn)
    assert not ok


def test_detect_forwarders_counts(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/apps/x.py",
            "def fwd(self):\n    return self.db.create(x)\n"
            "def real(self):\n    a = 1\n    return a\n",
        ),
    ]
    out = cs.detect_forwarders(files)
    key = next(iter(out["per_file"]))
    stats = out["per_file"][key]
    assert stats["fwd_count"] == 1
    assert stats["real_count"] == 1
    assert stats["fwd_lines"] > 0


# ─── module naming / import graph ────────────────────────────────────


def test_module_name(cs) -> None:
    assert (
        cs.module_name(Path("src/llmwikify/apps/chat/db.py"))
        == "llmwikify.apps.chat.db"
    )
    assert (
        cs.module_name(Path("src/llmwikify/apps/chat/__init__.py"))
        == "llmwikify.apps.chat"
    )


def test_layer_of_module(cs) -> None:
    assert cs.layer_of_module("llmwikify.kernel.x") == "kernel"
    assert cs.layer_of_module("llmwikify.foundation.x") == "foundation"
    assert cs.layer_of_module("llmwikify.notalayer.x") is None
    assert cs.layer_of_module("llmwikify") is None


def test_detect_imports_absolute_and_relative(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/kernel/a.py",
            "from llmwikify.foundation.db import get_connection\n"
            "import llmwikify.kernel.b\n"
            "from . import c\n",
        ),
    ]
    g = cs.detect_imports(files)
    deps = g["llmwikify.kernel.a"]
    assert "llmwikify.foundation.db" in deps
    assert "llmwikify.kernel.b" in deps
    assert "llmwikify.kernel" in deps  # `from . import c` resolves to the package


def test_scc_cycles_finds_cycle(cs) -> None:
    g = {"a": {"b"}, "b": {"a"}, "c": {"a"}}
    cycles = cs.scc_cycles(g)
    assert ["a", "b"] in cycles
    assert ["a", "b", "c"] not in cycles


def test_scc_cycles_ignores_acyclic_graph(cs) -> None:
    assert cs.scc_cycles({"a": {"b"}, "b": set()}) == []


# ─── layer violations (the detector that was silently dead) ───────────


def test_detect_layer_violations_flags_kernel_to_apps(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/kernel/bad.py",
            "from llmwikify.apps.chat.db import ChatDatabase\n",
        ),
    ]
    violations = cs.detect_layer_violations(files)
    assert len(violations) == 1
    assert violations[0][2] == "kernel"
    assert violations[0][3] == "apps"


def test_detect_layer_violations_flags_foundation_to_kernel(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/foundation/bad.py",
            "from llmwikify.kernel.agent import Agent\n",
        ),
    ]
    violations = cs.detect_layer_violations(files)
    assert len(violations) == 1
    assert violations[0][2] == "foundation"


def test_detect_layer_violations_allows_legal_direction(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/kernel/ok.py",
            "from llmwikify.foundation.db import get_connection\n",
        ),
    ]
    assert cs.detect_layer_violations(files) == []


def test_detect_root_deps_labels_the_layer(cs, tmp_path) -> None:
    """A root import must be reported *with* its layer, not '?'."""
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/kernel/root.py",
            "from llmwikify import __version__\n",
        ),
    ]
    out = cs.detect_root_deps(files)
    assert len(out) == 1
    assert out[0][2] == "kernel"


# ─── fan-in / fan-out ─────────────────────────────────────────────────


def test_compute_fan(cs, tmp_path) -> None:
    files = [
        _mk(
            tmp_path,
            "src/llmwikify/kernel/a.py",
            "from llmwikify.foundation.db import get_connection\n",
        ),
        _mk(
            tmp_path,
            "src/llmwikify/kernel/b.py",
            "from llmwikify.foundation.db import connect\n",
        ),
    ]
    fan_in, fan_out = cs.compute_fan(files)
    assert "llmwikify.foundation.db" in fan_in
    assert len(fan_in["llmwikify.foundation.db"]) == 2
    assert "llmwikify.foundation.db" in fan_out["llmwikify.kernel.a"]
