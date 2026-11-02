# CLI 命令单测批次

日期: 2026-10-15 · 分支: v0.41-dev

## 范围

### 第一批 (`f5957a3b`)

| 文件 | 测试数 | 覆盖点 |
|------|--------|--------|
| `test_doctor_cmd.py` | 65 | 全部 12 个 check helper + run_doctor JSON/文本 + DoctorCommand |
| `test_lint_cmd.py` | 29 | _lint_full/brief/recommendations 全分支 + run_lint 四格式 |
| `test_qmd_cmd.py` | 32 | 5 子命令 + subprocess mock（mcp 集成/异常） |
| `test_wikis_cmd.py` | 21 | list/add/remove/scan + registry 内存态配置 |
| `test_init_cmd.py` | 25 | run_init 全 status 分支 + LLM prompt 路径 |

### 第二批 (`e90ed02f`)

| 文件 | 测试数 | 覆盖点 |
|------|--------|--------|
| `test_migrate_config_cmd.py` | 26 | _format_plan + run 全 reason 分支 + auto_resolve 映射 + 异常 |
| `test_init_llm_cmd.py` | 33 | auto_detect/resolve_api_key/create_llm_config 全路径 + env 中和 |
| `test_graph_analyze.py` | 25 | json/report/empty/full 文本 + 截断 + 缺省 attrs |
| `test_knowledge_gaps.py` | 14 | json + 四类 investigation 文本分支 |

### 第三批

| 文件 | 测试数 | 覆盖点 |
|------|--------|--------|
| `test_small_cmds.py` | 83 | 15 个小命令: read_page/search/status/sink/log/help/fix_wikilinks/write_page/synthesize/suggest/build_index/report/export_graph/community_detect/dict |

**CLI 目录合计: 359 passed**（`pytest tests/interfaces/cli/ -q`）

## 关键设计

- **doctor**: `CONFIG_PATH`/`CONFIG_DIR` 模块级常量 → monkeypatch 到 tmp；
  LLM/server 用 fake `httpx` 注入 `sys.modules`，不碰真实 socket。
- **webui**: `Path(__file__).parent.parent.parent` 上三级 → 测试目录需 3 层深。
- **wikis**: `WikiRegistry` 内存态，条目从 `config['wikis']['local']` 加载。
- **qmd mcp / export_graph**: monkeypatch `subprocess.run` / `kernel.graph.export`。
- **init LLM prompt**: `CONFIG_PATH` 函数内 `from .init_llm_cmd import` → patch 模块属性。
- **migrate**: `from foundation.migration import ...` 函数内 → patch 模块属性即生效。
- **init_llm**: fixture 必须 `delenv` 全部 provider env，防宿主环境泄漏。
- **dict**: `isinstance(wiki, Wiki)` 检查 → monkeypatch `llmwikify.kernel.Wiki` 指向 FakeWiki。
- **stdin 路径**: write_page/synthesize 的 stdin 回落 → monkeypatch `sys.stdin` 为 `StringIO("")`。
- **发现的源码瑕疵**（未改，仅记录）:
  - `_format_plan` 中 `ch.old_value is object()` 恒 False → `<new>` 分支是死代码
  - knowledge_gaps 的 `page.get('latest_year_mentioned', 'unknown')` 在值为 None 时返回 None

## 验证

```
pytest tests/interfaces/cli/ -q  → 359 passed
ruff check 全部新文件             → clean
```

## 未做

- e2e 测试（独立批次）
- 剩余 CLI 大文件: serve / auth / ingest / batch / references / watch / analyze_source / graph_query
- apps 层: wiki_dream_editor / gatherer / wiki_query_skill / agent/tools / research
- interfaces/server + mcp
