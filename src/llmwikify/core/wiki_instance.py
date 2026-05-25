"""WikiInstance - wraps Wiki with registry metadata for multi-wiki support."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class WikiType(str, Enum):
    """Type of wiki instance."""

    LOCAL = "local"
    REMOTE = "remote"


class WikiStatus(str, Enum):
    """Status of wiki instance."""

    READY = "ready"
    LOADING = "loading"
    ERROR = "error"
    OFFLINE = "offline"  # remote wiki unreachable


@dataclass
class WikiInstance:
    """Wraps a Wiki with registry metadata.

    This dataclass holds metadata about a wiki instance, including
    its ID, name, type (local/remote), and status. The actual Wiki
    object is managed by WikiRegistry and loaded lazily.
    """

    wiki_id: str
    name: str
    wiki_type: WikiType
    root: Path | None  # None for remote wikis
    url: str | None = None  # None for local wikis
    api_key: str | None = None
    is_default: bool = False
    status: WikiStatus = WikiStatus.READY
    page_count: int = 0
    last_accessed: datetime | None = None
    config: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "wiki_id": self.wiki_id,
            "name": self.name,
            "type": self.wiki_type.value,
            "root": str(self.root) if self.root else None,
            "url": self.url,
            "status": self.status.value,
            "page_count": self.page_count,
            "is_default": self.is_default,
            "last_accessed": self.last_accessed.isoformat()
            if self.last_accessed
            else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiInstance:
        """Create WikiInstance from dictionary."""
        root = data.get("root")
        if root and isinstance(root, str):
            root = Path(root)

        last_accessed = data.get("last_accessed")
        if last_accessed and isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)

        return cls(
            wiki_id=data["wiki_id"],
            name=data["name"],
            wiki_type=WikiType(data.get("type", "local")),
            root=root,
            url=data.get("url"),
            api_key=data.get("api_key"),
            is_default=data.get("is_default", False),
            status=WikiStatus(data.get("status", "ready")),
            page_count=data.get("page_count", 0),
            last_accessed=last_accessed,
            config=data.get("config", {}),
            error=data.get("error"),
        )
