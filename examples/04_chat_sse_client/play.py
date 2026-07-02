#!/usr/bin/env python3
"""Chat SSE Client — demonstrates streaming chat with llmwikify server.

Usage:
    1. Start server in another terminal:
        mkdir -p /tmp/demo-wiki && cd /tmp/demo-wiki
        llmwikify init --agent generic
        llmwikify serve --web --port 8765 --auth-token mysecret

    2. Run this script:
        python play.py

    3. Or with custom parameters:
        python play.py http://localhost:8765 mysecret "列出 wiki 里所有的页面"
"""

import json
import sys
import time

import httpx

DEFAULT_BASE_URL = "http://localhost:8765"
DEFAULT_TOKEN = "mysecret"
DEFAULT_MESSAGE = "列出 wiki 里所有的页面"


def stream_chat(base_url: str, token: str, message: str) -> None:
    """Connect to llmwikify server and stream a chat response via SSE."""
    url = f"{base_url}/api/agent/chat"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"session_id": "demo-play", "message": message}

    print(f"🔌 POST {url}")
    print(f"💬 message: '{message}'")
    print()

    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code == 401:
                    print("❌ 401 Unauthorized — check your auth token")
                    return
                if resp.status_code == 403:
                    print("❌ 403 Forbidden — token rejected")
                    return
                if resp.status_code != 200:
                    print(f"❌ HTTP {resp.status_code}")
                    return

                for line in resp.iter_lines():
                    if not line:
                        continue
                    # SSE format: "event: message" or "data: {...}"
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        etype = event.get("type", "?")

                        if etype == "session_created":
                            model = event.get("model", "unknown")
                            sid = event.get("session_id", "?")
                            print(f"🆔 [session_created] session={sid} model={model}")

                        elif etype == "reasoning":
                            text = event.get("text", "")
                            if text:
                                # Print reasoning inline (truncated)
                                snippet = text[:120] + ("..." if len(text) > 120 else "")
                                print(f"💭 [reasoning] {snippet}")

                        elif etype == "phase":
                            phase = event.get("phase", "?")
                            print(f"🔄 [phase] {phase}")

                        elif etype == "tool_call":
                            tool = event.get("tool", "?")
                            args = event.get("args", {})
                            args_str = json.dumps(args, ensure_ascii=False)[:80]
                            print(f"🔧 [tool_call] {tool}({args_str})")

                        elif etype == "confirmation_required":
                            op = event.get("operation", "?")
                            print(f"⚠️  [confirmation_required] {op}")

                        elif etype == "save_warning":
                            reason = event.get("reason", "?")
                            print(f"💾 [save_warning] {reason}")

                        elif etype == "stream_end":
                            stop = event.get("stop_reason", "?")
                            usage = event.get("usage", {})
                            tokens = usage.get("total_tokens", "?")
                            print(f"🏁 [stream_end] stop={stop} tokens={tokens}")

                        elif etype == "error":
                            err = event.get("error", event.get("message", "?"))
                            print(f"❌ [error] {err}")

                        elif etype == "timeout":
                            msg = event.get("message", "timeout")
                            print(f"⏰ [timeout] {msg}")

                        else:
                            print(f"❓ [{etype}] {json.dumps(event, ensure_ascii=False)[:100]}")

                    # SSE comments (heartbeat) are lines starting with ":"
                    elif line.startswith(":"):
                        pass  # heartbeat, ignore

    except httpx.ConnectError:
        print(f"❌ Connection refused — is the server running at {base_url}?")
        print("   Start with: llmwikify serve --web --port 8765 --auth-token mysecret")
    except httpx.TimeoutException:
        print("❌ Request timed out after 60s")
    except KeyboardInterrupt:
        print("\n⏹  Interrupted")


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    token = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TOKEN
    message = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MESSAGE

    stream_chat(base_url, token, message)


if __name__ == "__main__":
    main()
