"""Backward-compat shim: watcher was moved to
``llmwikify.kernel.storage.watcher`` in Batch B3.

The public class is now ``FileSystemWatcher``; the old
``WikiWatcher`` alias is preserved here for backward compat.
"""
from llmwikify.kernel.storage.watcher import *  # noqa: F401, F403
from llmwikify.kernel.storage.watcher import FileSystemWatcher as WikiWatcher  # noqa: F401
