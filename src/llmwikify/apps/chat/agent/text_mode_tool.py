"""Text-mode tool-call parsing — shared between ChatService and ChatReActBridge.

Some LLMs (especially smaller or non-tool-aware ones) emit tool
calls as inline text instead of using the OpenAI-style structured
``tool_calls`` field. The most common pattern is::

    [TOOL_CALL] {tool => "wiki_read_page",
                 args => { --page_name "overview" }} [/TOOL_CALL]

We detect and execute these blocks the same way as native tool
calls, suppressing the leaked markup from the user-visible stream.

This module was extracted from ``service.py`` so that both
``ChatService`` and ``ChatReActBridge`` can share the same
parsing logic.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

TOOL_CALL_RE = re.compile(
    r"\[TOOL_CALL\]\s*(.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL,
)

MINIMAX_TOOL_CALL_RE = re.compile(
    r"<minimax:tool_call>\s*(.*?)\s*</minimax:tool_call>",
    re.DOTALL,
)

MINIMAX_INVOKE_RE = re.compile(
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>\s*(.*?)\s*</invoke>",
    re.DOTALL,
)

MINIMAX_PARAM_RE = re.compile(
    r"<parameter\s+name=[\"']([^\"']+)[\"']\s*>\s*(.*?)\s*</parameter>",
    re.DOTALL,
)


def _unquote(s: str) -> str:
    """Strip a single layer of matching surrounding quotes."""
    if len(s) >= 2 and (
        (s.startswith('"') and s.endswith('"'))
        or (s.startswith("'") and s.endswith("'"))
    ):
        return s[1:-1]
    return s


def parse_perl_args(body: str) -> dict[str, str]:
    """Parse a Perl-style ``{key => value, ...}`` hash into a dict.

    Supports::
        tool => "wiki_read_page"
        "page_name" => "overview"
        --page_name "overview"
    """
    out: dict[str, str] = {}
    s = body.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    for part in re.split(r",\s*", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"--(\w+)\s+(.+)$", part, re.DOTALL)
        if m:
            out[m.group(1)] = _unquote(m.group(2).strip())
            continue
        m = re.match(
            r'(?:"(\w+)"|(\w+))\s*=>\s*(.+)$',
            part,
            re.DOTALL,
        )
        if m:
            key = m.group(1) or m.group(2)
            val = m.group(3).strip().rstrip(",").strip()
            out[key] = _unquote(val)
    return out


def _extract_args_block(body: str) -> dict[str, str]:
    """Find ``args => { ... }`` in ``body`` and parse the inner hash.

    Counts nested braces so we capture the full inner hash even when
    argument values themselves contain braces. Returns an empty dict
    if no ``args =>`` block is found.
    """
    m = re.search(r"args\s*=>\s*\{", body)
    if not m:
        return {}
    start = m.end()
    depth = 1
    i = start
    in_str: str | None = None
    while i < len(body):
        ch = body[i]
        if in_str:
            if ch == "\\" and i + 1 < len(body):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return parse_perl_args(body[start:i])
        i += 1
    return {}


def _normalize_tool_name(tool_name: str) -> str:
    if tool_name == "autoresearch_compound":
        return "autoresearch_compound_run"
    return tool_name


def parse_minimax_tool_call(body: str) -> tuple[str, dict[str, str]] | None:
    m = MINIMAX_INVOKE_RE.search(body)
    if not m:
        return None
    tool_name = _normalize_tool_name(m.group(1).strip())
    args = {
        key.strip(): value.strip()
        for key, value in MINIMAX_PARAM_RE.findall(m.group(2))
    }
    if tool_name == "autoresearch_compound_run" and "question" not in args and "topic" in args:
        args["question"] = args["topic"]
    return tool_name, args


def parse_text_tool_call(body: str) -> tuple[str, dict[str, str]] | None:
    """Extract ``(tool_name, args)`` from a text-mode tool-call block.

    Returns ``None`` if the body is not a recognisable tool-call form,
    in which case the caller should pass the text through verbatim.
    """
    minimax = parse_minimax_tool_call(body)
    if minimax is not None:
        return minimax
    m = re.search(r'tool\s*=>\s*"([^"]+)"', body)
    if not m:
        return None
    tool_name = _normalize_tool_name(m.group(1).strip())
    args = _extract_args_block(body)
    return tool_name, args


class TextModeParser:
    """Stateful parser for [TOOL_CALL] blocks that may straddle
    multiple LLM stream chunks.

    Mirrors the behavior of ``ChatService._stream_preprocess`` /
    ``_reset_text_mode_buffer`` so the bridge produces the same
    event sequence as ``aask_with_tools``.

    Usage::

        parser = TextModeParser()
        async for event in parser.feed(event):
            yield event
        # at end of stream, flush any remaining buffer
        for ev in parser.flush():
            yield ev
    """

    def __init__(self) -> None:
        self._buffer: str = ""

    def reset(self) -> None:
        """Reset the buffer."""
        self._buffer = ""

    async def feed(self, event: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Process a single LLM stream event and yield 0+ output events.

        For ``content`` events, the buffer is searched for
        ``[TOOL_CALL]...[/TOOL_CALL]`` blocks. Any prefix text is
        yielded as ``content`` and any parsed block is yielded as
        ``tool_call``.

        For non-content events, the remaining buffer (if any) is
        flushed as a single ``content`` event before the event
        itself is yielded.
        """
        if event.get("type") != "content":
            if self._buffer and event.get("type") in (
                "done", "thinking", "tool_call", "error",
            ):
                yield {"type": "content", "text": self._buffer}
                self._buffer = ""
            yield event
            return

        import json

        chunk = event.get("text", "")
        self._buffer += chunk
        while True:
            matches = [
                m for m in (
                    TOOL_CALL_RE.search(self._buffer),
                    MINIMAX_TOOL_CALL_RE.search(self._buffer),
                )
                if m is not None
            ]
            if not matches:
                break
            m = min(matches, key=lambda match: match.start())
            prefix = self._buffer[: m.start()]
            if prefix:
                yield {"type": "content", "text": prefix}
            body = m.group(1)
            parsed = parse_text_tool_call(body)
            if parsed is None:
                yield {"type": "content", "text": m.group(0)}
            else:
                tool_name, args = parsed
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": json.dumps(args, ensure_ascii=False),
                }
            self._buffer = self._buffer[m.end():]

    def flush(self) -> list[dict[str, Any]]:
        """Flush any remaining buffered text as a single content event."""
        if not self._buffer:
            return []
        ev: dict[str, Any] = {"type": "content", "text": self._buffer}
        self._buffer = ""
        return [ev]


__all__ = [
    "TOOL_CALL_RE",
    "MINIMAX_TOOL_CALL_RE",
    "parse_minimax_tool_call",
    "parse_text_tool_call",
    "parse_perl_args",
    "TextModeParser",
]
