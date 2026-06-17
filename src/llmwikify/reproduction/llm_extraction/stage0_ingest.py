"""Stage 0: Ingest PDF/source → parsed.md (MarkItDown output).

Wraps ``foundation.extractors.extract()`` to:
1. Detect format (PDF/DOCX/URL/...) via MarkItDown dispatcher
2. Save the extracted text to ``quant/papers/{id}/parsed.md``
3. Return a ``Stage0Result`` with text + metadata for downstream stages

The persisted ``parsed.md`` is the single source of truth for subsequent
LLM calls (Stage 1, Stage 2) so re-runs don't need to re-parse the PDF.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.foundation.extractors import extract

logger = logging.getLogger(__name__)


@dataclass
class Stage0Result:
    """Output of Stage 0 ingestion."""

    paper_id: str
    source_path: Path
    parsed_md_path: Path
    text: str
    title: str
    source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    char_count: int = 0
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "source_path": str(self.source_path),
            "parsed_md_path": str(self.parsed_md_path),
            "title": self.title,
            "source_type": self.source_type,
            "metadata": self.metadata,
            "char_count": self.char_count,
            "content_hash": self.content_hash,
        }


def _slugify_paper_id(name: str) -> str:
    """Convert PDF filename to a stable paper_id."""
    base = Path(name).stem
    base = re.sub(r"[^\w\-]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    return base or "paper"


def _content_hash(text: str) -> str:
    """Stable hash for cache invalidation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def run_stage0_ingest(
    source: str | Path,
    output_root: Path,
    paper_id: str | None = None,
    force_reparse: bool = False,
) -> Stage0Result:
    """Run Stage 0: extract source → parsed.md.

    Args:
        source: PDF file path (absolute).
        output_root: ``quant/papers/`` directory.
        paper_id: Override ID; default = slugified filename stem.
        force_reparse: If True, re-extract even if parsed.md exists.

    Returns:
        Stage0Result with text + path to parsed.md.

    Raises:
        FileNotFoundError: source does not exist.
        RuntimeError: extraction produced no text.
    """
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    pid = paper_id or _slugify_paper_id(source_path.name)
    work_dir = output_root / pid
    work_dir.mkdir(parents=True, exist_ok=True)
    parsed_md_path = work_dir / "parsed.md"

    if parsed_md_path.exists() and not force_reparse:
        text = parsed_md_path.read_text(encoding="utf-8")
        logger.info("[stage0] cache hit: %s (%d chars)", parsed_md_path, len(text))
        return Stage0Result(
            paper_id=pid,
            source_path=source_path,
            parsed_md_path=parsed_md_path,
            text=text,
            title=source_path.stem,
            source_type="pdf",
            metadata={"cached": True},
            char_count=len(text),
            content_hash=_content_hash(text),
        )

    logger.info("[stage0] extracting: %s", source_path)
    result = extract(str(source_path), wiki_root=None)

    if result.source_type == "error" or not result.text:
        raise RuntimeError(
            f"Extraction failed: {result.metadata.get('error', 'no text')}"
        )

    parsed_md_path.write_text(result.text, encoding="utf-8")
    logger.info(
        "[stage0] saved: %s (%d chars, %s)",
        parsed_md_path, len(result.text), result.source_type,
    )

    return Stage0Result(
        paper_id=pid,
        source_path=source_path,
        parsed_md_path=parsed_md_path,
        text=result.text,
        title=result.title or source_path.stem,
        source_type=result.source_type,
        metadata=dict(result.metadata),
        char_count=len(result.text),
        content_hash=_content_hash(result.text),
    )
