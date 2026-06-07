"""Multi-wiki registry, instances, discovery, and remote access.

The ``multi_wiki`` subpackage supports managing multiple wikis
from a single Python process:

- ``registry``: a ``WikiRegistry`` keyed by wiki name; the
  central entry point.
- ``instance``: a per-wiki handle with status, type, and
  metadata.
- ``discovery``: filesystem discovery of wikis under a common
  root.
- ``remote``: an HTTP-backed ``RemoteWiki`` for accessing a
  wiki running on another host.
"""
from .discovery import WikiDiscovery
from .instance import WikiInstance, WikiStatus, WikiType
from .registry import WikiRegistry
from .remote import RemoteWiki

__all__ = [
    "WikiRegistry",
    "WikiInstance",
    "WikiType",
    "WikiStatus",
    "WikiDiscovery",
    "RemoteWiki",
]
