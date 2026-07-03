#!/usr/bin/env python3
"""02_chat_sse.py - exercise the SSE chat endpoint via httpx.

This is the third script in the 00->01->02->03 chain. It starts a
local ``llmwikify serve --web`` subprocess, waits for ``/api/health``,
then POSTs a single message to ``/api/agent/chat`` and parses the
SSE event stream. The script verifies the **wire format** only; it
does not require a working LLM (an auth error or 401 will still
stream ``session_created`` / ``error`` / ``done`` events).

The 6 steps:

    1.  spawn ``llmwikify serve --web --port $SERVER_PORT``
    2.  poll ``GET /api/health`` until 200 (max 30s)
    3.  POST ``/api/agent/chat`` with session_id + message
    4.  parse SSE events (``event:`` / ``data:`` framing)
    5.  assert at least 1 event received, identify the event types
    6.  shutdown the server cleanly (SIGTERM, fallback SIGKILL)

The server is started in its own process group so it doesn't leak
across runs even if the test crashes.

Run::

    python examples/09_wiki_build_e2e/scripts/02_chat_sse.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from _lib import (  # noqa: E402
    AUTH_TOKEN,
    SERVER_PORT,
    WIKI_ROOT,
    cli,
    env_banner,
    record,
    section,
    summary,
)

HEALTH_TIMEOUT_S = 30.0
SSE_TIMEOUT_S = 25.0
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


def step_1_init_wiki_if_needed() -> None:
    section("step 1: ensure wiki is initialized")
    if (WIKI_ROOT / "wiki.md").exists():
        record("wiki.md present", True, "already initialized")
        return
    WIKI_ROOT.mkdir(parents=True, exist_ok=True)
    proc = cli("init", "--agent", "generic", check=False)
    if proc.returncode == 0:
        record("llmwikify init", True, "wiki skeleton created")
    else:
        record("llmwikify init", False, proc.stderr[:200] or proc.stdout[:200])


def step_2_start_server() -> subprocess.Popen | None:
    section("step 2: start llmwikify serve --web")
    log_path = THIS_DIR.parent / "expected" / "02-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("wb")

    # The generic runner image already has `llmwikify` on PATH. On a
    # developer machine it may or may not — fall back to `python -m`.
    use_console = os.environ.get("IN_DOCKER") == "1" and _which("llmwikify")
    if use_console:
        cmd = ["llmwikify", "serve", "--web", "--port", str(SERVER_PORT),
               "--auth-token", AUTH_TOKEN, "--name", "e2e-test"]
    else:
        cmd = [sys.executable, "-m", "llmwikify", "serve", "--web",
               "--port", str(SERVER_PORT), "--auth-token", AUTH_TOKEN,
               "--name", "e2e-test"]

    proc = subprocess.Popen(
        cmd,
        cwd=str(WIKI_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"  server PID: {proc.pid}")
    print(f"  log:        {log_path}")
    print(f"  url:        {BASE_URL}")
    return proc


def _which(cmd: str) -> str | None:
    """Return path or None (cheap reimpl to avoid importing shutil in
    this script — we already import httpx, no need for more)."""
    for p in os.environ.get("PATH", "").split(":"):
        candidate = Path(p) / cmd
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def step_3_wait_health() -> bool:
    section("step 3: poll /api/health")
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    last_err: str = ""
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                r = client.get(f"{BASE_URL}/api/health")
                if r.status_code == 200:
                    data = r.json()
                    print(f"  health: {r.status_code} status={data.get('status')}")
                    record("server healthy", True, f"v{data.get('version')}")
                    return True
                last_err = f"HTTP {r.status_code}"
            except (httpx.ConnectError, httpx.ReadError) as e:
                last_err = type(e).__name__
            time.sleep(0.5)
    record("server healthy", False, f"timeout after {HEALTH_TIMEOUT_S}s ({last_err})")
    return False


def step_4_post_chat() -> list[dict]:
    section("step 4: POST /api/agent/chat (SSE)")
    events: list[dict] = []
    try:
        with httpx.Client(timeout=SSE_TIMEOUT_S) as client:
            with client.stream(
                "POST",
                f"{BASE_URL}/api/agent/chat",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}",
                         "Content-Type": "application/json"},
                json={"session_id": "e2e-chat-02", "message": "hello"},
            ) as resp:
                if resp.status_code != 200:
                    record("POST /api/agent/chat", False,
                           f"HTTP {resp.status_code}")
                    return events
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    try:
                        ev = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    events.append(ev)
    except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
        record("SSE stream", False, f"{type(e).__name__}: {e}")
        return events
    print(f"  events received: {len(events)}")
    record("POST /api/agent/chat", True, f"{len(events)} events")
    return events


def step_5_classify_events(events: list[dict]) -> None:
    section("step 5: classify SSE events")
    if not events:
        record("SSE event types", False, "no events received")
        return
    types = [e.get("type", "?") for e in events]
    distinct = sorted(set(types))
    print(f"  types: {distinct}")
    expected = {"session_created", "done"}
    found = set(distinct) & expected
    if "session_created" in found:
        record("session_created event", True, "stream starts correctly")
    else:
        record("session_created event", False, f"types={distinct}")
    if "done" in found or "stream_end" in found or "error" in found:
        record("terminal event", True, f"end-of-stream: {found & {'done', 'stream_end', 'error'}}")
    else:
        record("terminal event", False, f"no done/stream_end/error in {distinct}")


def step_6_shutdown(proc: subprocess.Popen | None) -> None:
    section("step 6: shutdown server")
    if proc is None or proc.poll() is not None:
        record("server shutdown", True, "already exited")
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
        record("server shutdown", True, f"exit={proc.returncode}")
    except (ProcessLookupError, OSError) as e:
        record("server shutdown", True, f"already gone: {e}")


def main() -> int:
    print("=" * 60)
    print("  llmwikify chat SSE e2e (02_chat_sse.py)")
    print("=" * 60)
    env_banner()
    print()
    print(f"  Server URL: {BASE_URL}")
    print(f"  Auth token: {AUTH_TOKEN[:8]}...")
    print()

    step_1_init_wiki_if_needed()
    proc = step_2_start_server()
    if proc is None:
        return summary("02 chat-sse")
    try:
        healthy = step_3_wait_health()
        if healthy:
            events = step_4_post_chat()
            step_5_classify_events(events)
        else:
            # Server didn't come up - still try the SSE call so the
            # 4xx/5xx response is captured (verifies the endpoint exists).
            events = step_4_post_chat()
            step_5_classify_events(events)
    finally:
        step_6_shutdown(proc)
    return summary("02 chat-sse")


if __name__ == "__main__":
    sys.exit(main())
