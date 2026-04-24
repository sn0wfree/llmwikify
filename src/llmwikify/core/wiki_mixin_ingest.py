"""Wiki ingest mixin — source file ingestion, extraction, raw collection."""

import logging
import re
from pathlib import Path

from ..extractors import extract

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiIngestMixin(WikiProtocol):
    """Source ingestion: extract, save to raw/, return data for LLM processing."""

    def ingest_source(self, source: str) -> dict:
        """Ingest a source file and return extracted data for LLM processing.

        Does NOT automatically write wiki pages. Returns extracted content
        along with current wiki index so the LLM can decide which pages
        to create/update and how to cross-reference.

        All source files are collected into raw/ for centralized management.
        - URL/YouTube: extracted text is saved to raw/
        - Local files outside raw/: copied to raw/
        - Local files already in raw/: no copy needed
        """
        result = extract(source, wiki_root=self.root)

        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error")}

        if not result.text:
            return {"error": "No content extracted"}

        saved_to_raw = False
        already_exists = False
        hint = ""
        source_name = ""

        self.raw_dir.mkdir(parents=True, exist_ok=True)

        if result.source_type in ("url", "youtube"):
            safe_name = self._slugify(result.title) + ".md"
            saved_path = self.raw_dir / safe_name

            if saved_path.exists():
                already_exists = True
                source_name = safe_name
                hint = f"Source already exists in raw/{safe_name}"
            else:
                saved_path.write_text(result.text)
                saved_to_raw = True
                source_name = safe_name
                hint = f"Extracted text saved to raw/{safe_name}"
        else:
            original_path = Path(source).resolve()
            try:
                original_path.relative_to(self.raw_dir.resolve())
                source_name = str(original_path.relative_to(self.raw_dir))
                saved_to_raw = False
                hint = f"Source is already in raw/{source_name}"
            except ValueError:
                safe_name = self._slugify(result.title or original_path.stem) + original_path.suffix
                saved_path = self.raw_dir / safe_name

                if saved_path.exists():
                    already_exists = True
                    source_name = safe_name
                    hint = f"Source already exists in raw/{safe_name}"
                else:
                    saved_path.write_bytes(original_path.read_bytes())
                    saved_to_raw = True
                    source_name = safe_name
                    hint = f"Source copied to raw/{safe_name} from {original_path}"

        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()

        log_detail = f"Source ({result.source_type}): {result.title}"
        if saved_to_raw:
            log_detail += f" → raw/{source_name}"
        self.append_log("ingest", log_detail)

        raw_file = self.raw_dir / source_name
        file_size = 0
        word_count = 0
        has_images = False
        image_count = 0

        if raw_file.exists():
            file_size = raw_file.stat().st_size
            word_count = len(result.text.split()) if result.text else 0
            image_refs = re.findall(r'!\[.*?\]\((.*?)\)', result.text or '')
            image_count = len(image_refs)
            has_images = image_count > 0

        return {
            "source_name": source_name,
            "source_raw_path": f"raw/{source_name}",
            "source_type": result.source_type,
            "file_type": self._detect_file_type(source_name),
            "file_size": file_size,
            "word_count": word_count,
            "has_images": has_images,
            "image_count": image_count,
            "text_extracted": bool(result.text),
            "title": result.title,
            "content_preview": (result.text or "")[:200],
            "content": result.text,
            "content_length": len(result.text),
            "metadata": result.metadata,
            "saved_to_raw": saved_to_raw,
            "already_exists": already_exists,
            "hint": hint,
            "current_index": index_content,
            "message": "Source ingested. Read the file to extract key takeaways.",
            "instructions": self._get_prompt_registry().render_text("ingest_instructions"),
        }
