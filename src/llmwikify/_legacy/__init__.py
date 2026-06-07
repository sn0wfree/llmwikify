"""Backward-compatibility shims for the 4-layer refactor.

The shims in this package preserve public-API entry points that
were moved during the 4-layer refactor (Batches B1–C1, see
``docs/designs/refactor-4layer-architecture.md``). Each shim is
a one-liner that re-exports the canonical symbol from its new
home and emits a ``DeprecationWarning`` so external users get a
clear migration signal.

All shims are scheduled for removal in v0.33.0 (one release
cycle of deprecation after the move).

Current contents:

- ``mcp_server``            — added in B2 (B2.5)
- ``create_unified_server`` — added in B2 (B2.5)
- ``agent``                 — added in B4
- ``adapters``              — added in B4
- ``autoresearch``          — added in C1
"""
