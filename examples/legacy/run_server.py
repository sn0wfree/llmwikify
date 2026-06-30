"""
DEPRECATED — 保留用于向后兼容。

迁移路径：
  旧 `from llmwikify.interfaces.server import WikiServer`  →  `from llmwikify.interfaces.server import WikiServer`
  旧 `MCPServer(wiki).serve()`                →  `llmwikify serve` CLI

推荐示例：../04_chat_sse_client/  (SSE chat) 与 ../03_multi_wiki_registry/  (server 启动)

llmwikify Web 服务器示例

演示：
1. 启动统一 FastAPI 服务器
2. MCP 协议集成
3. REST API 使用
4. API Key 认证配置
"""

import sys
from pathlib import Path

# 添加 src 到路径（如果直接运行示例）
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def example_1_basic_server():
    """示例 1：基础服务器"""
    print("=" * 60)
    print("示例 1：基础服务器")
    print("=" * 60)

    from llmwikify import Wiki, create_wiki
    from llmwikify.interfaces.server import WikiServer

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 创建服务器
        server = WikiServer(
            wiki,
            enable_mcp=True,       # 启用 MCP 协议
            enable_rest=True,       # 启用 REST API
            enable_webui=False,     # 禁用 Web UI（需要前端构建）
        )

        print(f"✓ WikiServer 已创建")
        print(f"  FastAPI App: {type(server.app)}")
        print(f"  MCP 端点: /mcp")
        print(f"  API 文档: /docs")
        print(f"  ReDoc: /redoc")
        print("\n⚠️ 此示例仅演示创建，不实际启动服务器")


def example_2_with_auth():
    """示例 2：带 API Key 认证的服务器"""
    print("\n" + "=" * 60)
    print("示例 2：带 API Key 认证")
    print("=" * 60)

    from llmwikify import Wiki, create_wiki
    from llmwikify.interfaces.server import WikiServer

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 创建带 API Key 认证的服务器
        api_key = "my-secret-key-123"
        server = WikiServer(
            wiki,
            api_key=api_key,
            enable_mcp=True,
            enable_rest=True,
            enable_webui=False,
        )

        print(f"✓ 带认证的服务器已创建")
        print(f"  API Key: {api_key}")
        print("\n使用方式:")
        print(f"  curl -H 'Authorization: Bearer {api_key}' "
              "http://localhost:8765/api/wiki/status")


def example_3_mcp_only():
    """示例 3：仅 MCP 模式"""
    print("\n" + "=" * 60)
    print("示例 3：仅 MCP 模式")
    print("=" * 60)

    from llmwikify import Wiki, create_wiki
    from llmwikify.interfaces.server import WikiServer

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 仅启用 MCP
        server = WikiServer(
            wiki,
            enable_mcp=True,
            enable_rest=False,
            enable_webui=False,
        )

        print(f"✓ MCP-only 服务器已创建")
        print("  适合与 AI Agent 集成")
        print("  通过 MCP 协议访问所有 Wiki 功能")


def example_4_rest_api_client():
    """示例 4：REST API 客户端"""
    print("\n" + "=" * 60)
    print("示例 4：REST API 客户端（使用 httpx）")
    print("=" * 60)

    # 客户端调用示例（不实际运行服务器）
    print("客户端代码示例:\n")
    print("import httpx")
    print("")
    print("# 获取知识库状态")
    print("response = httpx.get('http://localhost:8765/api/wiki/status')")
    print("print(response.json())")
    print("")
    print("# 搜索")
    print("response = httpx.get(")
    print("    'http://localhost:8765/api/wiki/search',")
    print("    params={'q': '关键词', 'limit': 10, 'backend': 'fts5'}")
    print(")")
    print("")
    print("# 写入页面")
    print("response = httpx.post(")
    print("    'http://localhost:8765/api/wiki/page',")
    print("    json={'page_name': 'TestPage', 'content': '# Test Content'}")
    print(")")


if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " llmwikify Web 服务器示例".center(58) + "║")
    print("╚" + "═" * 58 + "╝\n")

    example_1_basic_server()
    example_2_with_auth()
    example_3_mcp_only()
    example_4_rest_api_client()

    print("\n" + "=" * 60)
    print("✓ 所有服务器示例演示完成！")
    print("=" * 60)
