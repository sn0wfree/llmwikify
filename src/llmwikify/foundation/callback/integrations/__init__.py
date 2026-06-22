"""Hook integrations shipped with the callback foundation."""

from llmwikify.foundation.callback.integrations.auto_ingest import AutoIngestHook
from llmwikify.foundation.callback.integrations.dream import WikiDreamSyncHook
from llmwikify.foundation.callback.integrations.wiki import WikiHook

__all__ = ["AutoIngestHook", "WikiDreamSyncHook", "WikiHook"]
