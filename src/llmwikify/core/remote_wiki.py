"""RemoteWiki - HTTP client for remote llmwikify servers."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class RemoteWiki:
    """HTTP client for remote llmwikify server.

    Provides methods to interact with a remote llmwikify instance,
    mirroring the local Wiki API for seamless multi-wiki support.
    """

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        """Initialize RemoteWiki client.

        Args:
            url: Base URL of the remote llmwikify server
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        """Get or create requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.verify = self.verify_ssl
        return self._session

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with optional auth."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make HTTP request to remote server.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/api/wiki/status")
            **kwargs: Additional arguments for requests

        Returns:
            JSON response as dict or list

        Raises:
            ConnectionError: If remote server is unreachable
            TimeoutError: If request times out
        """
        session = self._get_session()
        url = f"{self.url}{path}"
        headers = self._get_headers()

        try:
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise TimeoutError(f"Remote wiki timed out: {self.url}")
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot connect to remote wiki: {self.url} - {e}")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Remote wiki HTTP error: {e}")

    def health(self) -> dict[str, Any]:
        """Check remote server health.

        Returns:
            Health status dict
        """
        return self._request("GET", "/api/wiki/status")

    def get_status(self) -> dict[str, Any]:
        """Get remote wiki status.

        Returns:
            Wiki status dict
        """
        return self._request("GET", "/api/wiki/status")

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search remote wiki.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of search results
        """
        return self._request(
            "GET", "/api/wiki/search", params={"q": query, "limit": limit}
        )

    def read_page(self, page_name: str) -> dict[str, Any]:
        """Read a page from remote wiki.

        Args:
            page_name: Name of the page to read

        Returns:
            Page content dict
        """
        return self._request("GET", f"/api/wiki/page/{page_name}")

    def write_page(self, page_name: str, content: str) -> dict[str, Any]:
        """Write a page to remote wiki.

        Args:
            page_name: Name of the page to write
            content: Page content in markdown

        Returns:
            Response dict
        """
        return self._request(
            "POST", "/api/wiki/page", json={"page_name": page_name, "content": content}
        )

    def get_references(
        self, page_name: str, detail: bool = True
    ) -> dict[str, Any]:
        """Get page references.

        Args:
            page_name: Name of the page
            detail: Whether to include context

        Returns:
            References dict with inbound/outbound links
        """
        return self._request(
            "GET", f"/api/wiki/references/{page_name}", params={"detail": detail}
        )

    def get_graph(self, **kwargs: Any) -> dict[str, Any]:
        """Get graph data from remote wiki.

        Returns:
            Graph visualization data
        """
        return self._request("GET", "/api/wiki/graph", params=kwargs)

    def lint(self, format: str = "brief") -> dict[str, Any]:
        """Run health check on remote wiki.

        Args:
            format: Output format (brief/full/recommendations/json)

        Returns:
            Lint results
        """
        return self._request("GET", "/api/wiki/lint", params={"format": format})

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None
