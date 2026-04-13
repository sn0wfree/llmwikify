"""Core wiki functionality."""

from .wiki import Wiki
from .index import WikiIndex
from .query_sink import QuerySink

__all__ = ["Wiki", "WikiIndex", "QuerySink"]
