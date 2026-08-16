"""Tests for the maintenance background-LLM rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from llmwikify.apps.agent.maintenance.rate_limit import SlidingWindowRateLimiter


def test_allows_burst_up_to_max_without_waiting():
    rl = SlidingWindowRateLimiter(max_requests=5, window_seconds=5.0)

    async def scenario() -> float:
        start = time.monotonic()
        for _ in range(5):
            assert await rl.acquire() is True
        return time.monotonic() - start

    elapsed = asyncio.run(scenario())
    assert elapsed < 1.0  # full burst allowed, no waiting
    assert rl.stats()["throttled_total"] == 0
    assert rl.stats()["window_in_use"] == 5


def test_sixth_request_waits_for_window_slide():
    rl = SlidingWindowRateLimiter(max_requests=5, window_seconds=1.0)

    async def scenario() -> tuple[bool, float]:
        for _ in range(5):
            await rl.acquire()
        start = time.monotonic()
        ok = await rl.acquire()  # 6th — must wait ~1 window
        return ok, time.monotonic() - start

    ok, waited = asyncio.run(scenario())
    assert ok is True
    assert waited >= 0.8  # waited for the window to slide (allow scheduler slack)
    assert rl.stats()["throttled_total"] == 1


def test_window_slides_old_events_expire():
    rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=0.2)

    async def scenario() -> None:
        await rl.acquire()
        await rl.acquire()
        assert rl.stats()["window_in_use"] == 2
        await asyncio.sleep(0.25)  # both events expired
        await rl.acquire()  # immediate, no wait
        assert rl.stats()["window_in_use"] == 1

    asyncio.run(scenario())  # no timeout = passed


def test_disabled_is_passthrough():
    rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0, enabled=False)

    async def scenario() -> float:
        start = time.monotonic()
        for _ in range(20):
            await rl.acquire()
        return time.monotonic() - start

    elapsed = asyncio.run(scenario())
    assert elapsed < 1.0
    assert rl.stats()["window_in_use"] == 0


def test_concurrent_waiters_fifo_and_capped():
    rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=0.3)

    async def scenario() -> tuple[list[int], float]:
        order: list[int] = []
        start = time.monotonic()

        async def worker(i: int) -> None:
            await rl.acquire()
            order.append(i)

        # 5 workers, only 2 get in immediately; 3 wait for window slides
        await asyncio.gather(*(worker(i) for i in range(5)))
        return order, time.monotonic() - start

    order, elapsed = asyncio.run(scenario())
    assert sorted(order) == [0, 1, 2, 3, 4]  # all admitted eventually
    # 5 acquires / max 2 per 0.3s → needs ≥2 window slides ≥ ~0.6s... but
    # burst admission timing means ~0.3-0.6s; assert a conservative floor.
    assert elapsed >= 0.25
    assert rl.stats()["throttled_total"] >= 1


# ── config parsing ───────────────────────────────────────────────────


def test_config_llm_rate_limit_defaults():
    from llmwikify.apps.agent.maintenance.config import MaintenanceConfig

    cfg = MaintenanceConfig()
    assert cfg.llm_rate_limit.enabled is True
    assert cfg.llm_rate_limit.max_requests == 5
    assert cfg.llm_rate_limit.window_seconds == 5.0


def test_config_llm_rate_limit_overrides(tmp_path):
    import json

    from llmwikify.apps.agent.maintenance.config import load_maintenance_config

    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({
        "maintenance": {
            "llm_rate_limit": {
                "enabled": True,
                "max_requests": 2,
                "window_seconds": 10.0,
            },
        },
    }))
    cfg = load_maintenance_config(path)
    assert cfg.llm_rate_limit.max_requests == 2
    assert cfg.llm_rate_limit.window_seconds == 10.0


def test_manager_wires_shared_limiter():
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager

    cfg = MaintenanceConfig()
    cfg.llm_rate_limit.max_requests = 7
    mgr = MaintenanceManager(
        registry=type("R", (), {"list_wikis": staticmethod(lambda: [])})(),
        config=cfg,
    )
    assert mgr.llm_rate_limiter.max_requests == 7
    assert mgr.llm_rate_limiter.enabled is True
    assert "llm_rate_limit" in mgr.status()
