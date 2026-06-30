"""
04 — Chat SSE 客户端

对应 TUTORIAL.md §场景 4
======================

演示：用 httpx 客户端连接 /api/agent/chat 流式接口，打印每个
SSE 事件（reasoning / phase / tool_call / stream_end / save_warning）。

运行条件：需要先在另一个终端启动 server：

    cd /tmp/some-wiki
    llmwikify init --agent generic
    llmwikify serve --web --port 8765 --auth-token mysecret

然后本剧本：

    python play.py http://localhost:8765 mysecret

（不传任何参数 = 走默认；超时 5s 自动退出）
"""

from __future__ import annotations

import json
import sys
import time

import httpx


def stream_chat(base_url: str, token: str, message: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "session_id": f"demo-{int(time.time())}",
        "message": message,
    }

    print(f"🔌 POST {base_url}/api/agent/chat")
    print(f"💬 message: {message!r}\n")

    with httpx.stream(
        "POST", f"{base_url}/api/agent/chat",
        headers=headers, json=payload, timeout=60,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if not data:
                continue
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                print(f"   (raw) {data}")
                continue
            _print_event(evt)


def _print_event(evt: dict) -> None:
    kind = evt.get("type", "?")
    icon = {
        "session_created": "🆔",
        "reasoning": "💭",
        "phase": "🔄",
        "tool_call": "🔧",
        "confirmation_required": "⚠️ ",
        "save_warning": "💾",
        "stream_end": "🏁",
        "error": "❌",
    }.get(kind, "📨")
    detail = (
        evt.get("delta", "")
        or evt.get("description", "")
        or evt.get("name", "")
        or evt.get("reason", "")
        or evt.get("phase", "")
        or json.dumps(evt, ensure_ascii=False)
    )
    print(f"{icon} [{kind}] {str(detail)[:120]}")


def main(argv: list[str]) -> None:
    base_url = argv[1] if len(argv) > 1 else "http://localhost:8765"
    token = argv[2] if len(argv) > 2 else "mysecret"
    message = argv[3] if len(argv) > 3 else "列出 wiki 里所有的页面"

    try:
        stream_chat(base_url, token, message)
    except httpx.HTTPError as e:
        print(f"❌ HTTP error: {e}", file=sys.stderr)
        print("   → server 启动了吗？(--web --port 8765 --auth-token mysecret)",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
