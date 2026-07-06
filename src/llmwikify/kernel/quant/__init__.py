"""kernel/quant/ — backward-compat shim (v0.40).

Historical: this subpackage held quant-domain abstractions shared between
``apps/`` and ``reproduction/``. After v0.40's quant strip (Phase 1) and
the G+Y architecture refactor:

  - ``codegen/`` (C1) was renamed to ``kernel/codegen/`` (G+Y commit 5),
    because the contents are generic code-generation primitives, not
    quant-specific. See ``kernel/codegen/__init__.py``.
  - ``data_source/`` (planned C3) was never implemented; ``reproduction/``
    was deleted in v0.40, so the use case is gone.

What remains:

  - ``llm_client.py`` — re-exports ``build_llm_client`` /
    ``load_llm_config`` / ``CONFIG_PATH`` from
    ``llmwikify.foundation.llm.client``. Kept as a back-compat
    shim for legacy imports; new code should import from
    ``foundation.llm.client`` directly.
"""

