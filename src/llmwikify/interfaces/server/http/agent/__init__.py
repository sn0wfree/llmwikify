"""Agent 路由模块。

导入所有子模块以触发路由注册。
"""

from llmwikify.interfaces.server.http.agent import (  # noqa: F401
    config,
    confirmations,
    dream,
    ingest,
    notifications,
    sessions,
    status,
)
