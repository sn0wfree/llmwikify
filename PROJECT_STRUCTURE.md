# llmwikify 项目结构

标准 Python 包结构的项目布局

## 📁 目录结构

```
llmwikify/
├── 📄 pyproject.toml              # 项目配置和依赖 (PEP 517/518)
├── 📄 README.md                   # 项目说明和使用指南 (~480 lines)
├── 📄 ARCHITECTURE.md             # 技术架构文档 (~370 lines)
├── 📄 CHANGELOG.md                # 版本变更记录
├── 📄 PROJECT_SUMMARY.md          # 项目总结
├── 📄 PROJECT_STRUCTURE.md        # 本文件
├── 📄 MIGRATION.md                # 版本迁移指南
├── 📄 LICENSE                     # MIT 许可证
├── 📄 .gitignore                  # Git 忽略规则
├── 📄 .wiki-config.yaml.example   # 配置文件模板
│
├── 📂 src/llmwikify/              # 源代码目录
│   ├── __init__.py                # 包入口、版本 (v0.12.6)、导出
│   ├── core/                      # 核心业务逻辑
│   │   ├── wiki.py                # Wiki 类 (~1,260 lines)
│   │   │   ├── init()             # 初始化（幂等，支持 overwrite）
│   │   │   ├── ingest_source()    # 摄入源文件（统一归集到 raw/）
│   │   │   ├── write_page()       # 写入页面（自动更新 index.md）
│   │   │   ├── read_page()        # 读取页面
│   │   │   ├── search()           # 全文搜索
│   │   │   ├── synthesize_query() # 查询答案持久化（v0.12.6+）
│   │   │   ├── lint()             # 健康检查
│   │   │   ├── recommend()        # 智能推荐
│   │   │   ├── hint()             # 智能建议
│   │   │   └── read_schema() / update_schema() # 管理 wiki.md
│   │   └── index.py               # WikiIndex 类 (~309 lines)
│   │       ├── FTS5 全文搜索       # BM25 排序，高亮片段
│   │       ├── 引用追踪            # 双向 wikilink 解析
│   │       └── JSON 导出           # Obsidian 兼容
│   ├── extractors/                # 内容提取器
│   │   ├── base.py                # detect_source_type(), extract()
│   │   ├── text.py                # 文本/HTML 提取
│   │   ├── pdf.py                 # PDF 提取（可选: pymupdf）
│   │   ├── web.py                 # URL 提取（可选: trafilatura）
│   │   └── youtube.py             # YouTube 提取（可选: youtube-transcript-api）
│   ├── cli/                       # 命令行接口
│   │   └── commands.py            # WikiCLI 类（15 个命令）
│   ├── mcp/                       # MCP 服务器
│   │   └── server.py              # MCPServer 类（13 个工具）
│   ├── config.py                  # 配置系统
│   └── llm_client.py              # LLM API 客户端（可选）
│
├── 📂 tests/                      # 测试目录
│   ├── conftest.py                # pytest 配置和 fixtures
│   ├── test_wiki_core.py          # Wiki 核心测试（36 tests）
│   ├── test_query_flow.py         # 查询合成测试（27 tests）
│   ├── test_index.py              # WikiIndex 测试（8 tests）
│   ├── test_recommend.py          # 推荐引擎测试（5 tests）
│   ├── test_cli.py                # CLI 命令测试（8 tests）
│   ├── test_extractors.py         # 提取器测试（12 tests）
│   └── test_llm_client.py         # LLM 客户端测试（14 tests）
│
├── 📂 docs/                       # 文档目录
│   ├── CONFIGURATION_GUIDE.md     # 配置指南（英文）
│   ├── CONFIG_GUIDE.md            # 配置指南（中文）
│   ├── LLM_WIKI_PRINCIPLES.md     # Karpathy LLM Wiki 原则
│   ├── REFERENCE_TRACKING_GUIDE.md # 引用追踪指南
│   └── MCP_SETUP.md               # MCP 服务器设置指南
│
└── 📂 archive/reports/            # 历史开发报告
```

## 📊 文件统计

| 类别 | 文件数 | 代码行数 |
|------|--------|----------|
| 核心代码 | 11+ | ~2,500 |
| 测试代码 | 8 | ~1,200 |
| 文档 | 12+ | ~3,500 |
| 配置 | 4 | ~300 |
| **总计** | **35+** | **~7,500** |

