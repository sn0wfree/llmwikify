"""Backward-compat shim: remote_wiki was moved to
``llmwikify.kernel.multi_wiki.remote`` in Batch B3."""
from llmwikify.kernel.multi_wiki.remote import *  # noqa: F401, F403
from llmwikify.kernel.multi_wiki.remote import RemoteWiki  # noqa: F401
