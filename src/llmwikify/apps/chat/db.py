"""Backward-compat shim: ChatDatabase 已移至 apps/chat_db.py.

ChatDatabase 被 chat / research / apps.db 共用（三个 DB facade 共用
一个 SQLite 文件），放在 ``apps/chat/`` 里会造成 apps 子包间的横向
依赖。它现在是 apps 级的共享包（与 ``db_base.py`` / ``wiki_db.py``
同级）。

新代码应直接:
    from llmwikify.apps.chat_db import ChatDatabase
"""

from llmwikify.apps.chat_db import *  # noqa: F403
from llmwikify.apps.chat_db import ChatDatabase, get_chat_db_path

__all__ = ["ChatDatabase", "get_chat_db_path"]
