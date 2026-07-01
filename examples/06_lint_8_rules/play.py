"""
06 — 主动触发 wiki lint 8 rules

对应 docs/TUTORIAL.md §Part 3 — 9 个功能 playbook (06 lint_8_rules)

构造示例数据触发 kernel/wiki/lint 下的多条 rule。

lint() 返回 dict 结构：
  {
    "issues": [...],              # orphan_page 等常规 issues (有 'type' 字段)
    "mode": "full"|"brief",
    "schema_source": "...",
    "hints": {
      "critical": [...],          # dated_claim 等 hints (同样有 'type' 字段)
      "informational": [...],
    },
    "investigations": {           # LLM-driven investigations (可选)
      "contradictions": [...],
      "data_gaps": [...],         # 含 'unsourced_claims' 等
      "outdated_pages": [...],    # 含 'potentially_outdated'
      "knowledge_gaps": [...],
      "redundancy_alerts": [...], # 含 'redundancy'
    },
    ...
  }

剧本规模：~120 行，可独立 `python play.py` 跑。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from llmwikify import create_wiki


def step(n: int, msg: str) -> None:
    print(f"\n=== Step {n}: {msg} ===")


def collect_types(result: dict) -> dict[str, list]:
    """Flatten all issue types from lint result into one mapping."""
    by_type: dict[str, list] = {}
    for issue in result.get("issues", []):
        t = issue.get("type", "unknown")
        by_type.setdefault(t, []).append(issue)
    for hint in result.get("hints", {}).get("critical", []):
        t = hint.get("type", "unknown")
        by_type.setdefault(t, []).append(hint)
    for hint in result.get("hints", {}).get("informational", []):
        t = hint.get("type", "unknown")
        by_type.setdefault(t, []).append(hint)
    inv = result.get("investigations", {})
    for category, items in inv.items():
        for it in items:
            t = it.get("type", category)
            by_type.setdefault(t, []).append(it)
    return by_type


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="llmwikify_lint_demo_"))
    try:
        wiki = create_wiki(work / "wiki")

        # ── Step 1: write 2 pages with high content overlap (redundancy trigger)
        step(1, "Write 2 pages with high content overlap (redundancy)")
        wiki.write_page(
            "machine-learning-basics",
            """# Machine Learning Basics

Machine learning is a subset of artificial intelligence. It focuses on
building systems that learn from data. Common algorithms include neural
networks, decision trees, and support vector machines.

The field has grown rapidly in recent years.

(raw/ml_history_2024.md)
""",
        )
        wiki.write_page(
            "ml-introduction",
            """# ML Introduction

Machine learning is a subset of artificial intelligence. It focuses on
building systems that learn from data. Common algorithms include neural
networks, decision trees, and support vector machines.

The field has grown rapidly in recent years.

(raw/ml_history_2024.md)
""",
        )

        # ── Step 2: page with old year (dated_claim + potentially_outdated)
        step(2, "Write page with old year ref (dated_claim + outdated)")
        wiki.write_page(
            "company-info-2018",
            """# Company History

This page describes the company's history from 2018. Founded in 2015,
the company went public in 2018 and expanded to Europe in 2019.

Key milestones:
- 2015: Founded
- 2018: IPO
- 2019: European expansion

(raw/old_report_2018.md)
""",
        )

        # ── Step 3: page mentions topic without wikilink (missing_cross_ref)
        step(3, "Write page that mentions 'neural networks' without wikilink")
        wiki.write_page(
            "deep-learning-overview",
            """# Deep Learning Overview

Deep learning is a subfield of machine learning. It uses neural networks
with many layers. The field has applications in computer vision and
natural language processing.

For background on the underlying algorithms, see machine learning
fundamentals and gradient descent tutorials.
""",
        )

        # ── Step 4: Query page with high jaccard overlap (topic_overlap)
        step(4, "Write Query: page with high topic overlap (topic_overlap)")
        wiki.write_page(
            "Query: neural networks",
            """# Query: neural networks

Neural networks are a class of machine learning models. They are inspired
by biological neurons and consist of layers of interconnected nodes.
Common architectures include feedforward, convolutional, and recurrent
neural networks.

Applications: image recognition, NLP, time series.
""",
        )

        # ── Step 5: add a raw source (latest year = 2024)
        step(5, "Add raw source (latest year = 2024)")
        raw_dst = work / "wiki" / "raw" / "ml_history_2024.md"
        raw_dst.parent.mkdir(parents=True, exist_ok=True)
        raw_dst.write_text(
            "# ML History 2024\n\nIn 2024, the ML field saw breakthroughs in "
            "transformer architectures and multimodal models.\n",
            encoding="utf-8",
        )
        print(f"   Added raw source: {raw_dst.name}")

        # ── Step 6: run lint and show per-rule breakdown
        step(6, "Run wiki.lint() and group issues by rule")
        result = wiki.lint()
        by_type = collect_types(result)
        total = sum(len(v) for v in by_type.values())
        print(f"\n   Total issues (across all categories): {total}")

        for rule_name in sorted(by_type):
            items = by_type[rule_name]
            print(f"\n   [{rule_name}] {len(items)} issue(s):")
            for it in items[:2]:
                page = it.get("page", "?")
                obs = it.get("observation", it.get("detail", str(it)))[:90]
                print(f"      - {page}: {obs}")
            if len(items) > 2:
                print(f"      ... and {len(items) - 2} more")

        # ── Step 7: brief mode (counts only)
        step(7, "Brief mode (counts only)")
        brief = wiki.lint(mode="brief")
        print(f"   total_pages: {brief.get('total_pages')}")
        print(f"   issue_count: {brief.get('issue_count')}")

        # ── Step 8: 8 rules coverage summary
        step(8, "Rule coverage summary (which fired)")
        all_rules = [
            "dated_claim",
            "potentially_outdated",
            "topic_overlap",
            "missing_cross_ref",
            "contradiction",
            "redundancy",
            "unsourced_claims",  # data_gap sub-rule
            "knowledge_gap",
        ]
        triggered = set(by_type.keys())
        for r in all_rules:
            mark = "✓" if r in triggered else "·"
            print(f"   {mark} {r}")

        print(f"\nDone. Wiki at: {work / 'wiki'}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
