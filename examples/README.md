# llmwikify 集成示例

本目录包含 llmwikify 的各种使用和集成示例。

---

## 📋 示例列表

| 文件名 | 说明 |
|--------|------|
| **`basic_usage.py`** | 基础使用：创建 Wiki、页面读写、搜索、引用、健康检查 |
| **`run_server.py`** | Web 服务器：FastAPI 统一服务器、API 认证、MCP 集成 |
| **`mcp_agent.py`** | MCP Agent 集成：MCP 工具列表、Agent 集成模式、Claude 配置 |
| **`integrate_with_django.py`** | Django 集成：ORM 集成、视图、API、信号处理 |
| **`integrate_with_flask.py`** | Flask 集成：Blueprint、REST API、模板渲染 |
| **`Dockerfile.example`** | Docker 容器化：多阶段构建、健康检查 |
| **`docker-compose.yml.example`** | Docker Compose：完整服务栈、备份、QMD |

---

## 🚀 快速开始

### 运行基础示例

```bash
# 确保 llmwikify 已安装
pip install -e .

# 运行基础使用示例
python examples/basic_usage.py

# 运行服务器示例
python examples/run_server.py

# 运行 MCP 示例
python examples/mcp_agent.py
```

---

## 📖 集成场景

### 场景 1：作为 Python 库使用

```python
from llmwikify import Wiki, create_wiki

wiki = create_wiki("./my-wiki")
wiki.write_page("Test", "content")
results = wiki.search("keyword")
```

适用：任何 Python 项目的本地知识库。

### 场景 2：作为 Web 服务

```python
from llmwikify.server import WikiServer

server = WikiServer(wiki, enable_mcp=True, enable_rest=True)
server.run(port=8765)
```

适用：微服务架构、多客户端共享知识库。

### 场景 3：作为 MCP 工具

```bash
llmwikify mcp --name my-wiki
```

适用：AI Agent 集成（Claude Desktop、Cursor、OpenCode 等）。

### 场景 4：Web 框架集成

- Django：ORM 模型、视图、信号
- Flask：Blueprint、REST API、Jinja2 模板

---

## 🔧 配置文件模板

| 文件名 | 说明 |
|--------|------|
| **`personal-kb.yaml`** | 个人知识库配置 |
| **`project-docs.yaml`** | 项目文档配置 |
| **`research-wiki.yaml`** | 研究知识库配置 |
| **`mining-news-wiki.yaml`** | 新闻摘要配置 |

---

## 🐳 Docker 部署

```bash
# 复制配置文件
cp examples/Dockerfile.example ./Dockerfile
cp examples/docker-compose.yml.example ./docker-compose.yml

# 启动
docker-compose up -d

# 带 QMD 混合搜索
docker-compose --profile qmd up -d
```

---

## 💡 最佳实践

### 1. 知识库路径管理

```python
# 好做法：使用绝对路径
wiki = create_wiki(Path.cwd() / "data" / "wiki")

# 避免：相对路径依赖工作目录
wiki = create_wiki("../wiki")  # ❌
```

### 2. Wiki 实例生命周期

```python
# 在应用启动时初始化，复用单例
# 避免每次请求都创建 Wiki 实例

# Django: 放入 AppConfig.ready()
# Flask: 放入应用工厂
# FastAPI: 放入 lifespan 事件
```

### 3. 并发访问

Wiki 类是线程安全的，可以在多线程环境下使用。但建议在生产环境中：
- 使用连接池模式
- 避免频繁打开关闭
- 考虑使用文件锁进行写操作

### 4. 备份策略

```bash
# 定时备份
0 2 * * * tar -czf backup-$(date +%Y%m%d).tar.gz ./wiki/
```

---

## ❓ 常见问题

### Q: 如何处理大文件？

A: 建议：
- 单个页面不超过 10MB
- 大附件放入 raw/ 目录
- 使用 `wiki_ingest` 自动提取内容

### Q: 如何迁移现有知识库？

A:
```python
from pathlib import Path

wiki = Wiki("./new-wiki")
wiki.init()

# 批量导入
for md_file in Path("./old-wiki").glob("**/*.md"):
    content = md_file.read_text()
    wiki.write_page(md_file.stem, content)
```

### Q: 如何自定义 MCP 工具？

A:
```python
from llmwikify.mcp.tools import register_wiki_tools
from fastmcp import FastMCP

mcp = FastMCP("my-custom-wiki")
register_wiki_tools(mcp, wiki)

# 添加自定义工具
@mcp.tool
def my_custom_tool():
    return "..."
```

---

## 📚 相关文档

- [项目 README](../README.md)
- [架构文档](../ARCHITECTURE.md)
- [迁移指南](../MIGRATION.md)
- [MCP 配置](../docs/MCP_SETUP.md)
- [QMD 配置](../docs/QMD_SETUP.md)
