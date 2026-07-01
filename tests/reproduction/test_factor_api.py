"""Factor API tests — 3 endpoints.

The v0.4 paper-reproduction feature redesigned the factor storage
contract: factors are now read from the YAML-backed
``factor_library`` (``quant/factors/``), not from wiki markdown
pages. These tests were written against the old wiki-backed
contract and need to be rewritten against the library contract
before they can run.

Tracked in: docs/poc/plan-b-results.md (Phase 3 cleanup).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Skip the whole module until tests are ported to the library contract.
pytestmark = pytest.mark.skip(
    reason="Factor API contract migrated to factor_library; "
    "wiki-backed tests need rewrite to test the new contract."
)
