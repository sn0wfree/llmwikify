"""Generate human-readable preview.md for a paper's extraction outputs.

Renders a single Markdown file combining:
  - Paper metadata + abstract (from track_a.json tier1)
  - Validation issues (from validator.ValidationReport)
  - Pass 1 signal list (name + brief formula)
  - Pass 2 first 5 factors' L1-L4 detail
  - Stats: counts, success rate, latency, n_calls

For human review of extraction quality before downstream consumption.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .validator import ValidationReport, validate_paper_outputs

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────


def _md_escape(text: str) -> str:
    """Escape pipe chars in markdown table cells."""
    if not isinstance(text, str):
        text = str(text)
    return text.replace("|", "\\|").replace("\n", " ").strip()[:200]


def _section_header(title: str) -> str:
    return f"\n## {title}\n\n"


# ── Section renderers ───────────────────────────────────────


def _render_overview(work_dir: Path, plan: dict | None) -> str:
    lines = _section_header("Overview")
    lines += f"- **Paper ID**: `{work_dir.name}`\n"
    if plan:
        p2 = plan.get("stage1_call2_plan", {})
        lines += f"- **Schema**: `{p2.get('schema_choice', 'unknown')}`\n"
        lines += f"- **Estimated signals**: {p2.get('n_signals_estimate', 0)}\n"
        lines += f"- **Planner confidence**: {p2.get('confidence', 0):.2f}\n"
        lines += f"- **Source**: `{plan.get('source_path', '?')}`\n"
        lines += f"- **Char count**: {plan.get('char_count', 0):,}\n"
    return lines


def _render_validation(report: ValidationReport) -> str:
    lines = _section_header("Validation")
    n_e = report.n_errors
    n_w = report.n_warnings
    n_i = len([i for i in report.issues if i.level == "info"])

    if report.files_missing:
        lines += f"**Missing files**: {', '.join(report.files_missing)}\n\n"

    if not report.issues:
        lines += "All outputs passed validation. No issues found.\n"
        return lines

    lines += f"**{n_e} errors, {n_w} warnings, {n_i} info**\n\n"
    for level, marker in [("error", "ERR"), ("warning", "WARN"), ("info", "INFO")]:
        items = report.by_level(level)
        if not items:
            continue
        lines += f"### {level.title()}\n\n"
        for issue in items:
            lines += f"- **[{marker}][{issue.file}]** {issue.message}\n"
        lines += "\n"
    return lines


def _render_tier1(track_a: dict) -> str:
    lines = _section_header("Tier 1: Paper Metadata & Abstract")
    tier1 = track_a.get("tier1", {})
    if not tier1:
        lines += "Tier 1 not available.\n"
        return lines

    meta = tier1.get("paper_metadata", {})
    if meta:
        lines += f"**Title**: {meta.get('title', '?')}\n\n"
        authors = meta.get("authors", [])
        if authors:
            lines += f"**Authors**: {', '.join(authors)}\n\n"
        if meta.get("institution"):
            lines += f"**Institution**: {meta['institution']}\n\n"
        if meta.get("date"):
            lines += f"**Date**: {meta['date']}\n\n"
        kw = meta.get("keywords", [])
        if kw:
            lines += f"**Keywords**: {', '.join(kw[:10])}\n\n"

    abstract = tier1.get("abstract_summary", {})
    if abstract:
        one = abstract.get("one_sentence", "")
        if one:
            lines += f"**One-sentence**: {one}\n\n"
        bullets = abstract.get("three_bullets", [])
        if bullets:
            lines += "**Three bullets**:\n"
            for b in bullets:
                lines += f"- {b}\n"
            lines += "\n"

    logic = tier1.get("strategy_logic", {})
    if logic:
        strat = logic.get("core_strategy", "")
        if strat:
            lines += f"**Core strategy**: {strat[:300]}\n\n"

    return lines


def _render_pass1_signals(pass1: dict) -> str:
    lines = _section_header(f"Pass 1 Signals (n={pass1.get('n_pass1', 0)})")
    sigs = pass1.get("pass1_signals", [])
    if not sigs:
        lines += "No signals extracted.\n"
        return lines

    # Show first 30 + total count
    preview = sigs[:30]
    lines += "| # | Name | Formula |\n|---|---|---|\n"
    for s in preview:
        name = _md_escape(s.get("name", ""))
        formula = _md_escape(s.get("formula_brief", ""))
        lines += f"| {s.get('index', '?')} | {name} | `{formula[:80]}` |\n"
    if len(sigs) > 30:
        lines += f"\n_... and {len(sigs) - 30} more_\n"
    lines += f"\n**LLM calls**: {pass1.get('llm_calls', 1)}\n"
    lines += f"**Latency**: {pass1.get('pass1_latency_ms', 0):,}ms\n"
    return lines


def _render_pass2_factors(pass2: dict) -> str:
    lines = _section_header(
        f"Pass 2 Factor Detail (n={pass2.get('n_pass2_complete', 0)} complete, "
        f"{pass2.get('n_pass2_failed', 0)} failed)"
    )
    details = pass2.get("pass2_details", [])
    if not details:
        lines += "No Pass 2 data.\n"
        return lines

    # Show first 5 successful + summary
    success = [d for d in details if d.get("success")]
    failed = [d for d in details if not d.get("success")]

    for d in success[:5]:
        lines += f"### `{d.get('name', '?')}`\n\n"
        if d.get("description"):
            lines += f"**Description**: {d['description']}\n\n"
        l1 = d.get("l1", {})
        if l1.get("formula"):
            lines += f"- **L1 formula**: `{_md_escape(l1['formula'])}`\n"
        l2 = d.get("l2", {})
        if l2:
            funcs = l2.get("function_calls") or l2.get("functions") or []
            if funcs:
                lines += f"- **L2 functions**: {', '.join(funcs[:10])}\n"
        l3 = d.get("l3", {})
        if l3:
            inputs = l3.get("input_data") or l3.get("data_types") or []
            if inputs:
                lines += f"- **L3 inputs**: {', '.join(inputs[:10])}\n"
        l4 = d.get("l4", {})
        if l4:
            strat = l4.get("strategy_type") or l4.get("category")
            if strat:
                lines += f"- **L4 strategy**: {strat}\n"
        lines += "\n"

    if failed:
        lines += f"### Failed ({len(failed)})\n\n"
        for d in failed[:3]:
            lines += f"- `{d.get('name')}`: {d.get('error')}\n"
        if len(failed) > 3:
            lines += f"- _... and {len(failed) - 3} more failures_\n"
        lines += "\n"

    lines += f"**Total latency**: {pass2.get('pass2_latency_ms', 0):,}ms\n"
    return lines


def _render_stats(track_a: dict, pass1: dict | None, pass2: dict | None) -> str:
    lines = _section_header("Stats")
    lines += "| Stage | Calls | Latency (ms) | Status |\n|---|---|---|---|\n"
    lines += f"| Stage 1 Call 1 | 1 | {track_a.get('latency_ms_tier1', 0):,} | {'OK' if track_a.get('success') else 'FAIL'} |\n"
    lines += "| Stage 1 Call 2 | 1 | - | (in plan.json) |\n"
    if pass1:
        lines += f"| Pass 1 | {pass1.get('llm_calls', 1)} | {pass1.get('pass1_latency_ms', 0):,} | {'OK' if pass1.get('n_pass1', 0) > 0 else 'FAIL'} |\n"
    if pass2:
        lines += f"| Pass 2 | {pass2.get('n_pass2_complete', 0) + pass2.get('n_pass2_failed', 0)} | {pass2.get('pass2_latency_ms', 0):,} | {pass2.get('n_pass2_complete', 0)}/{pass2.get('n_pass2_complete', 0) + pass2.get('n_pass2_failed', 0)} OK |\n"
    return lines


# ── Main entry point ────────────────────────────────────────


def generate_preview(work_dir: Path) -> str:
    """Generate preview.md content (does not write to disk)."""
    work_dir = Path(work_dir)

    plan_data = None
    plan_path = work_dir / "plan.json"
    if plan_path.exists():
        try:
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    track_a_data = {}
    track_a_path = work_dir / "track_a.json"
    if track_a_path.exists():
        try:
            track_a_data = json.loads(track_a_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    pass1_data = {}
    pass1_path = work_dir / "track_b_pass1.json"
    if pass1_path.exists():
        try:
            pass1_data = json.loads(pass1_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    pass2_data = {}
    # Pass 2 may be a single combined file or a directory of per-factor files
    pass2_path = work_dir / "track_b_pass2.json"
    if pass2_path.exists():
        try:
            pass2_data = json.loads(pass2_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    else:
        # Fallback: aggregate *_one.json, *_two.json etc.
        partials = sorted(work_dir.glob("track_b_pass2_*.json"))
        if partials:
            all_details = []
            n_complete = 0
            n_failed = 0
            for p in partials:
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and d.get("name"):
                        all_details.append(d)
                        if d.get("success"):
                            n_complete += 1
                        else:
                            n_failed += 1
                except json.JSONDecodeError:
                    pass
            if all_details:
                pass2_data = {
                    "n_pass1": len(all_details),
                    "n_pass2_complete": n_complete,
                    "n_pass2_failed": n_failed,
                    "pass2_details": all_details,
                    "pass2_latency_ms": 0,
                }

    report = validate_paper_outputs(work_dir)

    parts = [
        f"# Extraction Preview: `{work_dir.name}`\n",
        _render_overview(work_dir, plan_data),
        _render_validation(report),
    ]

    if track_a_data:
        parts.append(_render_tier1(track_a_data))

    if pass1_data and pass1_data.get("n_pass1", 0) > 0:
        parts.append(_render_pass1_signals(pass1_data))

    if pass2_data and (pass2_data.get("pass2_details") or pass2_data.get("n_pass2_complete", 0) > 0):
        parts.append(_render_pass2_factors(pass2_data))

    parts.append(_render_stats(track_a_data, pass1_data or None, pass2_data or None))

    return "".join(parts)


def write_preview(work_dir: Path, output_path: Path | None = None) -> Path:
    """Generate and write preview.md to disk."""
    work_dir = Path(work_dir)
    output_path = output_path or (work_dir / "preview.md")
    content = generate_preview(work_dir)
    output_path.write_text(content, encoding="utf-8")
    logger.info("[preview] wrote %s (%d chars)", output_path, len(content))
    return output_path
