"""WikiRegistry - manages multiple Wiki instances with discovery and lifecycle."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .remote_wiki import RemoteWiki
from .wiki_discovery import WikiDiscovery
from .wiki_instance import WikiInstance, WikiStatus, WikiType

logger = logging.getLogger(__name__)


class WikiRegistry:
    """Manages multiple Wiki instances with discovery and lifecycle.

    This registry provides:
    - Registration/unregistration of wiki instances
    - Lazy loading of Wiki objects
    - Directory scanning for local wikis
    - Remote wiki connection management
    - Cross-wiki search capabilities
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize WikiRegistry.

        Args:
            config: Configuration dict (from .wiki-config.yaml)
        """
        self._config = config
        self._instances: dict[str, WikiInstance] = {}
        self._wiki_objects: dict[str, Any] = {}  # lazy-loaded Wiki objects
        self._remote_clients: dict[str, RemoteWiki] = {}
        self._registry_db: sqlite3.Connection | None = None
        self._default_wiki_id: str | None = None
        self._lock = threading.Lock()

        # Initialize discovery
        discovery_config = config.get("wikis", {}).get("discovery", {})
        self._discovery = WikiDiscovery(
            exclude_patterns=discovery_config.get("exclude_patterns", None)
        )

    def initialize(self) -> None:
        """Initialize registry: load from config, discover local wikis, connect remote."""
        wikis_config = self._config.get("wikis", {})

        # Set default wiki
        self._default_wiki_id = wikis_config.get("default")

        # Register local wikis from config
        local_wikis = wikis_config.get("local", [])
        for wiki_def in local_wikis:
            wiki_id = wiki_def.get("id")
            if not wiki_id:
                continue

            root = wiki_def.get("path", ".")
            if isinstance(root, str):
                root = Path(root).expanduser().resolve()

            self.register_wiki(
                wiki_id=wiki_id,
                name=wiki_def.get("name", wiki_id),
                root=root,
                wiki_type=WikiType.LOCAL,
                is_default=(wiki_id == self._default_wiki_id),
            )

        # Register remote wikis from config
        remote_wikis = wikis_config.get("remote", [])
        for wiki_def in remote_wikis:
            wiki_id = wiki_def.get("id")
            if not wiki_id:
                continue

            self.register_remote(
                wiki_id=wiki_id,
                name=wiki_def.get("name", wiki_id),
                url=wiki_def.get("url", ""),
                api_key=wiki_def.get("api_key"),
                timeout=wiki_def.get("timeout", 30),
                verify_ssl=wiki_def.get("verify_ssl", True),
                is_default=(wiki_id == self._default_wiki_id),
            )

        # Discover local wikis if enabled
        discovery_config = wikis_config.get("discovery", {})
        if discovery_config.get("enabled", False):
            scan_paths = discovery_config.get("scan_paths", ["."])
            scan_depth = discovery_config.get("scan_depth", 2)
            self.scan_directories(scan_paths, scan_depth)

    def close(self) -> None:
        """Close all Wiki instances and registry DB."""
        with self._lock:
            # Close remote clients
            for client in self._remote_clients.values():
                client.close()
            self._remote_clients.clear()

            # Clear wiki objects
            self._wiki_objects.clear()
            self._instances.clear()

            # Close registry DB
            if self._registry_db:
                self._registry_db.close()
                self._registry_db = None

    # --- Wiki Management ---

    def register_wiki(
        self,
        wiki_id: str,
        name: str,
        root: Path,
        wiki_type: WikiType = WikiType.LOCAL,
        is_default: bool = False,
        **kwargs: Any,
    ) -> WikiInstance:
        """Register a new wiki.

        Args:
            wiki_id: Unique identifier for the wiki
            name: Display name
            root: Root directory path (for local wikis)
            wiki_type: Type of wiki (local/remote)
            is_default: Whether this is the default wiki
            **kwargs: Additional metadata

        Returns:
            WikiInstance object
        """
        with self._lock:
            instance = WikiInstance(
                wiki_id=wiki_id,
                name=name,
                wiki_type=wiki_type,
                root=root,
                is_default=is_default,
                status=WikiStatus.READY,
                **kwargs,
            )
            self._instances[wiki_id] = instance

            # Update default if needed
            if is_default:
                self._default_wiki_id = wiki_id
                # Unset default from other wikis
                for other_id, other in self._instances.items():
                    if other_id != wiki_id:
                        other.is_default = False

            logger.info(f"Registered wiki: {wiki_id} ({wiki_type.value})")
            return instance

    def register_remote(
        self,
        wiki_id: str,
        name: str,
        url: str,
        api_key: str | None = None,
        timeout: int = 30,
        verify_ssl: bool = True,
        is_default: bool = False,
        **kwargs: Any,
    ) -> WikiInstance:
        """Register a remote wiki.

        Args:
            wiki_id: Unique identifier for the wiki
            name: Display name
            url: Remote server URL
            api_key: Optional API key
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL
            is_default: Whether this is the default wiki
            **kwargs: Additional metadata

        Returns:
            WikiInstance object
        """
        with self._lock:
            instance = WikiInstance(
                wiki_id=wiki_id,
                name=name,
                wiki_type=WikiType.REMOTE,
                root=None,
                url=url,
                api_key=api_key,
                is_default=is_default,
                status=WikiStatus.READY,
                **kwargs,
            )
            self._instances[wiki_id] = instance

            # Create remote client
            client = RemoteWiki(
                url=url,
                api_key=api_key,
                timeout=timeout,
                verify_ssl=verify_ssl,
            )
            self._remote_clients[wiki_id] = client

            # Update default if needed
            if is_default:
                self._default_wiki_id = wiki_id
                for other_id, other in self._instances.items():
                    if other_id != wiki_id:
                        other.is_default = False

            logger.info(f"Registered remote wiki: {wiki_id} ({url})")
            return instance

    def unregister_wiki(self, wiki_id: str) -> None:
        """Remove wiki from registry.

        Args:
            wiki_id: Wiki to remove

        Raises:
            KeyError: If wiki_id not found
        """
        with self._lock:
            if wiki_id not in self._instances:
                raise KeyError(f"Wiki not found: {wiki_id}")

            # Close remote client if exists
            if wiki_id in self._remote_clients:
                self._remote_clients[wiki_id].close()
                del self._remote_clients[wiki_id]

            # Remove wiki object
            if wiki_id in self._wiki_objects:
                del self._wiki_objects[wiki_id]

            # Remove instance
            del self._instances[wiki_id]

            # Update default if needed
            if self._default_wiki_id == wiki_id:
                self._default_wiki_id = (
                    next(iter(self._instances)) if self._instances else None
                )
                if self._default_wiki_id:
                    self._instances[self._default_wiki_id].is_default = True

            logger.info(f"Unregistered wiki: {wiki_id}")

    def get_wiki(self, wiki_id: str) -> Any:
        """Get Wiki object by ID (lazy-loaded).

        Args:
            wiki_id: Wiki identifier

        Returns:
            Wiki object

        Raises:
            KeyError: If wiki_id not found
        """
        if wiki_id not in self._instances:
            raise KeyError(f"Wiki not found: {wiki_id}")

        # Return cached wiki object if available
        if wiki_id in self._wiki_objects:
            return self._wiki_objects[wiki_id]

        # Lazy-load wiki object
        instance = self._instances[wiki_id]

        if instance.wiki_type == WikiType.REMOTE:
            # Remote wikis don't have local Wiki objects
            raise ValueError(
                f"Cannot get local Wiki object for remote wiki: {wiki_id}"
            )

        # Import here to avoid circular imports
        from .wiki import Wiki

        wiki = Wiki(instance.root)
        self._wiki_objects[wiki_id] = wiki

        # Update page count
        try:
            status = wiki.status()
            instance.page_count = status.get("page_count", 0)
        except Exception as e:
            logger.warning(f"Failed to get status for wiki {wiki_id}: {e}")

        return wiki

    def get_wiki_instance(self, wiki_id: str) -> WikiInstance:
        """Get WikiInstance metadata.

        Args:
            wiki_id: Wiki identifier

        Returns:
            WikiInstance object

        Raises:
            KeyError: If wiki_id not found
        """
        if wiki_id not in self._instances:
            raise KeyError(f"Wiki not found: {wiki_id}")
        return self._instances[wiki_id]

    def list_wikis(self) -> list[WikiInstance]:
        """List all registered wikis.

        Returns:
            List of WikiInstance objects with fresh page_count
        """
        for instance in self._instances.values():
            if instance.wiki_type == WikiType.LOCAL:
                try:
                    status = self.get_wiki_status(instance.wiki_id)
                    instance.page_count = status.get("page_count", 0)
                except Exception:
                    pass
        return list(self._instances.values())

    def get_default_wiki(self) -> Any:
        """Get the default wiki instance.

        Returns:
            Default Wiki object

        Raises:
            ValueError: If no default wiki is set
        """
        if not self._default_wiki_id:
            raise ValueError("No default wiki configured")

        return self.get_wiki(self._default_wiki_id)

    def get_default_wiki_id(self) -> str | None:
        """Get the default wiki ID.

        Returns:
            Default wiki ID or None
        """
        return self._default_wiki_id

    def set_default_wiki(self, wiki_id: str) -> None:
        """Set the default wiki.

        Args:
            wiki_id: Wiki to set as default

        Raises:
            KeyError: If wiki_id not found
        """
        if wiki_id not in self._instances:
            raise KeyError(f"Wiki not found: {wiki_id}")

        with self._lock:
            # Unset current default
            if self._default_wiki_id and self._default_wiki_id in self._instances:
                self._instances[self._default_wiki_id].is_default = False

            # Set new default
            self._default_wiki_id = wiki_id
            self._instances[wiki_id].is_default = True

    # --- Discovery ---

    def scan_directories(
        self, scan_paths: list[str], depth: int = 2
    ) -> list[WikiInstance]:
        """Scan directories for .wiki-config.yaml files.

        Args:
            scan_paths: Directories to scan
            depth: Maximum recursion depth

        Returns:
            List of newly discovered WikiInstance objects
        """
        discovered = self._discovery.scan(scan_paths, depth)
        new_wikis: list[WikiInstance] = []

        for wiki_info in discovered:
            wiki_id = wiki_info["wiki_id"]
            root = wiki_info["root"]

            # Skip if already registered
            if wiki_id in self._instances:
                logger.debug(f"Wiki already registered: {wiki_id}")
                continue

            # Register discovered wiki
            instance = self.register_wiki(
                wiki_id=wiki_id,
                name=wiki_id.replace("-", " ").replace("_", " ").title(),
                root=root,
                wiki_type=WikiType.LOCAL,
            )
            new_wikis.append(instance)

        return new_wikis

    # --- Cross-Wiki Operations ---

    def cross_wiki_search(
        self,
        query: str,
        wiki_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search across multiple wikis, merge and rank results.

        Args:
            query: Search query
            wiki_ids: Specific wikis to search (None = all)
            limit: Results per wiki

        Returns:
            Merged and ranked search results
        """
        results: list[dict[str, Any]] = []

        # Determine which wikis to search
        target_wikis = wiki_ids or list(self._instances.keys())

        for wiki_id in target_wikis:
            instance = self._instances.get(wiki_id)
            if not instance:
                continue

            try:
                if instance.wiki_type == WikiType.REMOTE:
                    # Search remote wiki
                    client = self._remote_clients.get(wiki_id)
                    if client:
                        remote_results = client.search(query, limit)
                        for r in remote_results:
                            r["wiki_id"] = wiki_id
                            r["wiki_name"] = instance.name
                        results.extend(remote_results)
                else:
                    # Search local wiki
                    wiki = self.get_wiki(wiki_id)
                    local_results = wiki.search(query, limit)
                    for r in local_results:
                        r["wiki_id"] = wiki_id
                        r["wiki_name"] = instance.name
                    results.extend(local_results)
            except Exception as e:
                logger.error(f"Search failed for wiki {wiki_id}: {e}")

        # Sort by score (descending)
        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return results

    def get_wiki_status(self, wiki_id: str) -> dict[str, Any]:
        """Get detailed status for a wiki.

        Args:
            wiki_id: Wiki identifier

        Returns:
            Status dict
        """
        instance = self.get_wiki_instance(wiki_id)

        if instance.wiki_type == WikiType.REMOTE:
            client = self._remote_clients.get(wiki_id)
            if client:
                try:
                    return client.get_status()
                except Exception as e:
                    return {"status": "error", "error": str(e)}
            return {"status": "offline"}

        # Local wiki
        wiki = self.get_wiki(wiki_id)
        return wiki.status()

    def reload_wiki(self, wiki_id: str) -> dict[str, Any]:
        """Re-index a wiki (rebuild FTS5).

        Args:
            wiki_id: Wiki identifier

        Returns:
            Reload results
        """
        instance = self.get_wiki_instance(wiki_id)

        if instance.wiki_type == WikiType.REMOTE:
            return {"status": "error", "message": "Cannot reload remote wiki"}

        wiki = self.get_wiki(wiki_id)
        try:
            wiki.build_index()
            return {"status": "success", "message": f"Wiki {wiki_id} re-indexed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
