"""Core wiki functionality."""

from .index import WikiIndex
from .query_sink import QuerySink
from .wiki import Wiki

__all__ = ["Wiki", "WikiIndex", "QuerySink"]
