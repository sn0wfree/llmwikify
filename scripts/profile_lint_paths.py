#!/usr/bin/env python3
"""Profile lint / knowledge_gaps hot paths (segmented timing).

Usage:
  python scripts/profile_lint_paths.py --wiki /path/to/CKbase
  python scripts/profile_lint_paths.py --wiki ... --rules all
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", type=Path, required=True)
    ap.add_argument("--skip-rules", action="store_true", help="only inventory/load/orphan")
    args = ap.parse_args()

    from llmwikify.kernel.wiki.wiki import Wiki

    wiki = Wiki(args.wiki)
    t0 = time.perf_counter()
    pages = wiki._wiki_pages()
    t_list = time.perf_counter() - t0
    print(f"1 _wiki_pages (rglob): {t_list:.3f}s  n={len(pages)}")

    # display names
    t0 = time.perf_counter()
    names = [wiki._page_display_name(p) for p in pages]
    t_names = time.perf_counter() - t0
    print(f"2 _page_display_name xN: {t_names:.3f}s")

    # full read all pages (what CrossPageRule does)
    t0 = time.perf_counter()
    contents = {}
    total_bytes = 0
    for p in pages:
        try:
            c = p.read_text()
        except Exception:
            c = p.read_text(encoding="utf-8", errors="replace")
        contents[wiki._page_display_name(p)] = c
        total_bytes += len(c)
    t_read = time.perf_counter() - t0
    print(f"3 read_text all pages: {t_read:.3f}s  bytes={total_bytes}")

    # second full read (simulate 2nd CrossPageRule)
    t0 = time.perf_counter()
    for p in pages:
        _ = p.read_text(encoding="utf-8", errors="replace")
    t_read2 = time.perf_counter() - t0
    print(f"4 read_text all again: {t_read2:.3f}s")

    # regex scan all contents (wikilinks) — common in rules
    import re

    t0 = time.perf_counter()
    nlinks = 0
    for name, c in contents.items():
        nlinks += len(re.findall(r"\[\[(.*?)\]\]", c))
    t_re = time.perf_counter() - t0
    print(f"5 re.findall wikilinks: {t_re:.3f}s  links={nlinks}")

    # orphan concepts (SQL)
    t0 = time.perf_counter()
    try:
        orphans = wiki.get_relation_engine().find_orphan_concepts()
    except Exception as e:
        orphans = [f"ERR:{e}"]
    t_orph = time.perf_counter() - t0
    print(f"6 find_orphan_concepts: {t_orph:.3f}s  n={len(orphans)}")

    # sources dir walk + read (knowledge_gaps isolated_source)
    sources = wiki.wiki_dir / "sources"
    t0 = time.perf_counter()
    nsrc = 0
    if sources.exists():
        for sp in sources.rglob("*.md"):
            nsrc += 1
            try:
                _ = sp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    t_src = time.perf_counter() - t0
    print(f"7 sources rglob+read: {t_src:.3f}s  n={nsrc}")

    if args.skip_rules:
        print(f"\nSUMMARY list={t_list:.2f} read={t_read:.2f} total~{t_list+t_read:.2f}s")
        return

    # each lint rule
    print("\n8 per-rule timing:")
    engine = wiki._analyzer._lint_engine
    t_all0 = time.perf_counter()
    for name in engine.rule_names:
        t0 = time.perf_counter()
        try:
            issues = engine.run_rule(name)
            n = len(issues)
        except Exception as e:
            n = f"ERR:{e}"
        el = time.perf_counter() - t0
        print(f"   {name:22s} {el:7.2f}s  issues={n}")
    t_all = time.perf_counter() - t_all0
    print(f"   {'ALL run_all':22s} {t_all:7.2f}s")

    t0 = time.perf_counter()
    res = wiki.lint(mode="check", limit=5)
    t_lint = time.perf_counter() - t0
    print(f"9 wiki.lint(check,5): {t_lint:.2f}s  keys={list(res)[:8]}")


if __name__ == "__main__":
    main()
