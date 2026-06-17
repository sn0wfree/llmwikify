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

import yaml
from jinja2 import BaseLoader, Environment

from .utils import generate_slug, parse_frontmatter

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)

_API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}


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

    if source_type in ("pdf", "raw") and not source_ref.startswith(("http://", "https://")):
        # Local PDF file (pdf or raw source type)
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


def _load_prompt() -> tuple[str, str, dict[str, Any]]:
    """Load the repro_extract.yaml prompt template.

    Returns:
        (system_text, user_template, params) tuple.
    """
    prompt_path = (
        Path(__file__).parent.parent
        / "foundation"
        / "prompts"
        / "_defaults"
        / "repro_extract.yaml"
    )
    if not prompt_path.exists():
        logger.warning("repro_extract.yaml not found at %s", prompt_path)
        return ("", "", {})
    raw = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    return (raw.get("system", ""), raw.get("user", ""), raw.get("params", {}))


def _repair_truncated_json(text: str, exc: json.JSONDecodeError) -> dict[str, Any]:
    """Attempt to repair a truncated JSON response from the LLM.

    The LLM may hit max_tokens mid-output, leaving unclosed braces/brackets
    or mid-key/mid-value strings. Strategy: find the last complete object/
    value boundary, close all open brackets, and try to parse.
    """
    if not text:
        return {}
    pos = exc.pos if hasattr(exc, "pos") and exc.pos > 0 else len(text)
    # Find candidate truncation points: last }, last ], and the error position
    candidates = sorted(set(
        [pos, text.rfind("}") + 1, text.rfind("]") + 1, text.rfind('",') + 2]
        + list(range(pos, max(pos - 1000, 0), -50))
    ), reverse=True)
    for try_pos in candidates:
        if try_pos <= 0:
            continue
        candidate = text[:try_pos]
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape = False
        for ch in candidate:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                open_braces += 1
            elif ch == "}":
                open_braces -= 1
            elif ch == "[":
                open_brackets += 1
            elif ch == "]":
                open_brackets -= 1
        suffix = ""
        if in_string:
            suffix += '"'
        suffix += "]" * max(open_brackets, 0)
        suffix += "}" * max(open_braces, 0)
        repaired = candidate + suffix
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            continue
    return {}


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
    system_text, user_template, params = _load_prompt()
    if not user_template:
        logger.error("repro_extract.yaml not found or empty")
        return {}

    # Render user message with Jinja2 variables
    max_content_chars = params.get("max_content_chars", 100000)
    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        source_type=source_type,
        source_ref=source_ref,
        paper_content=paper_content[:max_content_chars],
    )

    logger.info("[extract] paper=%s content_len=%d calling LLM...", paper_id, len(paper_content))
    try:
        messages = []
        if system_text.strip():
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_msg})

        api_params = {k: v for k, v in params.items() if k in _API_PARAM_KEYS}
        logger.info("[extract] paper=%s api_params=%s, sending request...", paper_id, api_params)
        response = llm_client.chat(messages, **api_params)
        logger.info("[extract] paper=%s LLM response received, len=%d", paper_id, len(response))

        # Parse JSON — strip markdown code fences first
        cleaned = re.sub(r"```(?:json)?\s*", "", response)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                logger.info("[extract] paper=%s JSON parsed, keys=%s", paper_id, list(result.keys()))
                if "factor_list" in result:
                    logger.info("[extract] paper=%s factor_list has %d factors", paper_id, len(result["factor_list"]))
                return result
            except json.JSONDecodeError as exc:
                # Try to repair truncated JSON (LLM hit max_tokens mid-output)
                logger.warning("[extract] paper=%s JSON parse failed at %s, attempting repair...",
                              paper_id, exc)
                result = _repair_truncated_json(json_match.group(), exc)
                if result:
                    logger.info("[extract] paper=%s JSON repaired, keys=%s", paper_id, list(result.keys()))
                    if "factor_list" in result:
                        logger.info("[extract] paper=%s factor_list has %d factors (repaired)",
                                    paper_id, len(result["factor_list"]))
                    return result
                logger.warning("[extract] paper=%s JSON repair failed", paper_id)
        logger.warning("no JSON found in LLM response for %s (response_len=%d)", paper_id, len(response))
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


def _extract_factors_from_list(
    extraction: dict[str, Any],
    paper_id: str,
) -> list[dict[str, Any]]:
    """Convert extraction.factor_list[] to 6-layer factor dicts.

    Each entry in factor_list has L1-L4 fields. This function assembles
    them into the full 6-layer YAML structure expected by write_factor_yaml().

    Returns list of dicts: {name: "asset/category/slug", factor: {l1..l5}}
    """
    from llmwikify.reproduction.utils import generate_slug

    factor_list = extraction.get("factor_list", [])
    if not factor_list:
        return []

    results = []
    for i, fm in enumerate(factor_list):
        name = fm.get("name", f"alpha_{i+1:03d}")
        slug = generate_slug(name)
        asset_type = fm.get("asset_type", "stock")
        category = fm.get("category", "price")
        factor_name = f"{asset_type}/{category}/{slug}"

        # L1: definition, formula, inputs, params
        l1 = {
            "definition": fm.get("definition") or fm.get("description") or f"Factor from {paper_id}",
            "formula": fm.get("formula", "TBD"),
            "input_columns": fm.get("input_columns", ["close"]),
            "frequency": fm.get("frequency", "日频"),
            "output_schema": "[date × Code]",
            "nan_meaning": "TBD",
            "default_params": fm.get("default_params", {}),
            "param_constraints": fm.get("param_constraints", "TBD"),
            "business_constraints": fm.get("business_constraints", "TBD"),
        }

        # L2: calculation steps
        steps = fm.get("calculation_steps", [])
        if not steps:
            steps = [{"step": 1, "description": f"计算 {name} 因子"}]
        l2 = {
            "calculation_steps": steps,
            "edge_case_handling": fm.get("edge_case_handling", "TBD"),
            "missing_value_handling": fm.get("missing_value_handling", "TBD"),
            "data_alignment": "T+1",
            "complexity": fm.get("complexity", "O(T × N)"),
        }

        # L3: financial intuition, market behavior, theory
        l3 = {
            "financial_intuition": fm.get("financial_intuition", "TBD"),
            "market_behavior": fm.get("market_behavior", "TBD"),
            "theoretical_basis": fm.get("theoretical_basis", "TBD"),
            "historical_effectiveness": fm.get("historical_effectiveness", "TBD"),
            "related_factors": fm.get("related_factors", "TBD"),
        }

        # L4: hypotheses
        hypotheses = fm.get("hypotheses", [])
        for h in hypotheses:
            if "status" not in h:
                h["status"] = "未验证"
        l4 = {
            "hypotheses": hypotheses,
            "hypothesis_limit": 5,
            "archived_hypotheses": [],
            "meaning_summary": fm.get("description") or fm.get("financial_intuition", "TBD"),
            "key_insights": fm.get("key_insights", []),
            "uncertainty": fm.get("uncertainty", "TBD"),
            "final_meaning": None,
        }

        factor_dict = {
            "name": factor_name.replace("/", "_"),
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "l4": l4,
            "l5": {"overall_assessment": {"score": 0, "status": "未验证", "modules": {}}},
            "metadata": {
                "created_at": "TBD",
                "updated_at": "TBD",
                "version": 1,
                "source_paper": paper_id,
                "factor_source": f"paper/{paper_id}",
            },
        }

        results.append({"name": factor_name, "factor": factor_dict})

    return results


__all__ = [
    "extract_paper_structure",
    "build_paper_pages",
    "_extract_factors_from_list",
]
