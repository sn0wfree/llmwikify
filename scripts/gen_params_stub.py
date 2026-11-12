#!/usr/bin/env python3
"""Generate ``src/llmwikify/foundation/params.pyi`` from the parameter registry.

The runtime views (``FoundationParams`` / ``KernelParams`` / …) build their
attribute structure dynamically from ``PARAMS`` via :func:`nest`, so no field
is hand-written. This script emits the matching static type stub so mypy and
IDEs see the nested attributes.

Drift between the registry and the stub is caught by
``tests/test_foundation_params.py::test_generated_stub_is_current``, which
re-runs :func:`build` and compares it to the file on disk. After editing
``foundation/params.py``, run::

    python scripts/gen_params_stub.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from llmwikify.foundation.params import PARAMS, Param  # noqa: E402

STUB_PATH = REPO_ROOT / "src" / "llmwikify" / "foundation" / "params.pyi"

# Layer → (module-level view class name, one-line doc).
LAYER_VIEWS: list[tuple[str, str, str]] = [
    ("foundation", "FoundationParams", "L1 (foundation) view — ``llm.*``."),
    ("kernel", "KernelParams", "L2 (kernel) view — ``wiki.*``, ``directories.*``, …"),
    ("apps", "AppsParams", "L3 (apps) view — ``chat_mutable.*``, ``research*``."),
    ("interfaces", "InterfacesParams", "L4 (interfaces) view — ``mcp.*``, ``web.*``."),
]

_TYPE_NAMES: dict[type, str] = {
    int: "int",
    str: "str",
    float: "float",
    bool: "bool",
    list: "list[Any]",
}


def _type_name(spec: Param) -> str:
    if spec.type is None:
        return "Any"
    return _TYPE_NAMES.get(spec.type, "Any")


def _camel(path: str) -> str:
    """``search.qmd`` → ``SearchQmd``; ``chat_mutable`` → ``ChatMutable``."""
    parts: list[str] = []
    for seg in path.split("."):
        for word in seg.split("_"):
            parts.append(word[:1].upper() + word[1:])
    return "".join(parts)


def _section_tree(keys: list[str]) -> dict[str, object]:
    """Build ``{segment: subtree-or-leaf}`` from dotted keys."""
    tree: dict[str, object] = {}
    for key in keys:
        parts = key.split(".")
        node: dict[str, object] = tree
        for part in parts[:-1]:
            nxt = node.setdefault(part, {})
            assert isinstance(nxt, dict), key
            node = nxt
        node[parts[-1]] = None  # leaf marker
    return tree


def _emit_sections(tree: dict[str, object], prefix: str, out: list[str]) -> None:
    """Emit one class per section path, depth-first."""
    for seg, subtree in tree.items():
        if not isinstance(subtree, dict):
            continue
        path = f"{prefix}.{seg}" if prefix else seg
        class_name = f"{_camel(path)}Section"
        leaves = [
            (name, val)
            for name, val in subtree.items()
            if not isinstance(val, dict)
        ]
        nested = [
            (name, val)
            for name, val in subtree.items()
            if isinstance(val, dict)
        ]
        out.append(f"class {class_name}:")
        out.append(f'    """{path} section."""')
        out.append("")
        for name, _ in leaves:
            # Look up the full key for its declared type.
            full = f"{path}.{name}"
            spec = PARAMS.get(full)
            out.append(f"    {name}: {_type_name(spec) if spec else 'Any'}")
        for name, _ in nested:
            out.append(f"    {name}: {_camel(f'{path}.{name}')}Section")
        if not leaves and not nested:  # pragma: no cover - empty section
            out.append("    ...")
        out.append("")
        _emit_sections(subtree, path, out)


def build() -> str:
    """Return the full text of ``params.pyi``."""
    lines: list[str] = [
        '"""Type stub for llmwikify.foundation.params — GENERATED, do not edit.',
        "",
        "Regenerate with ``python scripts/gen_params_stub.py`` after changing",
        "the registry. Drift is caught by tests/test_foundation_params.py.",
        '"""',
        "",
        "import builtins",
        "from collections.abc import Mapping",
        "from typing import Any, ClassVar",
        "",
        "class Param:",
        '    """One declared parameter (see the runtime dataclass)."""',
        "",
        "    default: Any",
        "    type: builtins.type | None",
        "    doc: str",
        "    layer: str",
        "    env: str | None",
        "    hot_reloadable: bool",
        "    deprecated: bool",
        "    alias_of: str | None",
        "    def __init__(",
        "        self,",
        "        default: Any,",
        "        type: builtins.type | None,",
        "        doc: str,",
        "        layer: str,",
        "        env: str | None = ...,",
        "        hot_reloadable: bool = ...,",
        "        deprecated: bool = ...,",
        "        alias_of: str | None = ...,",
        "    ) -> None: ...",
        "",
    ]

    # Section classes, deduplicated by path across all layers.
    all_keys = sorted(PARAMS)
    section_classes: list[str] = []
    _emit_sections(_section_tree(all_keys), "", section_classes)
    lines.extend(section_classes)

    # View classes, one per layer.
    for layer, cls_name, doc in LAYER_VIEWS:
        keys = sorted(k for k, p in PARAMS.items() if p.layer == layer)
        top_segments = sorted({k.split(".")[0] for k in keys})
        lines.append(f"class {cls_name}:")
        lines.append(f'    """{doc}"""')
        lines.append("")
        lines.append("    LAYER: ClassVar[str]")
        lines.append("")
        for seg in top_segments:
            lines.append(f"    {seg}: {_camel(seg)}Section")
        lines.append("")
        lines.append(
            "    def __init__(self, values: Mapping[str, Any] | None = None) -> None: ..."
        )
        lines.append(
            "    def __getattr__(self, name: str) -> Any: ..."
        )
        lines.append(
            "    @classmethod"
        )
        lines.append(
            "    def layer_keys(cls) -> frozenset[str]: ..."
        )
        lines.append("")

    # Registry-level helpers the stub must also describe: a sibling
    # ``.pyi`` *shadows* the runtime ``.py`` for mypy, so every name the
    # runtime module exports has to appear here too.
    lines.extend(
        [
            "PARAMS: dict[str, Param]",
            "",
            "def param_default(key: str, fallback: Any = None) -> Any: ...",
            "def param_spec(key: str) -> Param: ...",
            "def has_param(key: str) -> bool: ...",
            "def params_under(prefix: str) -> dict[str, Param]: ...",
            "def defaults_for_prefix(prefix: str) -> dict[str, Any]: ...",
            "def section_defaults(prefix: str) -> dict[str, Any]: ...",
            "def canonical_key(key: str) -> str: ...",
            "def aliases_of(key: str) -> list[str]: ...",
            "def nest(values: Mapping[str, Any]) -> Any: ...",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    text = build()
    STUB_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {STUB_PATH} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
