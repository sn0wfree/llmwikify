"""LLM output -> JSON AST extractor with SAP (Schema-Aligned Parsing).

LLM emits AST wrapped in markdown fences, chain-of-thought, or chatty prose.
This module locates the JSON object and parses it as ASTNode.

Reference: docs/designs/llm_compile_loop_v4.md (BAML-style SAP)
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from .nodes import ASTNode

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
_FIRST_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)


def _strip_chatty_prefix(text: str) -> str:
    """Strip common chatty prefixes like 'Here is the AST:'."""
    patterns = [
        r"^(?:here(?:'s| is)|the |sure[,!]?\s+|certainly[,!]?\s+).*?:\s*\n",
        r"^```json\s*\n",
        r"^```\s*\n",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to parse text as JSON object. Returns None on failure."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        return None
    return None


def _find_json_block(text: str) -> str | None:
    """Find the first JSON object in text using multiple strategies."""
    text = _strip_chatty_prefix(text)

    # Strategy 1: ```json { ... } ```
    m = _JSON_FENCE.search(text)
    if m:
        return m.group(1)

    # Strategy 2: bare JSON
    m = _BARE_JSON.search(text)
    if m:
        return m.group(0)

    # Strategy 3: first {...} (greedy, fallback)
    m = _FIRST_OBJECT.search(text)
    if m:
        return m.group(0)

    return None


def extract_ast(text: str) -> ASTNode | None:
    """Extract AST from LLM text output. Returns None on failure.

    Handles:
    - Markdown fences ```json { ... } ```
    - Bare JSON
    - Chatty prefix ("Here is the AST:")
    - SAP-style repair (try multiple strategies)
    """
    if not text or not text.strip():
        return None

    block = _find_json_block(text)
    if block is None:
        return None

    obj = _try_parse_json(block)
    if obj is None:
        # Try to repair: strip trailing comma
        repaired = re.sub(r",\s*([}\]])", r"\1", block)
        obj = _try_parse_json(repaired)
    if obj is None:
        return None

    try:
        return ASTNode(**obj)
    except ValidationError:
        return None


__all__ = ["extract_ast"]
