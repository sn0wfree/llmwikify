"""Minimal-diff YAML line editing (config hub D3).

Layer: L1 (foundation). Pure text + optional PyYAML for value
serialization only — no round-trip dump of the whole document, so
user comments and key order outside the edited key are preserved
byte-for-byte.

Capabilities (D3):

* scalar key add / delete / update — precise to the line
* nested keys (``search.qmd.port``) — located by indent
* list / dict values — whole-block replace (comments **inside** the
  block are lost; documented limitation)
* YAML anchors (``&``), aliases (``*``), multi-document (``---``) —
  rejected with :class:`YamlEditError`

Write path for callers that need atomicity: :func:`write_text_atomic`
(temp file + ``os.replace`` in the same directory).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "YamlEditError",
    "set_in_yaml",
    "delete_in_yaml",
    "write_text_atomic",
]


class YamlEditError(ValueError):
    """Unsupported YAML construct or unresolvable key path."""


# Key line: optional indent, key, optional space, colon.
_KEY_RE = re.compile(r"^(\s*)([^#\s][^:]*?)\s*:(\s|$)")
# Document markers / anchors / aliases that we refuse to rewrite.
_UNSUPPORTED_RE = re.compile(
    r"(?:^|\s)(?:[&*][\w-]+)|(?:^---\s*$)|(?:^---\s+\S)",
    re.MULTILINE,
)


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via temp file + ``os.replace`` (S3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=".yaml_edit_")
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        Path(tmp).replace(path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _reject_unsupported(text: str) -> None:
    if _UNSUPPORTED_RE.search(text):
        raise YamlEditError(
            "minimal-diff editor does not support YAML anchors, aliases, "
            "or multi-document streams"
        )


def _split_comment(line: str) -> tuple[str, str]:
    """Split ``raw`` into (code_without_trailing_ws, comment_including_hash).

    A ``#`` only starts a comment when preceded by whitespace or at BOL
    (YAML rule); ``port: 8080#x`` stays a value.
    """
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1].isspace():
                return line[:i].rstrip(), line[i:]
    return line.rstrip(), ""


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_key_line(line: str) -> tuple[int, str, str, str] | None:
    """Return (indent, key, after_colon, comment) or None if not a key line."""
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    m = _KEY_RE.match(line)
    if not m:
        return None
    indent_s, key = m.group(1), m.group(2).strip()
    if key.startswith(("'", '"')):
        # Quoted keys are rare in our configs; treat as unsupported path.
        raise YamlEditError(f"quoted YAML keys are not supported: {key!r}")
    colon_at = line.index(":", m.start(2))
    rest = line[colon_at + 1 :]
    code, comment = _split_comment(rest)
    return len(indent_s), key, code, comment


def _find_key(
    lines: list[str], start: int, end: int, indent: int, key: str
) -> int | None:
    """Index of the first ``key:`` line at ``indent`` in ``[start, end)``."""
    i = start
    while i < end:
        parsed = _parse_key_line(lines[i])
        if parsed is not None:
            cur_indent, cur_key, _, _ = parsed
            if cur_indent == indent and cur_key == key:
                return i
        i += 1
    return None


def _block_end(lines: list[str], key_idx: int, key_indent: int) -> int:
    """Exclusive end of the block owned by the key line at ``key_idx``."""
    i = key_idx + 1
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            # Blank line: belongs to the block only if a later non-blank
            # line is still more-indented (or we're still inside).
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j >= n:
                return i  # trailing blanks stay outside
            if _indent_of(lines[j]) > key_indent:
                i = j
                continue
            return i
        if _indent_of(line) > key_indent:
            i += 1
            continue
        return i
    return n


def _sibling_indent(lines: list[str], start: int, end: int, parent_indent: int) -> int:
    """Indent used by existing children of a block (default parent+2)."""
    for i in range(start, end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind = _indent_of(line)
        if ind > parent_indent:
            return ind
    return parent_indent + 2


def _format_inline(value: Any) -> str:
    """Single-line YAML rendering for a scalar / empty container."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        # Prefer plain style when safe; fall back to double quotes.
        if value == "" or value != value.strip() or value[:1] in "@`\"'|&*!>%{}[],#?":
            import json

            return json.dumps(value, ensure_ascii=False)
        if value.lower() in ("null", "true", "false", "yes", "no", "on", "off"):
            import json

            return json.dumps(value, ensure_ascii=False)
        if re.search(r"[:#]\s|^\s|\s$|:\s", value) or value != value.strip():
            import json

            return json.dumps(value, ensure_ascii=False)
        return value
    if isinstance(value, (dict, list)):
        if not value:
            return "{}" if isinstance(value, dict) else "[]"
        raise YamlEditError("use block form for non-empty containers")
    import json

    return json.dumps(value, ensure_ascii=False)


