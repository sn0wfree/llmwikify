#!/usr/bin/env python3
"""v0.36 AgentChat Hardening — Real-LLM Smoke Test.

Runs 8 scenarios against a live LLM provider to verify the v0.36 hardening
changes work end-to-end (not just in mock tests).

Each scenario:
  1. Sets up a session
  2. Sends a message exercising a specific v0.36 capability
  3. Asserts on the SSE stream events
  4. Cleans up

Usage:
    export LLM_API_KEY=sk-...
    python scripts/smoke_v036.py

    # Or with explicit model:
    export LLM_MODEL=gpt-4o-mini
    python scripts/smoke_v036.py

    # Require key (no graceful skip):
    SMOKE_REQUIRE_KEY=1 python scripts/smoke_v036.py

    # Run subset:
    python scripts/smoke_v036.py --only s1,s3,s8

Exit codes:
    0  — all scenarios passed (or skipped because no key)
    1  — at least one scenario failed
    2  — setup error (no key + SMOKE_REQUIRE_KEY)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

# Project root on sys.path so we can import llmwikify.*
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@dataclass
class SmokeResult:
    """Result of one scenario."""

    scenario_id: str
    name: str
    passed: bool
    duration_s: float
    details: str = ""
    skipped: bool = False


@dataclass
class SmokeContext:
    """Shared context for all scenarios."""

    base_url: str = "http://localhost:8765"
    data_dir: Path = field(default_factory=lambda: Path("/tmp/smoke_v036"))
    timeout_s: float = 60.0
    llm_provider: str = ""
    llm_model: str = ""


@dataclass
class ChatEvent:
    """Parsed SSE event."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)


# ─── HTTP / SSE helpers ──────────────────────────────────────────────────────


async def post_chat(
    ctx: SmokeContext,
    message: str,
    session_id: str,
    wiki_id: str = "default",
) -> AsyncIterator[ChatEvent]:
    """POST /api/agent/sessions/{id}/chat and yield SSE events.

    This calls the live AgentChat HTTP endpoint, which is the production path.
    Requires the server to be running at ctx.base_url.
    """
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    url = f"{ctx.base_url}/api/agent/sessions/{session_id}/chat"
    body = json.dumps({"message": message, "wiki_id": wiki_id}).encode()

    # NOTE: this is a sync urlopen in an async function. Real implementation
    # should use aiohttp/httpx. Stubbed here to keep script zero-dep.
    raise NotImplementedError(
        "Real HTTP client not yet wired. Use aiohttp or run server in-process."
    )


# ─── Scenario stubs ──────────────────────────────────────────────────────────


