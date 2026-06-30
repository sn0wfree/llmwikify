# 04 — Chat SSE 客户端

> 对应 [docs/TUTORIAL.md §场景 4](../../docs/TUTORIAL.md#场景-4chat--react-agent)

## 跑法（两步）

**步骤 1：另开一个终端，启动 server**

```bash
mkdir -p /tmp/demo-wiki && cd /tmp/demo-wiki
llmwikify init --agent generic
llmwikify serve --web --port 8765 --auth-token mysecret
# 等到出现 "Uvicorn running on http://0.0.0.0:8765"
```

**步骤 2：跑本剧本**

```bash
cd examples/04_chat_sse_client
pip install httpx   # 第一次需要
python play.py
```

预期输出：

```
🔌 POST http://localhost:8765/api/agent/chat
💬 message: '列出 wiki 里所有的页面'

🆔 [session_created] {"session_id": "demo-...", "model": "gpt-4o"}
🔄 [phase] gather
💭 [reasoning] 用户要求列出 wiki 中所有页面...
🔧 [tool_call] wiki_list
💭 [reasoning] 已找到 0 个页面...
🏁 [stream_end] {"stop_reason": "end_turn"}
```

## 自定义参数

```bash
python play.py <base_url> <token> "<message>"
# 例：python play.py http://team-wiki:8765 s3cret "对比腾讯和阿里云"
```

## 涉及 API

| API | 用途 |
|---|---|
| `httpx.stream("POST", url, json=payload)` | SSE 长连接 |
| `r.iter_lines()` | 逐行读 SSE |
| `data: {json}` 解析 | 提取事件 |
| `Authorization: Bearer` | 鉴权 |

## SSE 事件类型一览（v0.38.0）

| 事件 | 触发时机 |
|---|---|
| `session_created` | 首次进入会话 |
| `reasoning` | LLM 思考过程（delta 增量） |
| `phase` | 阶段切换（gather/synthesize/review） |
| `tool_call` | 调 MCP 工具（最多 4 轮） |
| `confirmation_required` | 需人工确认的写操作 |
| `save_warning` | 落盘前的提示 |
| `stream_end` | 流结束，附 usage / stop_reason |
| `error` | LLM 异常 / 工具错误 |

## 对应 TUTORIAL 节

- §4.2 步骤 A/B/C
- §4.3 SSE 事件流
- §4.5 故障排查
