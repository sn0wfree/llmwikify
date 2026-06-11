"""Paper structure extraction — LLM-based paper understanding.

Reads a paper (PDF/URL content) and extracts 8 categories of structured
information via LLM prompt (repro_extract.yaml). Also generates Factor
and Strategy wiki pages from the extracted information.

Phase 1 of the Paper → Factor → Strategy pipeline.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from .utils import generate_slug, parse_frontmatter

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    """Load the repro_extract.yaml prompt template."""
    prompt_path = (
        Path(__file__).parent.parent
        / "foundation"
        / "prompts"
        / "_defaults"
        / "repro_extract.yaml"
    )
    if not prompt_path.exists():
        logger.warning("repro_extract.yaml not found at %s", prompt_path)
        return ""
    return prompt_path.read_text(encoding="utf-8")


def extract_paper_structure(
    paper_content: str,
    paper_id: str = "",
    source_type: str = "pdf",
    source_ref: str = "",
    llm_client: Any = None,
) -> dict[str, Any]:
    """Extract structured information from paper content via LLM.

    Args:
        paper_content: The raw text content of the paper.
        paper_id: Identifier for the paper (e.g., arxiv ID).
        source_type: "pdf" or "url".
        source_ref: Path or URL to the source.
        llm_client: LLM client for calling the prompt. If None, returns empty.

    Returns:
        Dict with 8 categories of extracted information, or empty dict on failure.
    """
    if not paper_content or not paper_content.strip():
        logger.warning("empty paper content for %s", paper_id)
        return {}

    if llm_client is None:
        logger.info("no LLM client provided, returning empty extraction for %s", paper_id)
        return {}

    # Load prompt template
    prompt_text = _load_prompt()
    if not prompt_text:
        logger.error("repro_extract.yaml not found")
        return {}

    # Build user message with variables filled
    user_msg = (
        f"Extract structured information from this paper for strategy reproduction.\n\n"
        f"Paper ID: {paper_id}\n"
        f"Source type: {source_type}\n"
        f"Source reference: {source_ref}\n\n"
        f"Paper content:\n---\n{paper_content[:32000]}\n---\n\n"
        f"Extract the 8 categories and output as JSON."
    )

    try:
        response = llm_client.chat(user_msg, system="You are a quantitative research analyst.")
        # Try to parse JSON from response
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        logger.warning("no JSON found in LLM response for %s", paper_id)
        return {}
    except Exception as exc:
        logger.error("LLM extraction failed for %s: %s", paper_id, exc)
        return {}


def build_paper_pages(
    extraction: dict[str, Any],
    paper_id: str,
) -> list[dict[str, str]]:
    """Convert extraction result into wiki page content strings.

    Args:
        extraction: Output from extract_paper_structure().
        paper_id: Paper identifier for page naming.

    Returns:
        List of dicts with keys: page_name, content, page_type.
    """
    pages = []

    # 1. Strategy Logic page
    logic = extraction.get("strategy_logic", {})
    if logic:
        content = f"---\ntitle: Strategy Logic — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Strategy Logic\n\n"
        content += f"**Core Hypothesis:** {logic.get('core_hypothesis', 'TBD')}\n\n"
        content += f"**Market Logic:** {logic.get('market_logic', 'TBD')}\n\n"
        content += f"**Alpha Source:** {logic.get('alpha_source', 'TBD')}\n\n"
        content += f"**Applicable Conditions:** {logic.get('applicable_conditions', 'TBD')}\n"
        pages.append({"page_name": f"paper-{paper_id}-logic", "content": content, "page_type": "Source"})

    # 2. Data Requirements page
    data = extraction.get("data_requirements", {})
    if data:
        content = f"---\ntitle: Data Requirements — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Data Requirements\n\n"
        content += f"**Fields:** {', '.join(data.get('fields', ['TBD']))}\n\n"
        content += f"**Frequency:** {data.get('frequency', 'TBD')}\n\n"
        content += f"**Universe:** {data.get('universe', 'TBD')}\n\n"
        content += f"**Source:** {data.get('data_source', 'TBD')}\n"
        pages.append({"page_name": f"paper-{paper_id}-data", "content": content, "page_type": "Source"})

    # 3. Risks page
    risks = extraction.get("risks", {})
    if risks:
        content = f"---\ntitle: Risks — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Risks & Limitations\n\n"
        for item in risks.get("known_limitations", []):
            content += f"- **Known:** {item}\n"
        for item in risks.get("assumption_risks", []):
            content += f"- **Assumption:** {item}\n"
        for item in risks.get("implementation_gaps", []):
            content += f"- **Gap:** {item}\n"
        pages.append({"page_name": f"paper-{paper_id}-risks", "content": content, "page_type": "Source"})

    # 4. Factor page (from suggested_signal)
    suggested = extraction.get("suggested_signal", {})
    signal_type = suggested.get("signal_type", "unknown")
    if signal_type != "unknown":
        params = suggested.get("signal_params", {})
        params_str = json.dumps(params) if isinstance(params, dict) else str(params)
        factor_name = suggested.get("reasoning", f"Factor — {paper_id}")
        factor_slug = generate_slug(factor_name)
        page_name = f"factor-{paper_id}-{factor_slug}"
        content = f"---\ntitle: Factor — {paper_id}\n"
        content += f"type: Factor\n"
        content += f"factor_class: {signal_type}\n"
        content += f"factor_params: {params_str}\n"
        content += f"factor_source: paper/{paper_id}\n"
        content += f"signal_type: {signal_type}\n"
        content += f"signal_params: {params_str}\n"
        content += f"status: draft\n---\n\n"
        content += f"# Factor — {paper_id}\n\n"
        content += f"**Signal Type:** {signal_type}\n\n"
        content += f"**Parameters:** {params_str}\n\n"
        content += f"**Confidence:** {suggested.get('confidence', 'low')}\n\n"
        content += f"**Reasoning:** {suggested.get('reasoning', 'TBD')}\n"
        pages.append({"page_name": page_name, "content": content, "page_type": "Factor"})

    # 5. Strategy page (from suggested_signal)
    if signal_type != "unknown":
        params = suggested.get("signal_params", {})
        params_str = json.dumps(params) if isinstance(params, dict) else str(params)
        strategy_class = suggested.get("strategy_class", "trend_following")
        content = f"---\ntitle: Strategy — {paper_id}\n"
        content += f"type: Strategy\n"
        content += f"strategy_class: {strategy_class}\n"
        content += f"signal_type: {signal_type}\n"
        content += f"signal_params: {params_str}\n"
        content += f"factor_refs: [factor-{paper_id}-{factor_slug}]\n"
        content += f"status: draft\n---\n\n"
        content += f"# Strategy — {paper_id}\n\n"
        content += f"**Signal Type:** {signal_type}\n\n"
        content += f"**Parameters:** {params_str}\n\n"
        content += f"**Factor Reference:** [[factor-{paper_id}-{factor_slug}]]\n"
        pages.append({"page_name": f"strategy-{paper_id}", "content": content, "page_type": "Strategy"})

    return pages


__all__ = [
    "extract_paper_structure",
    "build_paper_pages",
]
