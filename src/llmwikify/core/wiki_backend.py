"""Backward-compat shim: wiki_backend was moved to
``llmwikify.kernel.storage.backend`` in Batch B3."""
from llmwikify.kernel.storage.backend import *  # noqa: F401, F403
from llmwikify.kernel.storage.backend import LocalFileBackend, WikiBackend  # noqa: F401
