"""
DEPRECATED — 推荐改用 `llmwikify serve` CLI 或 llmwikify.interfaces.mcp.create_mcp_server。
端到端剧本：../04_chat_sse_client/  (含 MCP + REST + SSE 全栈)

llmwikify MCP 集成示例

演示：
1. 启动 MCP 服务器
2. MCP 工具列表
3. 与外部 Agent 集成的模式
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def example_1_mcp_server():
    """示例 1：启动 MCP 服务器"""
    print("=" * 60)
    print("示例 1：MCP 服务器")
    print("=" * 60)

    from llmwikify import Wiki, create_wiki
    from llmwikify.mcp import create_mcp_server, serve_mcp

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 创建 MCP 服务器
        mcp = create_mcp_server(wiki, name="example-wiki")

        print(f"✓ MCP 服务器已创建")
        print(f"  名称: example-wiki")
        print(f"  可用工具: {len(mcp.tools)} 个")
        print("\n⚠️  此示例仅演示创建，不实际启动服务")


def example_2_mcp_tools_list():
    """示例 2：MCP 工具列表"""
    print("\n" + "=" * 60)
    print("示例 2：MCP 可用工具列表")
    print("=" * 60)

    tools = [
        ("wiki_init", "初始化知识库目录结构"),
        ("wiki_ingest", "提取并导入源文件（PDF/URL/文本等）"),
        ("wiki_write_page", "写入或更新 Wiki 页面"),
        ("wiki_read_page", "读取 Wiki 页面内容"),
        ("wiki_search", "全文搜索，支持 fts5/qmd 后端"),
        ("wiki_lint", "健康检查（死链、孤儿页）"),
        ("wiki_status", "知识库状态总览"),
        ("wiki_log", "追加日志记录"),
        ("wiki_recommend", "建议缺失页面、检测孤儿页"),
        ("wiki_build_index", "构建引用索引"),
        ("wiki_read_schema", "读取 Wiki Schema"),
        ("wiki_update_schema", "更新 Wiki Schema"),
        ("wiki_synthesize", "将查询答案保存为 Wiki 页面"),
        ("wiki_sink_status", "查询 sink 缓冲区状态"),
        ("wiki_references", "获取页面入链/出链"),
        ("wiki_graph", "图数据库操作"),
        ("wiki_graph_analyze", "图分析（PageRank、社区检测"),
        ("wiki_analyze_source", "源文件分析（实体、关系提取）"),
        ("wiki_suggest_synthesis", "跨源合成建议"),
        ("wiki_knowledge_gaps", "知识缺口检测"),
    ]

    print(f"\n总计 {len(tools)} 个 MCP 工具:\n")
    for i, (name, desc) in enumerate(tools, 1):
        print(f"{i:2d}. {name:<25s} {desc}")


def example_3_agent_integration_patterns():
    """示例 3：Agent 集成模式"""
    print("\n" + "=" * 60)
    print("示例 3：Agent 集成模式")
    print("=" * 60)

    patterns = [
        ("模式 1: 独立 MCP 服务器",
         "llmwikify 作为独立 MCP 服务运行，通过 stdio 或 HTTP 连接到 Agent",
         "llmwikify serve --transport stdio"),

        ("模式 2: FastAPI 集成",
         "在统一 FastAPI 服务器中挂载 MCP，同时支持 REST API",
         "from llmwikify.interfaces.server import WikiServer\n"
         "server = WikiServer(wiki, enable_mcp=True)"),

        ("模式 3: 嵌入到 Agent 项目",
         "直接在 Agent 代码中导入 Wiki 类，不通过 MCP 层",
         "from llmwikify import Wiki\n"
         "wiki = Wiki('./path')"),
    ]

    separator = "─" * 30
    for name, desc, code in patterns:
        print(f"\n{name}\n{separator}")
        print(f"说明: {desc}")
        print(f"代码:\n{code}")


def example_4_claude_config():
    """示例 4：Claude Desktop MCP 配置"""
    print("\n" + "=" * 60)
    print("示例 4：Claude Desktop MCP 配置")
    print("=" * 60)

    config_example = '''
{
  "mcpServers": {
    "llmwikify": {
      "command": "python3",
      "args": [
        "-m", "llmwikify",
        "mcp",
        "--name", "my-wiki",
        "--wiki-root", "/path/to/your/wiki"
      ]
    }
  }
}
'''
    print("Claude Desktop 配置 (claude_desktop_config.json):")
    print(config_example)


if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " llmwikify MCP 集成示例".center(58) + "║")
    print("╚" + "═" * 58 + "╝\n")

    example_1_mcp_server()
    example_2_mcp_tools_list()
    example_3_agent_integration_patterns()
    example_4_claude_config()

    print("\n" + "=" * 60)
    print("✓ MCP 示例演示完成！")
    print("=" * 60)
