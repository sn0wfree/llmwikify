#!/usr/bin/env python3
"""03_agent_real.py - exercise the agent path via opencode CLI.

This is the fourth script in the 00->01->02->03 chain. It verifies
the **agent** mode described in docs/USAGE_MODES.md - i.e. an
external agent (opencode, claude, codex) reading ``wiki.md`` /
``SKILL.md`` and writing wiki pages via MCP / ``llmwikify write_page``.

The script is intentionally conservative: if ``opencode`` is not
installed in the container, it logs a ``[SKIP]`` and exits 0 so
the chain does not break. CI runners typically do not have an
agent CLI pre-installed, so this script is a **manual / local** test
in the README.

The 4 steps:

    1.  check whether ``opencode`` (or ``claude`` / ``codex``) is on PATH
    2.  if no agent is found, [SKIP] and return 0
    3.  init a wiki with ``init --agent opencode`` and verify the
        generated ``opencode.json`` / ``.agents/skills/llmwikify/SKILL.md``
    4.  (smoke test) invoke ``opencode --help`` to confirm the
        binary actually runs

Run::

    python examples/09_wiki_build_e2e/scripts/03_agent_real.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from _lib import (  # noqa: E402
    WIKI_ROOT,
    cli,
    env_banner,
    record,
    section,
    skip,
    summary,
)

AGENTS = ("opencode", "claude", "codex")


def find_agent() -> str | None:
    """Return the first available agent CLI on PATH, or None."""
    for name in AGENTS:
        path = shutil.which(name)
        if path:
            return name
    return None


def step_1_check_agents() -> str | None:
    section("step 1: look for an agent CLI on PATH")
    for name in AGENTS:
        path = shutil.which(name)
        if path:
            print(f"  found: {name} ({path})")
    agent = find_agent()
    if agent:
        record("agent CLI present", True, agent)
    else:
        skip("agent CLI present",
             f"none of {', '.join(AGENTS)} on PATH; agent mode is a manual test")
    return agent


def step_2_init_with_agent(agent: str) -> None:
    section(f"step 2: llmwikify init --agent {agent}")
    proc = cli("init", "--agent", agent, check=False)
    if proc.returncode != 0:
        record(f"init --agent {agent}", False, proc.stderr[:200] or proc.stdout[:200])
        return
    record(f"init --agent {agent}", True, "wiki initialised with agent config")


def step_3_verify_agent_files(agent: str) -> None:
    section("step 3: verify agent-specific files were generated")
    expected = {
        "opencode": ["opencode.json", ".agents/skills/llmwikify/SKILL.md"],
        "claude":   [".mcp.json",      ".agents/skills/llmwikify/SKILL.md"],
        "codex":    [".opencode.json", ".agents/skills/llmwikify/SKILL.md"],
    }[agent]
    for rel in expected:
        path = WIKI_ROOT / rel
        if path.exists():
            record(f"{rel} generated", True, f"{path.stat().st_size} bytes")
        else:
            record(f"{rel} generated", False, "missing")


def step_4_smoke_test(agent: str) -> None:
    section(f"step 4: smoke-test {agent} --help")
    import subprocess
    try:
        proc = subprocess.run(
            [agent, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 or proc.returncode == 2:
            record(f"{agent} --help", True, f"exit={proc.returncode}")
        else:
            record(f"{agent} --help", False, f"exit={proc.returncode}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        record(f"{agent} --help", False, str(e))


def main() -> int:
    print("=" * 60)
    print("  llmwikify agent e2e (03_agent_real.py)")
    print("=" * 60)
    env_banner()
    print()
    print("  This script verifies the 'agent mode' (opencode / claude / codex).")
    print("  It is a manual/local test - CI typically skips it.")
    print()

    agent = step_1_check_agents()
    if agent is None:
        return summary("03 agent")
    step_2_init_with_agent(agent)
    step_3_verify_agent_files(agent)
    step_4_smoke_test(agent)
    return summary("03 agent")


if __name__ == "__main__":
    sys.exit(main())