## 🎯 核心模块

### src/llmwikify/core/

| 文件 | 行数 | 说明 |
|------|------|------|
| `wiki.py` | ~1,260 | Wiki 类：业务逻辑、页面管理、查询合成、健康检查 |
| `index.py` | ~309 | WikiIndex：FTS5 搜索、引用追踪、JSON 导出 |

### src/llmwikify/extractors/

| 文件 | 核心函数 | 可选依赖 |
|------|----------|----------|
| `base.py` | `detect_source_type()`, `extract()` | 无 |
| `text.py` | `extract_text_file()`, `extract_html_file()` | 无 |
| `pdf.py` | `extract_pdf()` | `pymupdf` |
| `web.py` | `extract_url()` | `trafilatura` |
| `youtube.py` | `extract_youtube()` | `youtube-transcript-api` |

### src/llmwikify/mcp/

| 工具 | 说明 |
|------|------|
| `wiki_init` | 初始化 wiki |
| `wiki_ingest` | 摄入源文件（自动归集到 raw/） |
| `wiki_write_page` / `wiki_read_page` | 页面操作 |
| `wiki_search` | 全文搜索 |
| `wiki_lint` | 健康检查 |
| `wiki_status` | 状态概览 |
| `wiki_log` | 日志记录 |
| `wiki_recommend` | 推荐（缺失页面、孤立页面） |
| `wiki_build_index` | 构建引用索引 |
| `wiki_read_schema` | 读取 wiki.md |
| `wiki_update_schema` | 更新 wiki.md |
| `wiki_synthesize` | **查询答案持久化**（v0.12.6+） |

### src/llmwikify/cli/

15 个 CLI 命令：`init`, `ingest`, `write_page`, `read_page`, `search`, `lint`, `status`, `log`, `references`, `build-index`, `export-index`, `batch`, `hint`, `recommend`, `serve`

## 🧪 测试套件

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| `test_wiki_core.py` | 36 | Wiki 核心（初始化、摄入、页面、schema、lint） |
| `test_query_flow.py` | 27 | 查询合成（基础、源引用、日志、重复检测、完整流程） |
| `test_index.py` | 8 | WikiIndex（FTS5、链接、导出） |
| `test_recommend.py` | 5 | 推荐引擎 |
| `test_cli.py` | 8 | CLI 命令 |
| `test_extractors.py` | 12 | 内容提取器 |
| `test_llm_client.py` | 14 | LLM 客户端配置和 JSON 解析 |
| **总计** | **110** | **100% passing** |

## 📦 安装和开发

### 基础安装
```bash
pip install -e .
```

### 开发安装
```bash
pip install -e ".[dev]"
```

### 运行测试
```bash
pytest
# 输出: 110 passed
```

### 代码检查
```bash
# 格式化
black src/llmwikify

# Linting
ruff check src/llmwikify

# 类型检查
mypy src/llmwikify
```

## 🚀 打包发布

### 构建
```bash
python -m build
```

### 发布到 PyPI
```bash
twine upload dist/*
```

## 📝 版本管理

版本号格式：`v0.MINOR.PATCH`

- `0.12.x` — 功能迭代（CLI 完善、MCP 工具扩展、查询合成）
- `0.13.0` — 计划：增强 lint、增强 search、暴露 hint

## 📋 文档体系

| 文档 | 目标读者 | 内容 |
|------|----------|------|
| README.md | 用户 | 快速开始、功能介绍、API |
| CHANGELOG.md | 用户/开发者 | 版本变更历史（v0.9.0 → v0.12.6） |
| ARCHITECTURE.md | 开发者 | 技术架构、设计决策、数据流 |
| PROJECT_SUMMARY.md | 所有 | 项目总结、统计数据 |
| PROJECT_STRUCTURE.md | 开发者 | 文件结构、模块说明 |
| MIGRATION.md | 用户 | 版本迁移指南 |
| CONFIGURATION_GUIDE.md | 用户 | 配置选项详解（英文） |
| CONFIG_GUIDE.md | 用户 | 配置选项详解（中文） |
| LLM_WIKI_PRINCIPLES.md | 所有 | 设计理念 |
| REFERENCE_TRACKING_GUIDE.md | 用户 | 引用追踪功能 |
| MCP_SETUP.md | 开发者 | MCP 服务器配置 |

---

*最后更新：2026-04-10 | 版本：0.12.6 | 测试：110 passed*
