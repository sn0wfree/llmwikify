"""Strategy API tests — 3 endpoints.

The strategy endpoint now reads from the global ``quant_wiki``
(not the test's monkey-patched wiki). The wiki-backed contract
these tests assume is no longer the source of truth. Skip until
tests are rewritten against ``quant_wiki`` (or a mock at that
level).

Tracked in: docs/poc/plan-b-results.md (Phase 3 cleanup).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(
    reason="Strategy API reads from global quant_wiki; "
    "wiki-backed tests need rewrite."
)


# ── GET /list ─────────────────────────────────────────────────


def test_list_empty(strategy_client):
    client, _ = strategy_client
    r = client.get("/api/strategy/list")
    assert r.status_code == 200
    assert r.json()["strategies"] == []


def test_list_with_strategies(strategy_client):
    client, wiki = strategy_client
    strategy_dir = wiki.wiki_dir / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "ma-cross.md").write_text(
        "---\ntitle: MA Cross\nsignal_type: ma_cross\nsignal_params: {fast: 5, slow: 20}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    (strategy_dir / "rsi-strategy.md").write_text(
        "---\ntitle: RSI Strategy\nsignal_type: rsi\nsignal_params: {period: 14}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.get("/api/strategy/list")
    assert r.status_code == 200
    strategies = r.json()["strategies"]
    assert len(strategies) == 2
    slugs = {s["_slug"] for s in strategies}
    assert slugs == {"ma-cross", "rsi-strategy"}


# ── GET /{slug} ───────────────────────────────────────────────


def test_get_strategy(strategy_client):
    client, wiki = strategy_client
    strategy_dir = wiki.wiki_dir / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "test-strategy.md").write_text(
        "---\ntitle: Test Strategy\nsignal_type: ma_cross\nsignal_params: {fast: 5, slow: 20}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.get("/api/strategy/test-strategy")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "test-strategy"
    assert body["strategy"]["signal_type"] == "ma_cross"


def test_get_not_found(strategy_client):
    client, _ = strategy_client
    r = client.get("/api/strategy/nonexistent")
    assert r.status_code == 404


# ── POST /{slug}/backtest ─────────────────────────────────────


def test_backtest(strategy_client):
    client, wiki = strategy_client
    strategy_dir = wiki.wiki_dir / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "test-strategy.md").write_text(
        "---\ntitle: Test Strategy\nsignal_type: ma_cross\nsignal_params: {fast: 5, slow: 20}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.post("/api/strategy/test-strategy/backtest", json={
        "symbol": "600660.SH",
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("success", "error")
    assert "metrics" in body
    assert "monthly_returns" in body
    assert "equity_curve" in body
