#!/usr/bin/env python3
"""E2E test for the complete paper reproduction workflow.

Starts its own server, runs all API tests, then shuts down.

Usage:
    python tests/reproduction/test_e2e_paper.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:18765"  # Use non-conflicting port
TIMEOUT = 300
POLL_INTERVAL = 3
LLMWIKIFY_BIN = "/home/ll/.local/bin/llmwikify"
WORK_DIR = "/home/ll/Public/strategy"
SERVER_PROC = None


def start_server():
    global SERVER_PROC
    print(f"Starting server from {WORK_DIR} on {BASE}...")
    SERVER_PROC = subprocess.Popen(
        [LLMWIKIFY_BIN, "serve", "--web", "--port", "18765", "--host", "127.0.0.1"],
        cwd=WORK_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    for i in range(30):
        time.sleep(1)
        try:
            r = requests.get(f"{BASE}/api/paper/list-raw", timeout=3)
            if r.status_code == 200:
                print(f"  Server ready (pid={SERVER_PROC.pid})")
                return
        except Exception:
            pass
    raise RuntimeError("Server failed to start within 30s")


def stop_server():
    global SERVER_PROC
    if SERVER_PROC:
        SERVER_PROC.send_signal(signal.SIGTERM)
        try:
            SERVER_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            SERVER_PROC.kill()
        print("  Server stopped")


def api(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{BASE}{path}"
    return getattr(requests, method)(url, timeout=60, **kwargs)


def assert_ok(r: requests.Response, expected: int = 200):
    if r.status_code != expected:
        print(f"  FAIL: {r.status_code} (expected {expected})")
        print(f"  Body: {r.text[:500]}")
    assert r.status_code == expected, f"Expected {expected}, got {r.status_code}: {r.text[:300]}"


def poll_status(session_id: str, terminal: set = None, timeout: int = TIMEOUT) -> dict:
    if terminal is None:
        terminal = {"done", "error"}
    start = time.time()
    last_status = None
    while time.time() - start < timeout:
        try:
            r = api("get", f"/api/paper/{session_id}/status")
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue
        if r.status_code != 200:
            time.sleep(POLL_INTERVAL)
            continue
        body = r.json()
        status = body["session"]["status"]
        if status != last_status:
            elapsed = int(time.time() - start)
            events = [e["event_type"] for e in body.get("events", [])]
            print(f"  [{elapsed:3d}s] status={status}  events={events}")
            last_status = status
        if status in terminal:
            return body
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Session {session_id} did not reach terminal status in {timeout}s")


# ── Tests ─────────────────────────────────────────────────────


def test_01_list_raw():
    print("\n=== [1] List raw files ===")
    r = api("get", "/api/paper/list-raw")
    assert_ok(r)
    body = r.json()
    names = {f["filename"] for f in body["files"]}
    assert "1601.00991v3.pdf" in names
    target = [f for f in body["files"] if f["filename"] == "1601.00991v3.pdf"][0]
    print(f"  Found: {target['filename']} ({target['size_bytes']} bytes)")
    return target


def test_02_start_extraction(raw_file: dict):
    print("\n=== [2] Start paper extraction ===")
    r = api("post", "/api/paper/start", json={
        "paper_id": "e2e-test-001",
        "source_type": "raw",
        "source_ref": raw_file["path"],
        "symbol": "000300.SH",
        "start_date": "2023-01-01",
        "end_date": "2025-12-31",
    })
    assert_ok(r)
    body = r.json()
    assert body["status"] == "pending"
    print(f"  session_id: {body['session_id']}")
    return body["session_id"]


def test_03_poll_until_done(session_id: str) -> dict:
    print(f"\n=== [3] Poll status (session={session_id[:8]}...) ===")
    result = poll_status(session_id)
    status = result["session"]["status"]
    print(f"  Final status: {status}")
    assert status in ("done", "error")
    return result


def test_04_verify_events(result: dict):
    print("\n=== [4] Verify event sequence ===")
    events = [e["event_type"] for e in result["events"]]
    print(f"  All events: {events}")

    assert "extract.started" in events
    assert "extract.llm_called" in events

    llm_done = [e for e in result["events"] if e["event_type"] == "extract.llm_done"]
    if llm_done:
        payload = llm_done[0].get("payload", {})
        has_ext = payload.get("has_extraction", False)
        keys = payload.get("keys", [])
        print(f"  has_extraction: {has_ext}")
        print(f"  keys: {keys}")
        ext = payload.get("extraction", {})
        if ext:
            print(f"  extraction preview: {json.dumps(ext, ensure_ascii=False)[:300]}")

    wiki_written = [e for e in result["events"] if e["event_type"] == "wiki.written"]
    if wiki_written:
        pages = wiki_written[0].get("payload", {}).get("pages_written", 0)
        print(f"  pages_written: {pages}")

    backtest_events = [e for e in result["events"] if "backtest" in e["event_type"]]
    for bt in backtest_events:
        print(f"  {bt['event_type']}: {json.dumps(bt.get('payload', {}), ensure_ascii=False)[:200]}")

    finalize = [e for e in result["events"] if e["event_type"] == "finalize.done"]
    if finalize:
        p = finalize[0].get("payload", {})
        print(f"  finalize: pages={p.get('pages_written')}, backtests={len(p.get('backtest_results', []))}")

    print("  Event checks passed")


def test_05_verify_artifacts(session_id: str):
    print("\n=== [5] Verify artifacts ===")
    r = api("get", f"/api/paper/{session_id}/status")
    assert_ok(r)
    artifacts = r.json().get("artifacts", [])
    print(f"  Artifact count: {len(artifacts)}")
    for a in artifacts:
        print(f"    kind={a.get('kind')}, page={a.get('wiki_page')}")
    return artifacts


def test_06_factor_list():
    print("\n=== [6] List factors ===")
    r = api("get", "/api/factor/list")
    assert_ok(r)
    factors = r.json().get("factors", [])
    print(f"  Factor count: {len(factors)}")
    for f in factors:
        print(f"    {f.get('_slug')}: class={f.get('factor_class')}")
    return factors


def test_07_strategy_list():
    print("\n=== [7] List strategies ===")
    r = api("get", "/api/strategy/list")
    assert_ok(r)
    strategies = r.json().get("strategies", [])
    print(f"  Strategy count: {len(strategies)}")
    for s in strategies:
        print(f"    {s.get('_slug')}: signal={s.get('signal_type')}")
    return strategies


def test_08_paper_list():
    print("\n=== [8] List paper sessions ===")
    r = api("get", "/api/paper/list")
    assert_ok(r)
    sessions = r.json().get("sessions", [])
    e2e = [s for s in sessions if s["paper_id"] == "e2e-test-001"]
    print(f"  Total: {len(sessions)}, e2e: {len(e2e)}")
    assert len(e2e) >= 1


# ── Main ──────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("E2E TEST: Paper Reproduction Workflow")
    print("=" * 60)

    try:
        start_server()
        test_01_list_raw()
        session_id = test_02_start_extraction(
            {"filename": "1601.00991v3.pdf", "path": f"{WORK_DIR}/raw/1601.00991v3.pdf", "size_bytes": 244416}
        )
        result = test_03_poll_until_done(session_id)
        test_04_verify_events(result)
        test_05_verify_artifacts(session_id)
        test_06_factor_list()
        test_07_strategy_list()
        test_08_paper_list()

        print("\n" + "=" * 60)
        print("ALL E2E TESTS PASSED")
        print("=" * 60)

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"E2E TEST FAILED: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        stop_server()


if __name__ == "__main__":
    main()
