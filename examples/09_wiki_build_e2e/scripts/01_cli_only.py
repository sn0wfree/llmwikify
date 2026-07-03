#!/usr/bin/env python3
"""01_cli_only.py - exercise the 10 core wiki CLI commands end-to-end.

This is the second script in the 00->01->02->03 chain. It builds a
small wiki from scratch using **only the llmwikify CLI** (no LLM calls,
no agent, no server) and asserts that every step produces the expected
side effects.

The 10 steps:

    1.  llmwikify init
    2.  verify the wiki skeleton (raw/ wiki/ wiki.md .llmwikify.db)
    3.  copy 2 fixtures into raw/
    4.  llmwikify ingest --dry-run  (preview only)
    5.  llmwikify ingest            (extract + emit JSON)
    6.  llmwikify write_page         (from --file)
    7.  llmwikify write_page         (from --content)
    8.  llmwikify search             (FTS5)
    9.  llmwikify build-index  + references
   10.  llmwikify lint         + status

Run::

    python examples/09_wiki_build_e2e/scripts/01_cli_only.py
"""

from __future__ import annotations

import json
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
    summary,
)

FIXTURES = THIS_DIR.parent / "fixtures"
EXPECTED_TOP_LEVEL = ["raw", "wiki", "wiki.md", ".llmwikify.db"]


def step_1_init() -> None:
    section("step 1: init")
    WIKI_ROOT.mkdir(parents=True, exist_ok=True)
    proc = cli("init", check=False)
    if proc.returncode != 0:
        record("llmwikify init", False, proc.stderr[:200] or proc.stdout[:200])
        return
    out = proc.stdout + proc.stderr
    if "Wiki initialized" in out or "already initialized" in out:
        record("llmwikify init", True, "wiki skeleton created")
    else:
        record("llmwikify init", False, "unexpected output: " + out[:120])


def step_2_verify_skeleton() -> None:
    section("step 2: verify wiki skeleton")
    missing = [p for p in EXPECTED_TOP_LEVEL if not (WIKI_ROOT / p).exists()]
    if missing:
        record("wiki skeleton", False, f"missing: {missing}")
    else:
        record("wiki skeleton", True, ", ".join(EXPECTED_TOP_LEVEL))


def step_3_copy_fixtures() -> None:
    section("step 3: copy fixtures into raw/")
    raw_dir = WIKI_ROOT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in sorted(FIXTURES.glob("*.md")):
        shutil.copy(f, raw_dir / f.name)
        copied.append(f.name)
    if len(copied) >= 2:
        record("copy fixtures", True, f"{len(copied)} files")
    else:
        record("copy fixtures", False, f"only {len(copied)} found")


def step_4_ingest_dry_run() -> None:
    section("step 4: ingest --dry-run")
    sample = WIKI_ROOT / "raw" / "sample-1.md"
    if not sample.exists():
        record("ingest --dry-run", False, "sample-1.md not in raw/")
        return
    proc = cli("ingest", str(sample), "--dry-run", check=False)
    if proc.returncode == 0 and "No pages created" in (proc.stdout + proc.stderr):
        record("ingest --dry-run", True, "preview only, no pages created")
    else:
        record("ingest --dry-run", False,
               f"exit={proc.returncode}: " + (proc.stderr[:120] or proc.stdout[:120]))


def step_5_ingest_extract() -> None:
    section("step 5: ingest (extract + JSON)")
    sample = WIKI_ROOT / "raw" / "sample-2.md"
    if not sample.exists():
        record("ingest sample-2", False, "sample-2.md not in raw/")
        return
    proc = cli("ingest", str(sample), check=False)
    if proc.returncode != 0:
        record("ingest sample-2", False, f"exit={proc.returncode}")
        return
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        record("ingest sample-2", False, f"json parse: {e}")
        return
    title = data.get("title", "?")
    if title and "content_length" in data:
        record("ingest sample-2", True,
               f"title='{title}' content_length={data['content_length']}")
    else:
        record("ingest sample-2", False, "missing title or content_length")


def step_6_write_page_from_file() -> None:
    section("step 6: write_page --file")
    sample = WIKI_ROOT / "raw" / "sample-1.md"
    page = "sources/sample-1"
    proc = cli("write_page", page, "--file", str(sample), check=False)
    if proc.returncode == 0 and ("Created page" in proc.stdout or "Updated page" in proc.stdout):
        record(f"write_page {page}", True, "page written")
    else:
        record(f"write_page {page}", False, f"exit={proc.returncode}: {proc.stdout[:120]}")


def step_7_write_page_from_content() -> None:
    section("step 7: write_page --content (with [[wikilink]])")
    page = "concepts/bidirectional-references"
    content = (
        "# Bidirectional References\n\n"
        "A wikilink test page. See [[sources/sample-1]] for context.\n"
    )
    proc = cli("write_page", page, "--content", content, check=False)
    if proc.returncode == 0 and "Created page" in proc.stdout:
        record(f"write_page {page}", True, "page with [[wikilink]] written")
    else:
        record(f"write_page {page}", False, f"exit={proc.returncode}: {proc.stdout[:120]}")


def step_8_search() -> None:
    section("step 8: search FTS5")
    proc = cli("search", "wiki", check=False)
    if proc.returncode == 0 and "Search results" in proc.stdout:
        numbered = sum(1 for line in proc.stdout.splitlines()
                       if line.strip() and line.strip()[0].isdigit() and "." in line[:4])
        record("search 'wiki'", True, f"{numbered} hit" + ("s" if numbered != 1 else ""))
    else:
        record("search 'wiki'", False, f"exit={proc.returncode}: {proc.stdout[:120]}")


def step_9_build_index_and_references() -> None:
    section("step 9: build-index + references")
    bi = cli("build-index", check=False)
    if bi.returncode != 0 or "Index Built" not in (bi.stdout + bi.stderr):
        record("build-index", False, f"exit={bi.returncode}: {bi.stdout[:120]}")
    else:
        record("build-index", True, "index rebuilt")
    refs = cli("references", "concepts/bidirectional-references", check=False)
    if refs.returncode == 0 and "References" in refs.stdout:
        record("references", True, "bidirectional links reported")
    else:
        record("references", False, f"exit={refs.returncode}: {refs.stdout[:120]}")


def step_10_lint_and_status() -> None:
    section("step 10: lint + status")
    lint = cli("lint", check=False)
    if lint.returncode == 0 and ("Wiki Lint" in lint.stdout or "broken_link" in lint.stdout
                                  or "issues" in lint.stdout.lower()):
        record("lint", True, "report returned")
    else:
        record("lint", False, f"exit={lint.returncode}: {lint.stdout[:200]}")
    status = cli("status", check=False)
    if status.returncode == 0 and "Wiki Status" in status.stdout:
        record("status", True, "wiki stats returned")
    else:
        record("status", False, f"exit={status.returncode}: {status.stdout[:120]}")


def main() -> int:
    print("=" * 60)
    print("  llmwikify CLI-only e2e (01_cli_only.py)")
    print("=" * 60)
    env_banner()
    print()
    print(f"  Wiki root: {WIKI_ROOT}")
    print(f"  Fixtures:  {FIXTURES}")
    print()

    step_1_init()
    step_2_verify_skeleton()
    step_3_copy_fixtures()
    step_4_ingest_dry_run()
    step_5_ingest_extract()
    step_6_write_page_from_file()
    step_7_write_page_from_content()
    step_8_search()
    step_9_build_index_and_references()
    step_10_lint_and_status()

    return summary("01 cli-only")


if __name__ == "__main__":
    sys.exit(main())
