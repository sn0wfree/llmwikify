"""
08 — 章节级双向引用 (section anchor tracking)

对应 docs/TUTORIAL.md §Part 3 — 9 个功能 playbook (08 section_anchor_tracking)

演示 [[page#section]] 风格的章节级 wikilink:
- 写 1 个有 markdown 标题的 target page
- 写 1 个 source page 用 [[target#section]] 引用
- 跑 build_index
- get_inbound_links(target) 应包含 source + section 信息
- get_outbound_links(source) 应包含 target + section 信息

索引存储 (kernel/storage/index.py):
  page_links 表有 section TEXT 字段, 每个 link 记录 (source, target, section)

剧本规模：~100 行，可独立 `python play.py` 跑 (无 LLM 依赖)。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from llmwikify import create_wiki


def step(n: int, msg: str) -> None:
    print(f"\n=== Step {n}: {msg} ===")


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="llmwikify_anchor_demo_"))
    try:
        wiki = create_wiki(work / "wiki")

        # ── Step 1: 写 target page (with section headers)
        step(1, "Write target page with multiple sections")
        target_content = """# Python Style Guide

## Overview
Python emphasizes code readability. Use 4-space indentation.

## Naming
Use `snake_case` for functions and variables. Use `PascalCase` for classes.

## Imports
Group imports: standard library, third-party, local. Separate with blank lines.
"""
        wiki.write_page("python-style", target_content)
        print("   Wrote: python-style.md (3 sections)")

        # ── Step 2: 写 source page 用 [[target#section]]
        step(2, "Write source page with [[target#section]] anchors")
        source_content = """# My Coding Notes

## Daily Reminders
Follow the naming convention from [[python-style#Naming]] when writing functions.
For imports, see [[python-style#Imports]].

## Quick Reference
- Use 4-space indentation ([[python-style#Overview]])
- Prefer composition over inheritance
"""
        wiki.write_page("coding-notes", source_content)
        print("   Wrote: coding-notes.md (3 anchored links to python-style)")

        # ── Step 3: 写另一个 source page with [[target#section|display]]
        step(3, "Write another source with display-text [[target#section|disp]]")
        source2_content = """# Team Wiki

## Style Guide Summary
See [[python-style#Naming|the naming section]] for variable conventions.
Read [[python-style#Imports]] before writing any imports.
"""
        wiki.write_page("team-wiki", source2_content)
        print("   Wrote: team-wiki.md (1 anchored link with display text)")

        # ── Step 4: build_index (没有显式调用, 但 write_page 会更新)
        step(4, "Verify wikilinks parsed (index is auto-updated by write_page)")
        # ── Step 5: get_inbound_links for python-style
        step(5, "get_inbound_links('python-style') — should show all 5 anchored refs")
        inbound = wiki.get_inbound_links("python-style")
        for link in inbound:
            section = link.get("section", "")
            display = link.get("display", "")
            print(f"   from {link['source']} section={section!r} display={display!r}")

        # ── Step 6: get_outbound_links for coding-notes
        step(6, "get_outbound_links('coding-notes') — should show 3 python-style anchors")
        outbound = wiki.get_outbound_links("coding-notes")
        for link in outbound:
            section = link.get("section", "")
            target = link.get("target", "")
            print(f"   → {target} section={section!r}")

        # ── Step 7: get_outbound_links for team-wiki (display text)
        step(7, "get_outbound_links('team-wiki') — display text preserved")
        outbound2 = wiki.get_outbound_links("team-wiki")
        for link in outbound2:
            print(f"   → {link['target']} section={link.get('section')!r} display={link.get('display')!r}")

        # ── Step 8: include_context (拉取 link 周围 80 字符)
        step(8, "get_inbound_links(include_context=True) — show 80-char context")
        for link in wiki.get_inbound_links("python-style", include_context=True):
            ctx = link.get("context", "")
            print(f"\n   {link['source']} section={link.get('section')!r}:")
            print(f"      ...{ctx[:100]}...")

        # ── Step 9: 反向 — get_inbound for the section
        step(9, "Confirm section-level tracking via DB")
        # The page_links table has source_page, target_page, section columns
        # We can query directly
        if hasattr(wiki.index, "conn"):
            cursor = wiki.index.conn.execute(
                "SELECT source_page, section FROM page_links WHERE target_page = ? ORDER BY source_page, section",
                ("python-style",),
            )
            print("   DB query: page_links WHERE target='python-style':")
            for row in cursor.fetchall():
                print(f"      {row['source_page']} → section={row['section']!r}")

        # ── Step 10: fix-wikilinks (renaming preserves anchors)
        step(10, "fix-wikilinks: anchor preserved during rename")
        # Create a wiki with a broken target
        wiki2_path = work / "wiki2"
        wiki2 = create_wiki(wiki2_path)
        wiki2.write_page("old-name", "# Old Name\n\n## Section A\ncontent\n")
        wiki2.write_page(
            "source-page",
            "# Source\n\nLinks to [[old-name#Section A]]\n",
        )
        # Rename via index API (if available) or directly
        old_path = wiki2_path / "wiki" / "old-name.md"
        new_path = wiki2_path / "wiki" / "new-name.md"
        if old_path.exists():
            old_path.rename(new_path)
            # Re-write to trigger index update
            wiki2.write_page("new-name", "# New Name\n\n## Section A\ncontent\n")
            result = wiki2.fix_wikilinks(dry_run=True)
            print(f"   fix-wikilinks dry_run: {result.get('stats', {})}")

        # ── Step 11: summary
        step(11, "Summary — section-level tracking")
        print("   [[page#section]]      — anchored link (no display text)")
        print("   [[page#section|disp]]  — anchored + display text")
        print("   inbound links include 'section' field")
        print("   fix-wikilinks preserves anchor during rename")

        print(f"\nDone. Wiki at: {work / 'wiki'}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
