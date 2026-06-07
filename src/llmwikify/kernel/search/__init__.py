"""QMD search backend — the experimental hybrid full-text + vector
index used as an alternative to the SQLite FTS5 index.

The ``search`` subpackage wraps a ``qmd`` binary (if installed)
and exposes a ``QmdClient`` with a simple search interface.
"""
from .qmd_client import QmdClient
from .qmd_index import QmdIndex

__all__ = ["QmdClient", "QmdIndex"]
