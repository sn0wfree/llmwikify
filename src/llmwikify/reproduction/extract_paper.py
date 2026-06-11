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


def _fetch_content(source_ref: str, source_type: str, paper_id: str) -> str:
    """Fetch paper content from URL or PDF file when paper_content is empty."""
    if not source_ref:
        return ""

    if source_type == "pdf" and source_ref.startswith(("http://", "https://")):
        # Download PDF to temp file, extract text
        try:
            import tempfile
            import requests
            from llmwikify.foundation.extractors.pdf import extract_pdf

            resp = requests.get(source_ref, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
            }, allow_redirects=True)
            resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = Path(tmp.name)

            result = extract_pdf(tmp_path)
            tmp_path.unlink(missing_ok=True)
            logger.info("fetched PDF content for %s: %d chars", paper_id, len(result.text))
            return result.text
        except Exception as exc:
            logger.warning("failed to fetch PDF from %s: %s", source_ref, exc)
            return ""

    if source_type == "url" or source_ref.startswith(("http://", "https://")):
        # Fetch URL content via trafilatura
        try:
            from llmwikify.foundation.extractors.web import extract_url

            result = extract_url(source_ref)
            logger.info("fetched URL content for %s: %d chars", paper_id, len(result.text))
            return result.text
        except Exception as exc:
            logger.warning("failed to fetch URL content from %s: %s", source_ref, exc)
            return ""

    if source_type == "pdf" and not source_ref.startswith(("http://", "https://")):
        # Local PDF file
        try:
            from llmwikify.foundation.extractors.pdf import extract_pdf

            pdf_path = Path(source_ref)
            if pdf_path.exists():
                result = extract_pdf(pdf_path)
                logger.info("read local PDF for %s: %d chars", paper_id, len(result.text))
                return result.text
        except Exception as exc:
            logger.warning("failed to read local PDF %s: %s", source_ref, exc)
            return ""

    return ""


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
        # Try to fetch content from source_ref
        paper_content = _fetch_content(source_ref, source_type, paper_id)
        if not paper_content:
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
        messages = [
            {"role": "system", "content": "You are a quantitative research analyst."},
            {"role": "user", "content": user_msg},
        ]
        response = llm_client.chat(messages)
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

    # 4. Operation Steps page
    ops = extraction.get("operation_steps", {})
    if ops:
        content = f"---\ntitle: Operation Steps — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Operation Steps\n\n"
        labels = {
            "signal_generation": "Signal Generation",
            "position_sizing": "Position Sizing",
            "rebalance_frequency": "Rebalance Frequency",
            "stop_loss": "Stop Loss",
            "transaction_cost": "Transaction Cost",
        }
        for key, label in labels.items():
            value = ops.get(key, "TBD")
            content += f"**{label}:** {value}\n\n"
        pages.append({"page_name": f"paper-{paper_id}-operations", "content": content, "page_type": "Source"})

    # 5. Model Framework page
    model = extraction.get("model_framework", {})
    if model:
        content = f"---\ntitle: Model Framework — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Model Framework\n\n"
        content += f"**Model Type:** {model.get('model_type', 'TBD')}\n\n"
        content += f"**Framework:** {model.get('framework', 'TBD')}\n\n"
        content += f"**Validation:** {model.get('validation', 'TBD')}\n\n"
        metrics = model.get("evaluation_metrics", [])
        if metrics:
            content += f"**Evaluation Metrics:** {', '.join(metrics)}\n"
        pages.append({"page_name": f"paper-{paper_id}-model", "content": content, "page_type": "Source"})

    # 6. Strengths & Weaknesses page
    sw = extraction.get("strengths_weaknesses", {})
    if sw:
        content = f"---\ntitle: Strengths & Weaknesses — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Strengths & Weaknesses\n\n"
        if sw.get("strengths"):
            content += f"## Strengths\n\n"
            for item in sw["strengths"]:
                content += f"- {item}\n"
            content += "\n"
        if sw.get("weaknesses"):
            content += f"## Weaknesses\n\n"
            for item in sw["weaknesses"]:
                content += f"- {item}\n"
            content += "\n"
        if sw.get("improvement_directions"):
            content += f"## Improvement Directions\n\n"
            for item in sw["improvement_directions"]:
                content += f"- {item}\n"
        pages.append({"page_name": f"paper-{paper_id}-sw", "content": content, "page_type": "Source"})

    # 7. Datasets page
    datasets = extraction.get("datasets", {})
    if datasets:
        content = f"---\ntitle: Datasets — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# Datasets\n\n"
        content += f"**Name:** {datasets.get('name', 'TBD')}\n\n"
        content += f"**Source:** {datasets.get('source', 'TBD')}\n\n"
        content += f"**Time Range:** {datasets.get('time_range', 'TBD')}\n\n"
        content += f"**Processing:** {datasets.get('processing', 'TBD')}\n"
        pages.append({"page_name": f"paper-{paper_id}-datasets", "content": content, "page_type": "Source"})

    # 8. References page
    refs = extraction.get("references", {})
    if refs:
        content = f"---\ntitle: References — {paper_id}\npage_type: Source\n---\n\n"
        content += f"# References\n\n"
        if refs.get("original_paper"):
            content += f"## Original Paper\n\n{refs['original_paper']}\n\n"
        if refs.get("related_papers"):
            content += f"## Related Papers\n\n"
            for item in refs["related_papers"]:
                content += f"- {item}\n"
            content += "\n"
        if refs.get("code_repositories"):
            content += f"## Code Repositories\n\n"
            for item in refs["code_repositories"]:
                content += f"```\n{item}\n```\n"
        pages.append({"page_name": f"paper-{paper_id}-references", "content": content, "page_type": "Source"})

    # 9. Factor page (from suggested_signal)
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
