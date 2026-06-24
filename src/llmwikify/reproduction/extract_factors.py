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
import warnings
from pathlib import Path
from typing import Any, Optional

import yaml
from jinja2 import BaseLoader, Environment

from .common.utils import generate_slug, parse_frontmatter

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)

_API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}


def _load_prompt() -> tuple[str, str, dict[str, Any]]:
    """Load the repro_factor.yaml prompt template.

    Returns:
        (system_text, user_template, params) tuple.
    """
    prompt_path = (
        Path(__file__).parent.parent
        / "foundation"
        / "prompts"
        / "_defaults"
        / "repro_factor.yaml"
    )
    if not prompt_path.exists():
        logger.warning("repro_factor.yaml not found at %s", prompt_path)
        return ("", "", {})
    raw = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    return (raw.get("system", ""), raw.get("user", ""), raw.get("params", {}))


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

    system_text, user_template, params = _load_prompt()
    if not user_template:
        logger.error("repro_factor.yaml not found or empty")
        return []

    # Render user message with Jinja2 variables
    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        paper_understanding=json.dumps(paper_understanding, indent=2),
    )

    try:
        messages = []
        if system_text.strip():
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_msg})

        api_params = {k: v for k, v in params.items() if k in _API_PARAM_KEYS}
        response = llm_client.chat(messages, **api_params)

        # Parse JSON — strip markdown code fences first
        cleaned = re.sub(r"```(?:json)?\s*", "", response)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
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

    .. deprecated::
        Use ``factor_library.write_factor_yaml()`` instead. This function
        generates old-style wiki markdown pages which are no longer the
        canonical factor storage format.

    Args:
        factors: Output from extract_factors().
        paper_id: Paper identifier for page naming.

    Returns:
        List of dicts with keys: page_name, content, page_type.
    """
    warnings.warn(
        "build_factor_pages() is deprecated; use factor_library.write_factor_yaml()",
        DeprecationWarning,
        stacklevel=2,
    )
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

    .. deprecated::
        Use ``factor_library.read_factor_yaml()`` instead. Factor definitions
        are now stored as 6-layer YAML in ``quant/factors/``, not as wiki
        markdown frontmatter.

    Args:
        wiki: Wiki instance.
        slug: Factor page slug (without wiki/factor/ prefix).

    Returns:
        Parsed factor dict, or None if not found.
    """
    warnings.warn(
        "read_factor_from_wiki() is deprecated; use factor_library.read_factor_yaml()",
        DeprecationWarning,
        stacklevel=2,
    )
    from .factor_library import read_factor_yaml
    return read_factor_yaml(slug)


def list_factors(wiki: Any) -> list[dict[str, Any]]:
    """List all Factor pages in the wiki.

    .. deprecated::
        Use ``factor_library.list_factors()`` instead. Factor definitions
        are now stored as 6-layer YAML in ``quant/factors/``, not as wiki
        markdown pages.

    Returns:
        List of parsed frontmatter dicts.
    """
    warnings.warn(
        "list_factors() is deprecated; use factor_library.list_factors()",
        DeprecationWarning,
        stacklevel=2,
    )
    from .factor_library import list_factors as lib_list
    return lib_list()


__all__ = [
    "extract_factors",
    "build_factor_pages",
    "read_factor_from_wiki",
    "list_factors",
]
