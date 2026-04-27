"""QMD Index wrapper for llmwikify.

Integrates QMD hybrid search engine as an optional backend alongside
the default SQLite FTS5 WikiIndex.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


QMD_THRESHOLD = 1000  # Pages after which to recommend QMD


class QmdIndex:
    """QMD hybrid search index wrapper.

    Provides the same interface as WikiIndex for search operations,
    delegating to a QMD MCP server via HTTP.
    """

    def __init__(self, wiki_root: Path, config: dict | None = None):
        self.wiki_root = wiki_root
        self.config = config or {}

        qmd_config = self.config.get("search", {}).get("qmd", {})
        self.host = qmd_config.get("host", "127.0.0.1")
        self.port = qmd_config.get("port", 8181)
        self.auto_start = qmd_config.get("auto_start", False)

        self._client = None
        self._available: bool | None = None  # Cached availability state

    @property
    def client(self):
        """Lazy load QMD client."""
        if self._client is None:
            try:
                from .qmd_client import QmdClient
                self._client = QmdClient(host=self.host, port=self.port)
            except ImportError:
                pass
        return self._client

    def is_available(self, force_check: bool = False) -> bool:
        """Check if QMD is available and running."""
        if self._available is not None and not force_check:
            return self._available

        if self.client is None:
            self._available = False
            return False

        try:
            self._available = self.client.is_available()
        except Exception:
            self._available = False
        return self._available

    def should_recommend(self, page_count: int) -> bool:
        """Determine if QMD should be recommended to the user."""
        if page_count < QMD_THRESHOLD:
            return False
        if self.is_available():
            return False  # Already using QMD
        return True

    def get_recommendation(self, page_count: int) -> dict[str, Any]:
        """Get recommendation message if QMD is recommended."""
        if not self.should_recommend(page_count):
            return {"recommended": False}

        return {
            "recommended": True,
            "page_count": page_count,
            "threshold": QMD_THRESHOLD,
            "message": (
                f"Your wiki has {page_count}+ pages - consider "
                "enabling QMD for enhanced semantic search. "
                "Run `llmwikify qmd install` for setup instructions."
            ),
        }

    def search(
        self,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Perform hybrid search via QMD.

        Args:
            query: Search query
            limit: Max results
            mode: "hybrid", "lexical", or "semantic"

        Returns:
            List of results matching WikiIndex format:
                {page_name, snippet, score, ...}
        """
        if not self.is_available():
            logger.warning("QMD not available, falling back to FTS5")
            return []

        try:
            return self.client.search(query, limit=limit, mode=mode)
        except Exception as e:
            logger.warning("QMD search failed: %s", e)
            return []

    def embed(self) -> dict[str, Any]:
        """Trigger embedding generation for the wiki."""
        if not self.is_available():
            return {"status": "error", "error": "QMD server not available"}

        try:
            return self.client.embed()
        except Exception as e:
            logger.warning("QMD embed failed: %s", e)
            return {"status": "error", "error": str(e)}

    def get_install_guide(self) -> str:
        """Return QMD installation instructions."""
        if self.client:
            return self.client.get_install_guide()
        # Fallback if client not loaded
        try:
            from .qmd_client import QmdClient
            return QmdClient.get_install_guide(QmdClient)
        except Exception:
            return "Could not load QMD installation guide."
