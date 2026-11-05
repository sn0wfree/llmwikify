"""Backward-compat shim: WikiDatabase 已移至 apps/wiki_db.py.

WikiDatabase 被 chat / agent / research 三个应用共用，放在
``apps/wiki/`` 里会造成 apps 子包间的横向依赖。它现在是 apps 级的
共享模块（与 ``db.py`` / ``db_base.py`` 同级）。

新代码应直接:
    from llmwikify.apps.wiki_db import WikiDatabase
"""

from llmwikify.apps.wiki_db import WikiDatabase

__all__ = ["WikiDatabase"]
