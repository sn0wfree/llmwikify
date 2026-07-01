# llmwikify 旧示例（DEPRECATED）

> **保留原因**：v0.30 之前的零散示例仍对部分老用户有用。**新用户请用
> 上一级目录的 5 个端到端剧本（01-05）**。
>
> 保留时间：v0.38 之后至少 2 个 minor 版本（v0.40 之后考虑删除）。

## 迁移对照表

| 旧文件 | 迁移到 | 何时删 |
|---|---|---|
| `basic_usage.py` | [`../01_personal_reading_notes/`](../01_personal_reading_notes/) | v0.40 |
| `run_server.py` | [`../03_multi_wiki_registry/`](../03_multi_wiki_registry/) + [`../04_chat_sse_client/`](../04_chat_sse_client/) | v0.40 |
| `mcp_agent.py` | [`../04_chat_sse_client/`](../04_chat_sse_client/) | v0.40 |
| `integrate_with_django.py` | （保留参考用） | v0.42 |
| `integrate_with_flask.py` | （保留参考用） | v0.42 |
| `Dockerfile.example` | （保留参考用） | v0.42 |
| `docker-compose.yml.example` | （保留参考用） | v0.42 |

## 关键 API 变更（迁移必看）

| v0.13 写法 | v0.38 写法 |
|---|---|
| `from llmwikify import Wiki, MCPServer` | `from llmwikify import Wiki` |
| `MCPServer(wiki).serve()` | `WikiServer(wiki, enable_mcp=True).run()` 或 CLI `llmwikify serve` |
| `MCPServer(wiki, config={...})` | `WikiServer(wiki, **config)` |
| `from llmwikify.server import WikiServer` | `from llmwikify.interfaces.server import WikiServer` |
| `from llmwikify.mcp import create_mcp_server` | `from llmwikify.interfaces.mcp import create_mcp_server` |
| `llmwikify mcp --transport stdio` | `llmwikify serve --transport stdio` |
| `./llmwikify.py build-index` | `llmwikify build-index` |

详见 [docs/MCP_SETUP.md §Breaking changes](../../docs/MCP_SETUP.md) 与
[docs/CONFIGURATION_GUIDE.md §server](../../docs/CONFIGURATION_GUIDE.md#7-server-unified-server--mcp--rest--webui)。