def _format_block(value: Any, indent: str) -> list[str]:
    """Block-form lines for a non-empty dict/list (first line has no key)."""
    import yaml

    dumped = yaml.dump(
        value,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    out: list[str] = []
    for ln in dumped.splitlines():
        out.append(f"{indent}{ln}" if ln.strip() else "")
    return out


def _walk_parent(
    lines: list[str], path: list[str], *, create_missing: bool = False
) -> tuple[int, int, int]:
    """Locate the region that owns the final path segment.

    Returns ``(region_start, region_end, child_indent)`` where the leaf
    key should live. When ``create_missing`` is True, absent intermediate
    keys are appended as empty mapping parents (used by set, not delete).
    """
    if not path:
        raise YamlEditError("empty key path")
    start, end = 0, len(lines)
    indent = 0
    for depth, part in enumerate(path[:-1]):
        idx = _find_key(lines, start, end, indent, part)
        if idx is None:
            if not create_missing:
                raise YamlEditError(
                    f"parent key {'.'.join(path[: depth + 1])!r} not found"
                )
            # Insert an empty parent block at the end of the current region.
            insert_at = end
            # Skip trailing blanks so we insert before them? Keep simple:
            # insert at `end` (exclusive region end).
            lines[insert_at:insert_at] = [f"{' ' * indent}{part}:"]
            idx = insert_at
            end = insert_at + 1
            # Child region for the new empty parent is empty; next level
            # will also create if needed.
            block_end = idx + 1
            child_indent = indent + 2
            start, end = idx + 1, block_end
            indent = child_indent
            continue
        parsed = _parse_key_line(lines[idx])
        assert parsed is not None
        after = parsed[2].strip()
        if after and not after.startswith(("#", "|", ">")):
            if after not in ("{}", "[]"):
                raise YamlEditError(
                    f"cannot descend into inline value for "
                    f"{'.'.join(path[: depth + 1])!r}: {after!r}"
                )
        block_end = _block_end(lines, idx, indent)
        child_indent = _sibling_indent(lines, idx + 1, block_end, indent)
        start, end = idx + 1, block_end
        indent = child_indent
    return start, end, indent


def set_in_yaml(text: str, key: str, value: Any) -> str:
    """Return ``text`` with dotted ``key`` set to ``value`` (minimal diff).

    Args:
        text: Full YAML document.
        key: Dotted path, e.g. ``"search.qmd.port"``.
        value: New value. Non-empty dict/list replaces the whole block.

    Raises:
        YamlEditError: anchors/aliases/multi-doc, quoted keys, missing
            parents, or inline parents that cannot be descended into.
    """
    _reject_unsupported(text)
    path = [p for p in key.split(".") if p]
    if not path:
        raise YamlEditError("empty key path")
    if not text.strip():
        return _bootstrap(text, path, value)

    newline = "\r\n" if "\r\n" in text[:200] else "\n"
    body = text.replace("\r\n", "\n")
    had_trailing_nl = body.endswith("\n")
    lines = body.split("\n")
    if had_trailing_nl and lines and lines[-1] == "":
        lines.pop()

    start, end, indent = _walk_parent(lines, path, create_missing=True)
    leaf = path[-1]
    idx = _find_key(lines, start, end, indent, leaf)

    # Non-empty container → whole-block replace (D3: block comments lost).
    if isinstance(value, (dict, list)) and value:
        new_block = [f"{' ' * indent}{leaf}:"] + _format_block(
            value, " " * (indent + 2)
        )
        if idx is None:
            return _join(
                lines[:end] + new_block + lines[end:], newline, had_trailing_nl
            )
        old_end = _block_end(lines, idx, indent)
        return _join(
            lines[:idx] + new_block + lines[old_end:], newline, had_trailing_nl
        )

    inline = _format_inline(value)
    if idx is None:
        insert = f"{' ' * indent}{leaf}: {inline}"
        return _join(
            lines[:end] + [insert] + lines[end:], newline, had_trailing_nl
        )

    parsed = _parse_key_line(lines[idx])
    assert parsed is not None
    _, _, _, comment = parsed
    code_part = lines[idx].split(":", 1)[0]
    suffix = f"  {comment}" if comment else ""
    lines[idx] = f"{code_part}: {inline}{suffix}"

    # A scalar key must not keep a nested block — drop leftover children.
    child_end = _block_end(lines, idx, indent)
    if child_end > idx + 1 and any(
        lines[j].strip() and _indent_of(lines[j]) > indent
        for j in range(idx + 1, child_end)
    ):
        lines = lines[: idx + 1] + lines[child_end:]
    return _join(lines, newline, had_trailing_nl)


def _bootstrap(text: str, path: list[str], value: Any) -> str:
    """Create a nested document from scratch for an empty file."""
    indent = 0
    parts: list[str] = []
    for p in path[:-1]:
        parts.append(f"{' ' * indent}{p}:")
        indent += 2
    if isinstance(value, (dict, list)) and value:
        parts.append(f"{' ' * indent}{path[-1]}:")
        parts.extend(_format_block(value, " " * (indent + 2)))
    else:
        parts.append(f"{' ' * indent}{path[-1]}: {_format_inline(value)}")
    body = "\n".join(parts) + "\n"
    if text and not text.endswith("\n"):
        return text.rstrip("\r\n") + "\n" + body
    return (text or "") + body


def _join(lines: list[str], newline: str, trailing_nl: bool) -> str:
    body = newline.join(lines)
    if trailing_nl:
        body += newline
    return body


def delete_in_yaml(text: str, key: str) -> str:
    """Return ``text`` with dotted ``key`` (and its block) removed.

    Removing a missing key is a no-op. Parent keys are not auto-pruned.
    """
    _reject_unsupported(text)
    path = [p for p in key.split(".") if p]
    if not path:
        raise YamlEditError("empty key path")
    if not text.strip():
        return text

    newline = "\r\n" if "\r\n" in text[:200] else "\n"
    body = text.replace("\r\n", "\n")
    had_trailing_nl = body.endswith("\n")
    lines = body.split("\n")
    if had_trailing_nl and lines and lines[-1] == "":
        lines.pop()

    start, end, indent = _walk_parent(lines, path)
    leaf = path[-1]
    idx = _find_key(lines, start, end, indent, leaf)
    if idx is None:
        return _join(lines, newline, had_trailing_nl)
    block_end = _block_end(lines, idx, indent)
    # Also swallow one trailing blank that sat inside the block gap.
    return _join(lines[:idx] + lines[block_end:], newline, had_trailing_nl)