async def s1_single_turn(ctx: SmokeContext) -> SmokeResult:
    """S1: Single-turn chat produces session_created + message_delta + done."""
    # 1. Create session
    # 2. Send "Say hello in 5 words"
    # 3. Assert: events contain session_created, at least 1 message_delta, done
    # 4. Assert: no error/timeout/confirmation_required
    return SmokeResult("s1", "Single-turn chat", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s2_tool_call(ctx: SmokeContext) -> SmokeResult:
    """S2: Tool call (wiki_read_page) verifies §1.1 tool result feedback."""
    # 1. Create session with a wiki that has at least one page
    # 2. Send "Read the home page and summarize it"
    # 3. Assert: tool_call_start + tool_call_end for wiki_read_page
    # 4. Assert: message_delta after tool_call_end (feedback loop)
    return SmokeResult("s2", "Tool call", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s3_multi_step(ctx: SmokeContext) -> SmokeResult:
    """S3: Multi-step tool loop (1-4 iterations)."""
    # 1. Send a prompt that requires 2+ tool calls
    # 2. Assert: ≥2 tool_call_end events
    # 3. Assert: ≤4 tool_call_end events (cap at DEFAULT_MAX_CHAT_ITERATIONS)
    return SmokeResult("s3", "Multi-step tool loop", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s4_confirmation(ctx: SmokeContext) -> SmokeResult:
    """S4: Confirmation-required tool pauses stream."""
    # 1. Trigger a confirmation-required tool (e.g. write/edit page)
    # 2. Assert: confirmation_required event appears
    # 3. Assert: stream pauses (no message_delta after)
    # 4. Optionally: send approve_and_continue
    return SmokeResult("s4", "Confirmation interrupt", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s5_abort_reconnect(ctx: SmokeContext) -> SmokeResult:
    """S5: Abort + SSE reconnect (1s/2s/4s backoff)."""
    # 1. Start a long-running stream
    # 2. Abort after first chunk
    # 3. Assert: no further events after AbortError
    # 4. Separate: simulate disconnect, verify reconnect attempts with backoff
    return SmokeResult("s5", "Abort + SSE reconnect", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s6_regenerate(ctx: SmokeContext) -> SmokeResult:
    """S6: Any-message regenerate (§5.3)."""
    # 1. Run a chat turn to completion
    # 2. Call POST /api/agent/sessions/{id}/regenerate with the assistant message_id
    # 3. Assert: new SSE stream produces a different response
    # 4. Assert: message after target message is gone from DB
    return SmokeResult("s6", "Any-message regenerate", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s7_memory_retrieval(ctx: SmokeContext) -> SmokeResult:
    """S7: MemoryManager retrieval (top-3 history injection)."""
    # 1. Have a conversation history with several messages
    # 2. Send a message that references earlier content
    # 3. Assert: system prompt contains relevant history snippet
    #    (verify via logs or by checking context_entries table)
    return SmokeResult("s7", "MemoryManager retrieval", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


async def s8_rate_limit(ctx: SmokeContext) -> SmokeResult:
    """S8: Rate limit (60 req/min/IP, 429 after)."""
    # 1. Send 60 requests rapidly from same IP
    # 2. 61st request returns 429 with Retry-After
    # 3. Cleanup
    return SmokeResult("s8", "Rate limit", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v036.md for spec")


# Registry of scenarios
SMOKE_SCENARIOS: list[Callable[[SmokeContext], Awaitable[SmokeResult]]] = [
    s1_single_turn,
    s2_tool_call,
    s3_multi_step,
    s4_confirmation,
    s5_abort_reconnect,
    s6_regenerate,
    s7_memory_retrieval,
    s8_rate_limit,
]


# ─── Runner ─────────────────────────────────────────────────────────────────


def check_api_key() -> bool:
    """Return True if an LLM API key is available."""
    return bool(
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


async def run_scenarios(
    scenarios: list[Callable[[SmokeContext], Awaitable[SmokeResult]]],
    ctx: SmokeContext,
) -> list[SmokeResult]:
    """Run all scenarios sequentially and collect results."""
    results = []
    for fn in scenarios:
        sid = fn.__name__.split("_")[0]
        name = fn.__doc__.splitlines()[0] if fn.__doc__ else fn.__name__
        t0 = time.time()
        try:
            result = await fn(ctx)
        except Exception as exc:
            result = SmokeResult(
                scenario_id=sid,
                name=name,
                passed=False,
                duration_s=time.time() - t0,
                details=f"EXCEPTION: {exc}\n{traceback.format_exc()}",
            )
        result.duration_s = time.time() - t0
        results.append(result)
        marker = "PASS" if result.passed else ("SKIP" if result.skipped else "FAIL")
        print(f"  [{marker}] {result.scenario_id}: {result.name} "
              f"({result.duration_s:.1f}s) — {result.details}")
    return results


def print_summary(results: list[SmokeResult]) -> None:
    """Print final summary table."""
    print()
    print("─" * 78)
    print("v0.36 Smoke Summary")
    print("─" * 78)
    print(f"{'ID':<6}{'Status':<8}{'Duration':<12}{'Details'}")
    print("─" * 78)
    for r in results:
        status = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
        print(f"{r.scenario_id:<6}{status:<8}{r.duration_s:>8.1f}s     {r.details[:50]}")
    print("─" * 78)
    n_pass = sum(1 for r in results if r.passed)
    n_fail = sum(1 for r in results if not r.passed and not r.skipped)
    n_skip = sum(1 for r in results if r.skipped)
    print(f"Total: {len(results)} | Pass: {n_pass} | Fail: {n_fail} | Skip: {n_skip}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated scenario IDs to run (e.g. s1,s3,s8)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8765",
        help="AgentChat server base URL (default: http://localhost:8765)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-scenario timeout in seconds (default: 60)",
    )
    args = parser.parse_args()

    # Check API key
    require_key = os.environ.get("SMOKE_REQUIRE_KEY") == "1"
    if not check_api_key():
        msg = "No LLM_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY found"
        if require_key:
            print(f"ERROR: {msg}. Set one and retry.", file=sys.stderr)
            return 2
        print(f"WARNING: {msg}. Smoke scenarios will report as not-implemented.")
        print("Set SMOKE_REQUIRE_KEY=1 to require a key.")
        # We still run, scenarios report 'NOT YET IMPLEMENTED' as a clear signal.

    # Filter scenarios
    scenarios = SMOKE_SCENARIOS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        scenarios = [
            fn for fn in SMOKE_SCENARIOS
            if fn.__name__.split("_")[0] in wanted
        ]
        if not scenarios:
            print(f"ERROR: no scenarios match --only={args.only}", file=sys.stderr)
            return 2

    ctx = SmokeContext(
        base_url=args.base_url,
        timeout_s=args.timeout,
        llm_provider=os.environ.get("LLM_PROVIDER", "openai"),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    )
    print(f"v0.36 AgentChat Hardening — Real-LLM Smoke")
    print(f"Base URL: {ctx.base_url}")
    print(f"Provider: {ctx.llm_provider} | Model: {ctx.llm_model}")
    print(f"Scenarios: {len(scenarios)}")
    print()

    results = asyncio.run(run_scenarios(scenarios, ctx))
    print_summary(results)

    n_fail = sum(1 for r in results if not r.passed and not r.skipped)
    return 1 if n_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())