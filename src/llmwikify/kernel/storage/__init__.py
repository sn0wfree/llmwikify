"""Storage backends, indexing, query sink, and watcher.

The ``storage`` subpackage is the L2 home for everything
related to on-disk persistence:

- ``backend``: the ``WikiBackend`` Protocol and its local-file
  implementation.
- ``index``: the SQLite FTS5 full-text index.
- ``query_sink``: the per-query result sink (the "query cache"
  that holds recent search hits for repeated lookups).
- ``watcher``: a ``watchdog``-based filesystem watcher that
  invalidates the index when wiki files change.
"""
from .backend import LocalFileBackend, WikiBackend
from .index import WikiIndex
from .query_sink import QuerySink
from .watcher import FileSystemWatcher

__all__ = [
    "WikiBackend",
    "LocalFileBackend",
    "WikiIndex",
    "QuerySink",
    "FileSystemWatcher",
]
