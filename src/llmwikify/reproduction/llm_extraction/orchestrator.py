"""Orchestrate Stage 0/1/2 + Deferred queue for a single paper.

``run_one_paper`` is the entry point: it runs the full extraction flow
on one paper, catching ``DeferError`` from any stage and queueing it for
one retry at the end.

Flow:
  1. Stage 0: run_stage0_ingest
  2. Stage 1 Call 1: detect_sections (DeferError → queue + use no-sections fallback)
  3. Stage 1 Call 2: plan_paper (DeferError → queue + use summary fallback)
  4. Track A: run_track_a (DeferError → queue + mark partial)
  5. Track B: run_track_b (DeferError → queue + skip pass2)
  6. Generate preview.md
  7. Flush deferred queue once
  8. Save deferred metadata
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from .defer import DeferredQueue
from .planner import PlanResult
from .plan_saver import save_plan
from .preview import write_preview
from .retry import DeferError
from .section_detector import Section, SectionDetectionResult, detect_sections
from .stage0_ingest import Stage0Result, run_stage0_ingest
from .track_a import TrackAResult, run_track_a
from .track_b import TrackBResult, run_track_b
from .validator import validate_paper_outputs

logger = logging.getLogger(__name__)


def _make_fallback_plan(paper_id: str, parsed_text: str) -> PlanResult:
    """Default PlanResult when planner fails: use summary schema."""
    return PlanResult(
        paper_id=paper_id,
        schema_choice="summary",
        paper_type="unknown",
        n_signals_estimate=0,
        extraction_strategy="planner failed; defaulting to summary schema",
        token_budget={
            "track_a_tier1": 3072,
            "track_a_tier2_per_section": 2048,
            "track_b_pass1": 4096,
            "track_b_pass2_per_factor": 4096,
            "preview": 1536,
        },
        confidence=0.0,
        success=True,
        error="fallback_summary_schema",
    )


def _slugify(name: str) -> str:
    """Convert factor name like 'Alpha#1' to 'alpha-001'."""
    m = re.search(r"(\d+)", name)
    if m:
        return f"alpha-{int(m.group(1)):03d}"
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _write_factor_yamls(
    work_dir: Path,
    paper_id: str,
    pass2_details: list,
    pass1_signals: list,
) -> int:
    """Write draft factor YAML files to work_dir/factors/.

    Each successful factor gets a separate YAML file matching the
    6-layer structure expected by quant/factors/.

    Returns number of files written.
    """
    import yaml

    factors_dir = work_dir / "factors"
    factors_dir.mkdir(parents=True, exist_ok=True)

    # Build pass1 lookup for formula_brief
    pass1_map = {s.name: s for s in pass1_signals}

    written = 0
    for detail in pass2_details:
        if not detail.success or not detail.l1:
            continue

        slug = _slugify(detail.name)
        stub = pass1_map.get(detail.name)

        factor_data = {
            "factor": {
                "name": slug,
                "name_cn": detail.description[:50] if detail.description else detail.name,
                "asset_type": "stock",
                "category": "alpha",
                "subcategory": "paper_derived",
                "version": 1,
                "source_paper": paper_id,
                "status": "draft",
                "l1": detail.l1,
                "l2": detail.l2,
                "l3": detail.l3,
                "l4": detail.l4,
            }
        }

        yaml_path = factors_dir / f"{slug}.yaml"
        content = yaml.dump(
            factor_data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        yaml_path.write_text(content, encoding="utf-8")
        written += 1

    logger.info(
        "[orchestrator] wrote %d draft factor YAMLs to %s",
        written, factors_dir,
    )
    return written


def run_one_paper(
    paper_id: str,
    source_path: str | Path,
    output_root: Path,
    *,
    run_pass2: bool = True,
    llm_client: Any | None = None,
) -> dict:
    """Run Stage 0/1/2 + flush deferred queue for a single paper.

    Args:
        paper_id: Stable paper identifier; also the work-dir name.
        source_path: PDF file path (absolute or relative).
        output_root: ``quant/papers/`` directory. Each paper lives in
            ``{output_root}/{paper_id}/``.
        run_pass2: Whether to also run Track B Pass 2 (per-factor detail).
        llm_client: Optional pre-built LLM client.

    Returns:
        Summary dict with keys:
          paper_id, success, plan_success, n_signals, n_pass2_complete,
          n_pass2_failed, deferred_count, deferred_resolved,
          deferred_failed, llm_calls, total_latency_ms, error
    """
    source_path = Path(source_path)
    output_root = Path(output_root)
    work_dir = output_root / paper_id
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[orchestrator] paper=%s starting (run_pass2=%s)", paper_id, run_pass2)

    deferred = DeferredQueue(work_dir)
    summary: dict[str, Any] = {
        "paper_id": paper_id,
        "success": False,
        "plan_success": False,
        "n_signals": 0,
        "n_pass2_complete": 0,
        "n_pass2_failed": 0,
        "deferred_count": 0,
        "deferred_resolved": 0,
        "deferred_failed": 0,
        "llm_calls": 0,
        "total_latency_ms": 0,
        "error": None,
    }
    t_total = time.monotonic()

    # Stage 0: PDF → parsed.md
    logger.info("[orchestrator] paper=%s [1/5] stage0: extracting source", paper_id)
    try:
        s0 = run_stage0_ingest(
            source=source_path,
            output_root=output_root,
            paper_id=paper_id,
        )
        logger.info(
            "[orchestrator] paper=%s [1/5] stage0: ok (%d chars, hash=%s)",
            paper_id, s0.char_count, s0.content_hash,
        )
    except Exception as exc:
        logger.error("[orchestrator] paper=%s [1/5] stage0: FAILED %s", paper_id, exc)
        summary["error"] = f"stage0: {exc}"
        summary["total_latency_ms"] = int((time.monotonic() - t_total) * 1000)
        deferred.save_metadata()
        return summary

    parsed_text = s0.text
    title = s0.title

    # Stage 1 Call 1: detect sections
    logger.info("[orchestrator] paper=%s [2/5] stage1_call1: detecting sections", paper_id)
    sec_result: SectionDetectionResult | None = None
    sections: list[Section] | None = None
    try:
        sec_result = detect_sections(
            paper_id=paper_id,
            parsed_text=parsed_text,
            llm_client=llm_client,
        )
        if sec_result.success:
            sections = sec_result.sections
            logger.info(
                "[orchestrator] paper=%s [2/5] stage1_call1: ok (%d sections)",
                paper_id, len(sections or []),
            )
        elif sec_result.error and "llm_error" in sec_result.error:
            logger.warning(
                "[orchestrator] paper=%s [2/5] stage1_call1: failed: %s",
                paper_id, sec_result.error,
            )
        else:
            logger.warning(
                "[orchestrator] paper=%s [2/5] stage1_call1: returned no sections: %s",
                paper_id, sec_result.error,
            )
    except DeferError as exc:
        logger.warning(
            "[orchestrator] paper=%s [2/5] stage1_call1: deferred: %s",
            paper_id, exc,
        )
        deferred.add(
            "stage1_call1", detect_sections,
            (paper_id, parsed_text), {"llm_client": llm_client},
            reason=str(exc),
        )

    # Stage 1 Call 2: plan paper
    logger.info("[orchestrator] paper=%s [3/5] stage1_call2: planning", paper_id)
    try:
        plan = _run_planner(
            paper_id=paper_id, title=title, parsed_text=parsed_text,
            sections=sections, llm_client=llm_client,
        )
        logger.info(
            "[orchestrator] paper=%s [3/5] stage1_call2: ok schema=%s n=%d conf=%.2f",
            paper_id, plan.schema_choice, plan.n_signals_estimate, plan.confidence,
        )
    except DeferError as exc:
        logger.warning(
            "[orchestrator] paper=%s [3/5] stage1_call2: deferred, using summary fallback: %s",
            paper_id, exc,
        )
        deferred.add(
            "stage1_call2", _run_planner,
            (paper_id, title, parsed_text), {"sections": sections, "llm_client": llm_client},
            reason=str(exc),
        )
        plan = _make_fallback_plan(paper_id, parsed_text)
    summary["plan_success"] = plan.success

    # Save plan.json
    try:
        save_plan(s0, sec_result, plan, work_dir)
        logger.info("[orchestrator] paper=%s plan.json saved", paper_id)
    except Exception as exc:
        logger.warning("[orchestrator] paper=%s plan.json save failed: %s", paper_id, exc)

    # Track A
    logger.info(
        "[orchestrator] paper=%s [4/5] track_a: tier1+tier2 starting",
        paper_id,
    )
    track_a_result = None
    try:
        track_a_result = run_track_a(
            paper_id=paper_id,
            title=title,
            parsed_text=parsed_text,
            plan=plan,
            sections=sections,
            llm_client=llm_client,
        )
        if track_a_result.success:
            logger.info(
                "[orchestrator] paper=%s [4/5] track_a: ok tier1=%dB tier2_attempted=%d failed=%d (%dms)",
                paper_id,
                track_a_result.latency_ms_tier1,
                len(track_a_result.tier2_sections_attempted),
                len(track_a_result.tier2_sections_failed),
                track_a_result.latency_ms_total,
            )
        else:
            logger.warning(
                "[orchestrator] paper=%s [4/5] track_a: failed: %s",
                paper_id, track_a_result.error,
            )
        # Save track_a.json (always, even on partial failure)
        try:
            track_a_path = work_dir / "track_a.json"
            track_a_path.write_text(
                json.dumps(track_a_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("[orchestrator] paper=%s track_a.json saved", paper_id)
        except Exception as exc:
            logger.warning("[orchestrator] paper=%s track_a.json save failed: %s", paper_id, exc)
    except DeferError as exc:
        logger.warning(
            "[orchestrator] paper=%s [4/5] track_a: deferred: %s",
            paper_id, exc,
        )
        deferred.add(
            "track_a", run_track_a,
            (paper_id, title, parsed_text, plan),
            {"sections": sections, "llm_client": llm_client},
            reason=str(exc),
        )
        track_a_result = None

    # Track B
    logger.info(
        "[orchestrator] paper=%s [5/5] track_b: pass1+pass2 starting (run_pass2=%s)",
        paper_id, run_pass2,
    )
    track_b_result = None
    try:
        track_b_result = run_track_b(
            paper_id=paper_id,
            parsed_text=parsed_text,
            plan=plan,
            llm_client=llm_client,
            run_pass2=run_pass2,
            work_dir=work_dir,
        )
        if track_b_result.success:
            logger.info(
                "[orchestrator] paper=%s [5/5] track_b: ok pass1=%d pass2_complete=%d/%d (%dms, %d LLM calls)",
                paper_id,
                track_b_result.n_pass1,
                track_b_result.n_pass2_complete,
                track_b_result.n_pass2_complete + track_b_result.n_pass2_failed,
                track_b_result.total_latency_ms,
                track_b_result.llm_calls,
            )
            # Save track_b_pass1.json + track_b_pass2.json
            try:
                pass1_path = work_dir / "track_b_pass1.json"
                pass1_data = {
                    "paper_id": paper_id,
                    "n_pass1": track_b_result.n_pass1,
                    "n_signals": track_b_result.n_pass1,
                    "pass1_signals": [s.to_dict() for s in track_b_result.pass1_signals],
                    "latency_ms": track_b_result.pass1_latency_ms,
                }
                pass1_path.write_text(
                    json.dumps(pass1_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("[orchestrator] paper=%s track_b_pass1.json saved (%d signals)", paper_id, track_b_result.n_pass1)

                pass2_path = work_dir / "track_b_pass2.json"
                pass2_data = {
                    "paper_id": paper_id,
                    "n_pass1": track_b_result.n_pass1,
                    "n_pass2_complete": track_b_result.n_pass2_complete,
                    "n_pass2_failed": track_b_result.n_pass2_failed,
                    "n_complete": track_b_result.n_pass2_complete,
                    "n_failed": track_b_result.n_pass2_failed,
                    "pass2_details": [d.to_dict() for d in track_b_result.pass2_details],
                    "latency_ms": track_b_result.pass2_latency_ms,
                }
                pass2_path.write_text(
                    json.dumps(pass2_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("[orchestrator] paper=%s track_b_pass2.json saved (%d/%d)", paper_id, track_b_result.n_pass2_complete, track_b_result.n_pass2_complete + track_b_result.n_pass2_failed)

                # Write draft factor YAML files
                n_yamls = _write_factor_yamls(
                    work_dir, paper_id,
                    track_b_result.pass2_details,
                    track_b_result.pass1_signals,
                )
                logger.info("[orchestrator] paper=%s %d draft factor YAMLs written", paper_id, n_yamls)
            except Exception as exc:
                logger.warning("[orchestrator] paper=%s track_b json save failed: %s", paper_id, exc)
        else:
            logger.warning(
                "[orchestrator] paper=%s [5/5] track_b: failed: %s",
                paper_id, track_b_result.error,
            )
    except DeferError as exc:
        logger.warning(
            "[orchestrator] paper=%s [5/5] track_b: deferred: %s",
            paper_id, exc,
        )
        deferred.add(
            "track_b", run_track_b,
            (paper_id, parsed_text, plan),
            {"llm_client": llm_client, "run_pass2": run_pass2, "work_dir": work_dir},
            reason=str(exc),
        )
        track_b_result = None

    # Stats
    if track_b_result is not None:
        summary["n_signals"] = track_b_result.n_pass1
        summary["n_pass2_complete"] = track_b_result.n_pass2_complete
        summary["n_pass2_failed"] = track_b_result.n_pass2_failed
        summary["llm_calls"] = (
            (track_a_result.llm_calls if track_a_result else 0)
            + track_b_result.llm_calls
        )
    elif track_a_result is not None:
        summary["llm_calls"] = track_a_result.llm_calls

    # Flush deferred queue (one retry pass)
    summary["deferred_count"] = len(deferred)
    if deferred:
        logger.info(
            "[orchestrator] paper=%s flushing %d deferred items",
            paper_id, len(deferred),
        )
        resolved, errors = deferred.flush()
        summary["deferred_resolved"] = resolved
        summary["deferred_failed"] = len(errors)
        logger.info(
            "[orchestrator] paper=%s flush: resolved=%d failed=%d",
            paper_id, resolved, len(errors),
        )
    deferred.save_metadata()

    # Generate preview
    logger.info("[orchestrator] paper=%s generating preview.md", paper_id)
    try:
        write_preview(work_dir)
        logger.info("[orchestrator] paper=%s preview.md ok", paper_id)
    except Exception as exc:
        logger.warning(
            "[orchestrator] paper=%s preview generation failed: %s",
            paper_id, exc,
        )

    summary["success"] = True
    summary["total_latency_ms"] = int((time.monotonic() - t_total) * 1000)
    logger.info(
        "[orchestrator] paper=%s DONE in %dms (n_signals=%d pass2=%d/%d deferred=%d resolved=%d llm_calls=%d)",
        paper_id,
        summary["total_latency_ms"],
        summary["n_signals"],
        summary["n_pass2_complete"],
        summary["n_pass2_complete"] + summary["n_pass2_failed"],
        summary["deferred_count"],
        summary["deferred_resolved"],
        summary["llm_calls"],
    )
    return summary


def _run_planner(
    paper_id: str,
    title: str,
    parsed_text: str,
    sections: list[Section] | None,
    llm_client: Any | None,
) -> PlanResult:
    """Wrapper around plan_paper so it can be deferred."""
    from .planner import plan_paper
    return plan_paper(
        paper_id=paper_id, title=title, parsed_text=parsed_text,
        sections=sections, llm_client=llm_client,
    )
