"""Save plan.json for a paper after Stage 0 + Stage 1 calls.

Writes ``quant/papers/{id}/plan.json`` containing:
- Stage 0 metadata
- Stage 1 Call 1 sections
- Stage 1 Call 2 plan
- Token budget per stage
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .planner import PlanResult
from .section_detector import SectionDetectionResult
from .stage0_ingest import Stage0Result

logger = logging.getLogger(__name__)


def save_plan(
    stage0: Stage0Result,
    sections: SectionDetectionResult | None,
    plan: PlanResult,
    work_dir: Path,
) -> Path:
    """Write plan.json to the paper's working directory.

    Args:
        stage0: Result of Stage 0 ingestion.
        sections: Result of Stage 1 Call 1 (or None if failed).
        plan: Result of Stage 1 Call 2.
        work_dir: ``quant/papers/{id}/`` directory.

    Returns:
        Path to the written plan.json.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    plan_path = work_dir / "plan.json"

    data: dict[str, Any] = {
        "paper_id": stage0.paper_id,
        "title": stage0.title,
        "source_type": stage0.source_type,
        "char_count": stage0.char_count,
        "content_hash": stage0.content_hash,
        "source_path": str(stage0.source_path),
        "stage1_call1_sections": {
            "success": sections.success if sections else False,
            "n_sections": sections.n_sections if sections else 0,
            "latency_ms": sections.latency_ms if sections else 0,
            "error": sections.error if sections else "no_call",
            "sections": [s.to_dict() for s in sections.sections] if sections and sections.success else [],
        },
        "stage1_call2_plan": {
            "success": plan.success,
            "schema_choice": plan.schema_choice,
            "paper_type": plan.paper_type,
            "n_signals_estimate": plan.n_signals_estimate,
            "extraction_strategy": plan.extraction_strategy,
            "token_budget": plan.token_budget,
            "confidence": plan.confidence,
            "latency_ms": plan.latency_ms,
            "error": plan.error,
        },
    }
    plan_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[plan] saved: %s", plan_path)
    return plan_path
