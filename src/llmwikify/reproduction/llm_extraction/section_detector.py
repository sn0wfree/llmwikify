"""Stage 1 Call 1: LLM-based section detection.

Given a parsed text, ask the LLM to identify the structural sections
(introduction, methodology, results, ...) and return their absolute
character positions. This replaces the local heuristic approach in
``wiki.ingest.extract_section_metadata`` (which only matches markdown
``#`` headings and is useless for PDF text).

Failure handling: if the LLM call fails or returns unparseable output,
caller falls back to a "no sections" mode (Stage 2 uses full text
slicing instead of ``targeted_read``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment

from ..common.llm_factory import build_default_client
from .retry import DeferError, RetryConfig, with_retry

logger = logging.getLogger(__name__)

_jinja_env = Environment(loader=BaseLoader(), trim_blocks=True, lstrip_blocks=True)

PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "foundation"
    / "prompts"
    / "_defaults"
    / "repro_extract_section.yaml"
)

API_PARAM_KEYS = {"temperature", "max_tokens", "top_p", "top_k"}


@with_retry(stage="stage1_call1", config=RetryConfig(max_attempts=3, backoff_base=0.5))
def _call_llm_with_retry(client: Any, messages: list, **api_params: Any) -> str:
    """Thin wrapper around ``client.chat`` with L1 retry."""
    return client.chat(messages, **api_params)


@dataclass
class Section:
    """A single detected section in the paper."""

    id: int
    title: str
    level: int
    char_start: int
    char_end: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SectionDetectionResult:
    """Output of Stage 1 Call 1."""

    paper_id: str
    sections: list[Section] = field(default_factory=list)
    n_sections: int = 0
    raw_response: str = ""
    cost_tokens: int = 0
    latency_ms: int = 0
    success: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "sections": [s.to_dict() for s in self.sections],
            "n_sections": self.n_sections,
            "cost_tokens": self.cost_tokens,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
        }


def _load_prompt() -> tuple[str, str, dict[str, Any]]:
    """Load section detector prompt template."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt not found: {PROMPT_PATH}")
    import yaml
    raw = yaml.safe_load(PROMPT_PATH.read_text(encoding="utf-8"))
    return raw.get("system", ""), raw.get("user", ""), raw.get("params", {})


def _extract_json(text: str) -> dict | None:
    """Extract and parse JSON from LLM response, with truncation repair."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        # Try a simple repair: close open braces/brackets at last complete position
        candidate = match.group()
        opens_b, opens_s = 0, 0
        in_str = False
        esc = False
        for ch in candidate:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if not in_str:
                if ch == "{":
                    opens_b += 1
                elif ch == "}":
                    opens_b -= 1
                elif ch == "[":
                    opens_s += 1
                elif ch == "]":
                    opens_s -= 1
        if opens_b > 0 or opens_s > 0:
            candidate = candidate.rstrip(",\n ") + "]" * opens_s + "}" * opens_b
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


def _parse_sections(data: dict, text_len: int) -> list[Section]:
    """Parse and validate section list from LLM JSON output."""
    raw_sections = data.get("sections", [])
    sections: list[Section] = []
    seen_ids: set[int] = set()
    for i, item in enumerate(raw_sections, start=1):
        try:
            sid = int(item.get("id", i))
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            level = max(1, min(3, int(item.get("level", 1))))
            char_start = max(0, int(item.get("char_start", 0)))
            char_end = min(text_len, int(item.get("char_end", char_start)))
            if char_end <= char_start:
                continue
            sections.append(Section(
                id=sid, title=title, level=level,
                char_start=char_start, char_end=char_end,
            ))
        except (ValueError, TypeError):
            continue
    sections.sort(key=lambda s: s.char_start)
    for new_id, s in enumerate(sections, start=1):
        s.id = new_id
    return sections


def detect_sections(
    paper_id: str,
    parsed_text: str,
    llm_client: Any | None = None,
) -> SectionDetectionResult:
    """Run Stage 1 Call 1: detect sections via LLM.

    Args:
        paper_id: Stable paper identifier.
        parsed_text: Full text from Stage 0 (MarkItDown output).
        llm_client: Optional pre-built LLM client. If None, builds default.

    Returns:
        SectionDetectionResult with success flag and parsed sections.
        On failure, ``success=False`` and ``error`` set; caller decides
        whether to fall back to "no sections" mode.
    """
    if not parsed_text or not parsed_text.strip():
        return SectionDetectionResult(
            paper_id=paper_id, success=False, error="empty_parsed_text",
        )

    system_text, user_template, params = _load_prompt()
    client = llm_client or build_default_client()

    tmpl = _jinja_env.from_string(user_template)
    user_msg = tmpl.render(
        paper_id=paper_id,
        char_count=len(parsed_text),
        paper_text=parsed_text,
    )

    api_params = {k: v for k, v in params.items() if k in API_PARAM_KEYS}
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_msg},
    ]

    logger.info(
        "[section_detector] paper=%s text_len=%d max_tokens=%s",
        paper_id, len(parsed_text), api_params.get("max_tokens"),
    )
    import time
    t0 = time.monotonic()
    try:
        response = _call_llm_with_retry(client, messages, **api_params)
    except DeferError:
        raise
    except Exception as exc:
        logger.warning("[section_detector] paper=%s LLM call failed: %s", paper_id, exc)
        return SectionDetectionResult(
            paper_id=paper_id, success=False, error=f"llm_error: {exc}",
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    data = _extract_json(response)
    if not data:
        logger.warning(
            "[section_detector] paper=%s JSON parse failed, response_len=%d",
            paper_id, len(response),
        )
        return SectionDetectionResult(
            paper_id=paper_id, raw_response=response[:1000],
            latency_ms=latency_ms, success=False, error="json_parse_failed",
        )

    sections = _parse_sections(data, len(parsed_text))
    if not sections:
        return SectionDetectionResult(
            paper_id=paper_id, raw_response=response[:1000],
            latency_ms=latency_ms, success=False, error="no_valid_sections",
        )

    logger.info(
        "[section_detector] paper=%s detected %d sections (latency=%dms)",
        paper_id, len(sections), latency_ms,
    )
    return SectionDetectionResult(
        paper_id=paper_id,
        sections=sections,
        n_sections=len(sections),
        raw_response=response[:1000],
        latency_ms=latency_ms,
        success=True,
    )
