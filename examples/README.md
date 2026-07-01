# llmwikify 端到端示例剧本

> **v0.38.0 (2026-06-30)** — 5 个端到端剧本，对应 [docs/TUTORIAL.md](../docs/TUTORIAL.md)
> 5 个场景。每个剧本 30-80 行独立可跑脚本 + README + fixtures。

---

## 📋 剧本目录

| # | 场景 | 路径 | 关键 API |
|---|---|---|---|
| 01 | 个人阅读笔记 wiki | [`01_personal_reading_notes/`](01_personal_reading_notes/) | init / ingest / search / write_page / build-index / references / lint |
| 02 | 公司尽调知识库 | [`02_company_research_kb/`](02_company_research_kb/) | batch ingest / synthesize / GraphAnalyzer / lint |
| 03 | 多 wiki 注册表 | [`03_multi_wiki_registry/`](03_multi_wiki_registry/) | WikiRegistry / WikiDiscovery / switch / list |
| 04 | Chat SSE 客户端 | [`04_chat_sse_client/`](04_chat_sse_client/) | httpx.stream / /api/agent/chat / SSE 事件 |
| 05 | Paper → Factor → Backtest | [`05_paper_to_factor/`](05_paper_to_factor/) | write_factor_yaml / list_factors / DuckDB |

---

## 🚀 一键跑全部

```bash
# 1-3、5 不需要 LLM / 网络
for d in 0[1-3]_* 05_*; do
    echo "===== $d ====="
    (cd "$d" && python play.py)
    echo
done

# 4 需要先启 server
(cd /tmp/demo-wiki && llmwikify init --agent generic)
(cd /tmp/demo-wiki && llmwikify serve --web --port 8765 --auth-token mysecret &) ; sleep 3
cd 04_chat_sse_client && python play.py
```

---

## 📁 配置文件模板

旧版 `*.yaml` 模板（`personal-kb.yaml` / `project-docs.yaml` 等）保留为
wiki config snippets，可直接 `cat <file> >> .wiki-config.yaml` 合并。

| 文件 | 用途 |
|---|---|
| `personal-kb.yaml` | 个人知识库 config 片段 |
| `project-docs.yaml` | 项目文档 wiki |
| `research-wiki.yaml` | 研究知识库 |
| `mining-news-wiki.yaml` | 矿业新闻 wiki |

---

## 🗄️ Legacy 脚本（已迁移）

历史零散示例已搬到 [`legacy/`](legacy/) 目录并加 **DEPRECATED** 横幅。
**不要在新代码里引用**。迁移路径见 [legacy/README.md](legacy/README.md)。

| 旧文件 | 替代剧本 |
|---|---|
| `legacy/basic_usage.py` | `01_personal_reading_notes/` |
| `legacy/run_server.py` | `03_multi_wiki_registry/` + `04_chat_sse_client/` |
| `legacy/mcp_agent.py` | `04_chat_sse_client/` |
| `legacy/integrate_with_django.py` | （仍参考用，无端到端剧本） |
| `legacy/integrate_with_flask.py` | （仍参考用，无端到端剧本） |
| `legacy/Dockerfile.example` | （仍参考用） |
| `legacy/docker-compose.yml.example` | （仍参考用） |

---

## 🔍 选哪个剧本

```
我想……
├── 入门：把 PDF 转成可搜索 wiki          → 01
├── 多源分析：年报/招股书 → 知识图谱       → 02
├── 一个 server 挂多个 wiki              → 03
└── 让 LLM 反过来用 wiki 回答问题         → 04
└── 量化复现：paper → factor → backtest  → 05
```

详见 [docs/TUTORIAL.md §0 决策树](../docs/TUTORIAL.md#0-预备安装矩阵--决策树)。
