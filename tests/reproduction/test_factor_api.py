"""Factor API tests — 3 endpoints."""

from __future__ import annotations

from pathlib import Path


# ── GET /list ─────────────────────────────────────────────────


def test_list_empty(factor_client):
    client, _ = factor_client
    r = client.get("/api/factor/list")
    assert r.status_code == 200
    assert r.json()["factors"] == []


def test_list_with_factors(factor_client):
    client, wiki = factor_client
    factor_dir = wiki.wiki_dir / "factor"
    factor_dir.mkdir(parents=True, exist_ok=True)
    (factor_dir / "momentum-60d.md").write_text(
        "---\ntitle: Momentum 60d\nfactor_class: momentum\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    (factor_dir / "rsi-14d.md").write_text(
        "---\ntitle: RSI 14d\nfactor_class: rsi\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.get("/api/factor/list")
    assert r.status_code == 200
    factors = r.json()["factors"]
    assert len(factors) == 2
    slugs = {f["_slug"] for f in factors}
    assert slugs == {"momentum-60d", "rsi-14d"}


# ── GET /{slug} ───────────────────────────────────────────────


def test_get_factor(factor_client):
    client, wiki = factor_client
    factor_dir = wiki.wiki_dir / "factor"
    factor_dir.mkdir(parents=True, exist_ok=True)
    (factor_dir / "test-factor.md").write_text(
        "---\ntitle: Test Factor\nfactor_class: momentum\nfactor_params: {lookback: 60}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.get("/api/factor/test-factor")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "test-factor"
    assert body["factor"]["factor_class"] == "momentum"


def test_get_not_found(factor_client):
    client, _ = factor_client
    r = client.get("/api/factor/nonexistent")
    assert r.status_code == 404


# ── POST /{slug}/backtest ─────────────────────────────────────


def test_backtest(factor_client):
    client, wiki = factor_client
    factor_dir = wiki.wiki_dir / "factor"
    factor_dir.mkdir(parents=True, exist_ok=True)
    (factor_dir / "test-factor.md").write_text(
        "---\ntitle: Test Factor\nfactor_class: momentum\nfactor_params: {lookback: 60}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.post("/api/factor/test-factor/backtest", json={
        "universe": "single",
        "symbol": "600660.SH",
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["factor"]["factor_class"] == "momentum"
    assert "metrics" in body
    assert "ic_series" in body
    assert "quantile_curves" in body
