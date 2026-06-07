"""Non-Python template assets shipped with llmwikify.

This package contains MCP config templates and agent skill
documents. The data files are loaded at runtime via
``importlib.resources`` (or the path computed in
``core.wiki_mixin_utility.TEMPLATES_DIR``) by the init
mixin and the MCP CLI commands.

Access patterns:
    - From Python: ``from llmwikify.foundation import templates``
      then ``templates.opencode_json`` etc. (each data file is
      exposed as a module attribute).
    - From disk: path is
      ``llmwikify/foundation/templates/<file>``.
"""
from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

# Expose each data file as a module attribute so callers can do
# ``templates.opencode_json`` etc. The values are Path objects
# (not file contents) — the init mixin reads them with
# ``Path.read_text()`` because the files may contain user-editable
# content that we want to copy verbatim.
opencode_json = _PACKAGE_DIR / "opencode.json"
claude_mcp_json = _PACKAGE_DIR / "claude_mcp.json"
codex_mcp_json = _PACKAGE_DIR / "codex_mcp.json"
_gitignore = _PACKAGE_DIR / "_gitignore"

# skill_llmwikify/ is a directory of markdown files; expose the
# directory itself so the init mixin can list its contents.
skill_llmwikify = _PACKAGE_DIR / "skill_llmwikify"


__all__ = [
    "opencode_json",
    "claude_mcp_json",
    "codex_mcp_json",
    "_gitignore",
    "skill_llmwikify",
]
