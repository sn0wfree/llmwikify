"""json_extract — parse JSON from LLM response text.

C1: extracted from `reproduction/codegen/llm_code.py`. Tolerant parser:
first tries ```json ... ``` fenced block, then falls back to finding
a JSON object `{...}` in raw text.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json_from_response(text: str) -> dict | None:
    """Parse JSON from ```json ... ``` fenced block in LLM response.

    Tolerant: if no fence, tries to find JSON object `{...}` in text.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("[codegen_utils] fenced JSON parse failed: %s", exc)

    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("[codegen_utils] raw JSON parse failed: %s", exc)

    return None
