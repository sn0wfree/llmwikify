"""Web interface layer (L4) — HTTP server entry points.

This package provides the Python-side entry points for the
unified web interface (MCP + REST API + WebUI). The actual
HTML/JS assets live at the top-level ``ui/`` directory (not
inside the Python package) and are loaded at runtime.

Per the 4-layer architecture (foundation | kernel | apps | interfaces),
this package lives at the topmost layer and may only depend on
foundation (L1). It must not import from kernel (L2) or apps (L3).

See ``docs/designs/refactor-4layer-architecture.md`` for the full
architecture plan and import-linter contracts.

Public API:
  - server: ``python -m llmwikify.interfaces.web.server`` entry
"""
