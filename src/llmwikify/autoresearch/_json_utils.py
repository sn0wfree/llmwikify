"""Robust JSON parsing for LLM responses.

The autoresearch pipeline makes ~6 LLM calls that expect JSON output.
Even with ``json_mode=True`` and ``response_format={type: json_object}``
set, model outputs occasionally contain:

* Empty body (max_tokens cut, or safety filter returned ``content=""``)
* Markdown code fences (``\\`\\`\\`json ... \\`\\`\\```)
* Trailing prose ("Note: ...")
* Multiple JSON objects in one response
* Leading prose ("Here is the JSON: { ... }")
* Truncated strings from streaming cutoffs

This module centralizes the defensive parsing that was previously
duplicated at 5 call sites. The strategy is:

1. Strip leading/trailing whitespace.
2. Strip markdown code fences (```json ... ```).
3. If the response is empty after stripping, raise JSONDecodeError
   with a clear "empty response" message.
4. Try a direct ``json.loads``.
5. On failure with ``allow_truncate=True`` (default), use
   ``JSONDecoder().raw_decode`` which finds the first complete
   JSON value in the string and ignores any leading or trailing
   junk. This is the OpenJDK/CPython-standard way to robustly
   parse a JSON value embedded in prose.
6. If still failing, re-raise the original error.
"""

from __future__ import annotations

import json
from typing import Any


def safe_json_loads(raw: str, *, allow_truncate: bool = True) -> Any:
    """Robustly parse JSON returned by an LLM.

    Args:
        raw: The LLM response string. May be empty, may contain
            markdown fences, may have trailing prose, may be truncated.
        allow_truncate: If True (default), use ``raw_decode`` to find
            the first valid JSON value in the input, ignoring any
            surrounding prose. Set False to disable this rescue
            (e.g., for tests that want strict behavior).

    Returns:
        The parsed JSON value (typically a dict).

    Raises:
        json.JSONDecodeError: If the input cannot be parsed even
            after truncation attempts.
    """
    text = raw.strip() if raw else ""
    if not text:
        raise json.JSONDecodeError("empty response", "", 0)

    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    if not text:
        raise json.JSONDecodeError("empty response (after fence strip)", "", 0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if not allow_truncate:
            raise
        # Find the first '{' or '[' and try raw_decode from there.
        # raw_decode finds the first complete JSON value at a given
        # offset and stops at the end of that value, ignoring any
        # leading or trailing content.
        start = -1
        for i, c in enumerate(text):
            if c in "{[":
                start = i
                break
        if start < 0:
            raise
        try:
            obj, _end = json.JSONDecoder().raw_decode(text, idx=start)
            return obj
        except json.JSONDecodeError:
            raise
