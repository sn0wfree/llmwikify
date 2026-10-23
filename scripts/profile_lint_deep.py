#!/usr/bin/env python3
"""Deep profile: missing_cross_ref + wiki.lint stages."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/src")  # editable in image; also works if installed
sys.path.insert(0, str(Path("/app").resolve()))


def main() -> None:
    from llmwikify.kernel.wiki.wiki import Wiki

    wiki = Wiki(Path("/app/wiki"))
    pages = wiki._wiki_pages()
    print(f"pages={len(pages)}")

    # --- missing_cross_ref internals ---
    t0 = time.perf_counter()
    contents = {}
    for p in pages:
        name = wiki._page_display_name(p)
        if name.startswith("Query:"):
            continue
        try:
            contents[name] = p.read_text()
        except Exception:
            contents[name] = p.read_text(encoding="utf-8", errors="replace")
    print(f"load contents: {time.perf_counter()-t0:.2f}s n={len(contents)}")

    import re

    t0 = time.perf_counter()
    mentions: dict[str, int] = {}
    for name, c in contents.items():
        for m in re.findall(r"\b[A-Z][\w一-鿿]{2,}\b", c):
            mentions[m] = mentions.get(m, 0) + 1
    print(f"mention scan: {time.perf_counter()-t0:.2f}s terms={len(mentions)}")

    # read the actual rule source logic
    rule = wiki._analyzer._lint_engine._rules.get("missing_cross_ref")
    print("rule_class", type(rule).__name__)

    t0 = time.perf_counter()
    issues = wiki._analyzer._run_rule("missing_cross_ref")
    print(f"missing_cross_ref: {time.perf_counter()-t0:.2f}s issues={len(issues)}")

    # --- wiki.lint stages ---
    an = wiki._analyzer
    stages = [
        ("_run_all_rules", lambda: an._run_all_rules()),
        ("_detect_knowledge_gaps", lambda: an._detect_knowledge_gaps()),
        ("_scan_all_pages", lambda: an._scan_all_pages()),
        ("_generate_hints", lambda: an._generate_hints()),
    ]
    for label, fn in stages:
        t0 = time.perf_counter()
        try:
            r = fn()
            n = len(r) if hasattr(r, "__len__") else type(r).__name__
        except Exception as e:
            n = f"ERR {e}"
        print(f"stage {label}: {time.perf_counter()-t0:.2f}s -> {n}")

    t0 = time.perf_counter()
    out = an.lint(mode="check", limit=5)
    print(f"full lint: {time.perf_counter()-t0:.2f}s keys={list(out)[:10]}")


if __name__ == "__main__":
    main()
