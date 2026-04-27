"""QMD (Query Markdown Documents) MCP HTTP Client.

Provides access to QMD hybrid search engine via its MCP HTTP endpoint.

QMD is a local hybrid search engine that combines:
- Full-text search (BM25 via SQLite FTS5)
- Semantic vector search (embedding models)
- LLM reranking
- Query expansion

See: https://github.com/tobilu/qmd
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class QmdClient:
    """Client for QMD MCP HTTP server.

    Connects to a running QMD MCP server to perform hybrid search.

    Usage:
        client = QmdClient(host="127.0.0.1", port=8181)
        results = client.search("knowledge architecture", limit=10)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8181, timeout: int = 30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"

    def is_available(self) -> bool:
        """Check if QMD server is running and accessible."""
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
            return response.status_code == 200
        except Exception:
            return False

    def health(self) -> dict[str, Any]:
        """Get QMD server health status."""
        try:
            import httpx
            response = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            return {"status": "error", "code": response.status_code}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def search(
        self,
        query: str,
        limit: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Perform hybrid search using QMD.

        Args:
            query: Search query string
            limit: Maximum number of results
            mode: Search mode - "hybrid" (default), "lexical", or "semantic"

        Returns:
            List of search results with keys:
                - page_name: Name of the page
                - snippet: Highlighted text snippet
                - score: Combined search score (0-1, higher is better)
                - mode: Search mode used for this result
        """
        try:
            import httpx
            response = httpx.post(
                f"{self.base_url}/tools/qmd_search",
                json={
                    "query": query,
                    "limit": limit,
                    "mode": mode,
                },
                timeout=self.timeout,
            )
            if response.status_code == 200:
                data = response.json()
                return self._normalize_results(data.get("content", []))
            logger.warning("QMD search failed: %s", response.status_code)
            return []
        except Exception as e:
            logger.debug("QMD search error: %s", e)
            return []

    def _normalize_results(self, results: list[dict]) -> list[dict]:
        """Normalize QMD results to match WikiIndex format."""
        normalized = []
        for result in results:
            # Handle different QMD response formats
            page_name = result.get("page_name") or result.get("filename") or result.get("title") or "Unknown"
            snippet = result.get("snippet") or result.get("content") or result.get("text") or ""
            score = result.get("score") or result.get("relevance") or 0.0

            normalized.append({
                "page_name": page_name,
                "snippet": snippet,
                "score": float(score),
                "mode": "qmd_hybrid",
            })
        return normalized

    def embed(self, collection: str | None = None) -> dict[str, Any]:
        """Trigger embedding generation for the collection.

        Returns:
            Status information about the embedding operation
        """
        try:
            import httpx
            payload = {}
            if collection:
                payload["collection"] = collection
            response = httpx.post(
                f"{self.base_url}/tools/qmd_embed",
                json=payload,
                timeout=self.timeout * 10,  # Longer timeout for embedding
            )
            if response.status_code == 200:
                data = response.json()
                return {"status": "success", "result": data.get("content", {})}
            return {"status": "error", "code": response.status_code}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_install_guide(self) -> str:
        """Return installation instructions for QMD."""
        return """
📦 QMD (Query Markdown Documents) Setup Guide

QMD is a local hybrid search engine that provides enhanced semantic search.

🔧 Installation:

1. Install QMD via npm:
   npm install -g @tobilu/qmd

2. Initialize QMD in your wiki root:
   cd /path/to/wiki
   qmd init

3. Add your markdown files:
   qmd add wiki/

4. Generate embeddings (downloads ~2GB models on first run):
   qmd embed

5. Start the MCP server (default port: 8181):
   qmd mcp --http --port 8181

💡 Usage:
   - In llmwikify config: search.backend: "qmd"
   - CLI: llmwikify search "query" --backend qmd
   - API: GET /api/wiki/search?q=query&backend=qmd

📚 Resources:
   - GitHub: https://github.com/tobilu/qmd
   - MCP Protocol: https://modelcontextprotocol.io/
        """.strip()
