#!/usr/bin/env python3
"""v0.37 Triple ReAct Loop — Real-LLM Smoke Test.

Runs 6 scenarios against a live LLM provider to verify the v0.37 ReActEngine
unification works end-to-end.

Each scenario exercises a specific ReActEngine capability:
  S1: ChatService → ChatReActBridge path
  S2: ResearchEngine → ReActEngine path (6-step → 13-step mapping)
  S3: ReActEngine timeout (configured to 5s, not the production 300s)
  S4: ReActEngine cancel via AbortSignal
  S5: Text-mode [TOOL_CALL] parsing for non-tool-aware LLMs
  S6: Thinking snapshot persisted to context

Usage:
    export LLM_API_KEY=sk-...
    python scripts/smoke_v037.py

Exit codes: same as smoke_v036.py (0=pass, 1=fail, 2=setup error)
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

# Project root on sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@dataclass
class SmokeResult:
    scenario_id: str
    name: str
    passed: bool
    duration_s: float
    details: str = ""
    skipped: bool = False


@dataclass
class SmokeContext:
    base_url: str = "http://localhost:8765"
    data_dir: Path = field(default_factory=lambda: Path("/tmp/smoke_v037"))
    timeout_s: float = 60.0
    short_timeout_s: float = 5.0  # for S3 timeout test
    llm_provider: str = ""
    llm_model: str = ""


# ─── Scenario stubs ──────────────────────────────────────────────────────────


async def s1_chat_react_bridge(ctx: SmokeContext) -> SmokeResult:
    """S1: ChatService routes through ChatReActBridge by default.

    Verifies: the new path is active, tool calls work, [TOOL_CALL] parsing
    kicks in for text-mode LLMs.
    """
    return SmokeResult("s1", "ChatService → ChatReActBridge", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


async def s2_research_react(ctx: SmokeContext) -> SmokeResult:
    """S2: ResearchEngine uses ReActEngine.

    Verifies: 6-step research flow maps to 13 generic round steps,
    EVENT_PHASE events emitted for domain semantics.
    """
    return SmokeResult("s2", "ResearchEngine → ReActEngine", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


async def s3_timeout(ctx: SmokeContext) -> SmokeResult:
    """S3: ReActEngine emits timeout event after configured timeout.

    Uses a short 5s timeout (not production 300s) to keep test fast.
    Verifies: timeout event fires, partial state cleaned up via on_timeout hook.
    """
    return SmokeResult("s3", "ReActEngine timeout", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


async def s4_cancel(ctx: SmokeContext) -> SmokeResult:
    """S4: ReActEngine responds to AbortSignal.

    Verifies: AbortSignal propagates to all hooks, on_cancel fires,
    pending tool calls are best-effort cancelled.
    """
    return SmokeResult("s4", "ReActEngine cancel", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


async def s5_text_mode(ctx: SmokeContext) -> SmokeResult:
    """S5: Text-mode [TOOL_CALL]...[/TOOL_CALL] parsing.

    Verifies: an LLM without native tool_calls support (e.g. text-only model)
    can still invoke tools via the text-mode parser.
    """
    return SmokeResult("s5", "Text-mode [TOOL_CALL] parsing", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


async def s6_thinking_snapshot(ctx: SmokeContext) -> SmokeResult:
    """S6: LLM Thought injected into SkillContext._thinking.

    Verifies: after a ReAct round, the thinking snapshot is accessible
    to downstream tools/hooks.
    """
    return SmokeResult("s6", "Thinking snapshot", False, 0.0,
                       details="NOT YET IMPLEMENTED — see smoke_v037.md for spec")


SMOKE_SCENARIOS: list[Callable[[SmokeContext], Awaitable[SmokeResult]]] = [
    s1_chat_react_bridge,
    s2_research_react,
    s3_timeout,
    s4_cancel,
    s5_text_mode,
    s6_thinking_snapshot,
]


# ─── Runner ─────────────────────────────────────────────────────────────────


def check_api_key() -> bool:
    return bool(
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )


async def run_scenarios(
    scenarios: list[Callable[[SmokeContext], Awaitable[SmokeResult]]],
    ctx: SmokeContext,
) -> list[SmokeResult]:
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
    print()
    print("─" * 78)
    print("v0.37 Smoke Summary")
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
        help="Comma-separated scenario IDs to run (e.g. s1,s3,s6)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8765",
        help="AgentChat server base URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-scenario timeout in seconds (default: 60)",
    )
    args = parser.parse_args()

    require_key = os.environ.get("SMOKE_REQUIRE_KEY") == "1"
    if not check_api_key():
        msg = "No LLM_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY found"
        if require_key:
            print(f"ERROR: {msg}. Set one and retry.", file=sys.stderr)
            return 2
        print(f"WARNING: {msg}. Smoke scenarios will report as not-implemented.")

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
    print(f"v0.37 Triple ReAct Loop — Real-LLM Smoke")
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