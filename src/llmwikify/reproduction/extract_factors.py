"""Factor extraction from paper understanding.

Takes the structured paper understanding (from extract_paper.py) and
extracts individual factor definitions, mapping them to signal types
for backtesting.

Phase 2 of the Paper → Factor → Strategy pipeline.
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
    """Load the repro_factor.yaml prompt template."""
    prompt_path = (
        Path(__file__).parent.parent
        / "foundation"
        / "prompts"
        / "_defaults"
        / "repro_factor.yaml"
    )
    if not prompt_path.exists():
        logger.warning("repro_factor.yaml not found at %s", prompt_path)
        return ""
    return prompt_path.read_text(encoding="utf-8")


def extract_factors(
    paper_understanding: dict[str, Any],
    paper_id: str = "",
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    """Extract factor definitions from paper understanding.

    Args:
        paper_understanding: Output from extract_paper_structure().
        paper_id: Paper identifier.
        llm_client: LLM client for calling the prompt. If None, returns empty.

    Returns:
        List of factor dicts with keys: name, factor_class, description,
        formula, params, signal_type, signal_params, confidence.
    """
    if not paper_understanding:
        return []

    if llm_client is None:
        logger.info("no LLM client, returning empty factor list for %s", paper_id)
        return []

    prompt_text = _load_prompt()
    if not prompt_text:
        logger.error("repro_factor.yaml not found")
        return []

    user_msg = (
        f"Given this paper's structured understanding, extract factor definitions.\n\n"
        f"Paper ID: {paper_id}\n"
        f"Paper understanding:\n---\n{json.dumps(paper_understanding, indent=2)}\n---\n\n"
        f"Extract factors and map to signal types. Output JSON."
    )

    try:
        response = llm_client.chat(user_msg, system="You are a quantitative factor researcher.")
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result.get("factors", [])
        logger.warning("no JSON found in LLM response for %s", paper_id)
        return []
    except Exception as exc:
        logger.error("LLM factor extraction failed for %s: %s", paper_id, exc)
        return []


def build_factor_pages(
    factors: list[dict[str, Any]],
    paper_id: str,
) -> list[dict[str, str]]:
    """Convert factor definitions into wiki page content strings.

    Args:
        factors: Output from extract_factors().
        paper_id: Paper identifier for page naming.

    Returns:
        List of dicts with keys: page_name, content, page_type.
    """
    pages = []
    for i, factor in enumerate(factors):
        name = factor.get("name", f"Factor {i+1}")
        factor_class = factor.get("factor_class", "unknown")
        signal_type = factor.get("signal_type", "unknown")
        signal_params = factor.get("signal_params", {})
        params_str = json.dumps(signal_params) if isinstance(signal_params, dict) else str(signal_params)

        slug = generate_slug(name)

        content = f"---\ntitle: {name}\n"
        content += f"factor_class: {factor_class}\n"
        content += f"factor_params: {params_str}\n"
        content += f"factor_source: paper/{paper_id}\n"
        content += f"status: draft\n---\n\n"
        content += f"# {name}\n\n"
        content += f"**Class:** {factor_class}\n\n"
        content += f"**Description:** {factor.get('description', 'TBD')}\n\n"
        content += f"**Formula:** {factor.get('formula', 'TBD')}\n\n"
        content += f"**Mapped Signal:** {signal_type} {params_str}\n\n"
        content += f"**Confidence:** {factor.get('confidence', 'low')}\n"

        pages.append({
            "page_name": f"factor-{paper_id}-{slug}",
            "content": content,
            "page_type": "Factor",
        })

    return pages


def read_factor_from_wiki(wiki: Any, slug: str) -> Optional[dict[str, Any]]:
    """Read a Factor page from wiki and parse its frontmatter.

    Args:
        wiki: Wiki instance.
        slug: Factor page slug (without wiki/factor/ prefix).

    Returns:
        Parsed factor dict, or None if not found.
    """
    factor_dir = wiki.wiki_dir / "factor"
    if not factor_dir.is_dir():
        return None
    md_path = factor_dir / f"{slug}.md"
    if not md_path.exists():
        return None
    try:
        content = md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_frontmatter(content)


def list_factors(wiki: Any) -> list[dict[str, Any]]:
    """List all Factor pages in the wiki.

    Returns:
        List of parsed frontmatter dicts.
    """
    factor_dir = wiki.wiki_dir / "factor"
    if not factor_dir.is_dir():
        return []
    results = []
    for md in sorted(factor_dir.glob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            if fm:
                fm["_slug"] = md.stem
                results.append(fm)
        except OSError as exc:
            logger.warning("could not read %s: %s", md, exc)
    return results


__all__ = [
    "extract_factors",
    "build_factor_pages",
    "read_factor_from_wiki",
    "list_factors",
]
