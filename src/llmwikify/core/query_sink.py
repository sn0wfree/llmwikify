"""Backward-compat shim: query_sink was moved to
``llmwikify.kernel.storage.query_sink`` in Batch B3."""
from llmwikify.kernel.storage.query_sink import *  # noqa: F401, F403
from llmwikify.kernel.storage.query_sink import QuerySink  # noqa: F401
