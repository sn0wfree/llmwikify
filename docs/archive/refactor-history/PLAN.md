# llmwikify 重构路线图 v1.0

> **范围**：7 项全做（14-20 commit · 2-3 周）
> **决策**：弃用 shim 保留 1 release cycle · 顺手修 3 个 pre-existing 失败 · 每 Phase 后更新 graph

---

## 进度总览

| # | 候选 | Phase | 状态 | 起始 commit | 完成 commit | 测试增量 |
|---|------|-------|------|------------|------------|---------|
| 1 | LLM 客户端去重 | 1 | ✅ done | 692c40f⁻¹ | ef31d2f | +30 |
| 2 | CLI 命令拆解 | 1 | ✅ done | 435c5cc | 34a253e | +94 |
| 3 | WikiAnalyzer rule-based | 1 | ✅ done | 0fa1f59 | 716a19a | +28 |
| 4 | Wiki 13-mixin 收敛 | 2 | ✅ done | 5094210⁻¹ | 5094210 | +6 |
| 5 | autoresearch 内部重组 | 2 | ✅ done | a43dc7c⁻¹ | 43d2a1d | +30 |
| 6 | MCP 整合 | 3 | ✅ done | 45afcdf⁻¹ | 6211b97 | +7 |
| 7 | 错误/日志统一 | 3 | ✅ done | b07e893⁻¹ | b07e893 | +14 |
| 8 | Level 2 WikiBackend | post-7 | ✅ done | 624b268⁻¹ | 624b268 | +31 |

**状态图标**：🔵 planned · 🟡 in_progress · ✅ done · ❌ blocked

---

## Pre-existing 待修

- [ ] `tests/e2e/` 2 failures
- [ ] `tests/test_relation_engine.py` 1 failure

不阻塞重构主路径；失败归失败，顺手处理时单独 commit。

---

## Phase 1 — 奠基

### #1 LLM 客户端去重（5-6 commit · +30 测试）✅

```
C1: 新建 src/llmwikify/llm/streamable.py（StreamableLLMClient 复制）        ✅ d7641ed⁻¹
C2: 合并 __init__ / 父类引用 LLMClient                                       ✅ d7641ed
C3: autoresearch import 改 → llmwikify.llm.streamable                        ✅ fba2a9f
C4: agent/backend/adapters.py 变 5 行 shim + DeprecationWarning              ✅ 3555764⁻¹
C5: providers/registry.py 内部仍走 agent.backend                              ✅ ef31d2f
C6: graph 更新 + 全套测试验证                                                  ✅ (this commit)
```

### #2 CLI 命令拆解（2-3 commit · +50 测试）

```
C1: cli/_base.py + cli/_output.py + cli/_config.py
C2: 简单命令迁移（10 个）
C3: 复杂命令迁移（16 个）+ main() 改用 registry
```

### #3 WikiAnalyzer rule-based（1-2 commit · +28 测试）✅

```
C1: core/lint/ 新建 + 8 个 rule 文件                                     ✅ 0fa1f59
C2: WikiAnalyzer 变 aggregator + WikiLintMixin 全委托（C1 已隐式完成）  ✅ 716a19a
```

---

## Phase 2 — 在 Phase 1 之上

### #4 Wiki 13-mixin 收敛（1 commit · +5 测试）

```
C1: 删 WikiSynthesisMixin + WikiLintMixin 全委托
```

### #5 autoresearch 内部重组（3-5 commit · +30 测试）

```
C1: 拆 engine.py → engine/{orchestrator,llm_resolver,event_logger}.py
C2: 拆 actions.py → actions/{sub_query,gap_replan,source_collect}.py
C3: 移 db/db_migrations/state/session → persistence/
C4: 27 个 autoresearch 文件更新 import
C5: 公共 API compatibility shim
```

---

## Phase 3 — 打磨

### #6 MCP 整合（1-2 commit · +5 测试）✅

**C1（1 commit, +7 tests, 2 commits total: docs + refactor）**：

```
45afcdf docs: document Phase 3 #6 — mcp is now alias of serve (v0.34.0 removal)
6211b97 refactor(cli,mcp): merge mcp→serve alias + add help subcommand
```

实现：
- `cli/commands/serve.py`：删除 `McpCommand` 类，serve subparser 加 `aliases=['mcp']`
- `cli/commands/help_cmd.py`（新）：`HelpCommand` + `SUBCOMMAND_ALIASES` 字典
- `cli/commands/__init__.py`：注册 HelpCommand，删除 McpCommand
- `cli/_app.py`：提取 `_build_parser()`，main() 通过 SUBCOMMAND_ALIASES 解析 alias
- `mcp/server.py`：3 个 deprecated 函数 → 1-line 委托到 MCPAdapter / WikiServer
- `cli/commands/serve.py:107`：stdio 路径直接用 MCPAdapter（消除 1 个内部 deprecation）

测试（7 个）：
- test_mcp_is_argparse_alias_of_serve
- test_mcp_accepts_serve_only_flags (`mcp --web` 现在工作)
- test_serve_command_is_only_registered_command
- test_help_command_lists_aliases
- test_init_writes_serve_command_in_mcp_config (决策 5.b: 验证 init 模板可安全用 serve)
- test_serve_py_does_not_import_mcp_server (回归 guard)
- test_mcp_command_class_not_in_commands_init (回归 guard)

净效果：
- `mcp/server.py`: 140 → 105 LOC
- `cli/commands/serve.py`: 167 → 158 LOC
- 新增 1 个命令 (`help`)
- `mcp` 仍工作（argparse alias）— v0.34.0 移除
- `init` 模板（claude_mcp.json, codex_mcp.json）保持用 `mcp` — 向后兼容
- mcp/serve help 文本都加 `(alias: mcp)` 提示
- 新 `llmwikify help` 子命令提供命令+alias 列表

```
C1: mcp/server.py 变 shim
C2: 'mcp' CLI 命令 → 'serve --transport=mcp' flag
```

### #7 错误/日志统一（1 commit · +20 测试）

```
C1: cli/_base.py 加 _error(e) → logger + 替换 print
```

---

## 累计数字

| 指标 | 当前 | 目标 |
|------|------|------|
| God nodes ≥65 edges | 8 | ≤4 |
| CLI 最大文件 LOC | 2200 | ~150 |
| deprecation warning | 1 | 0（保留 shim）|
| LLM 客户端类 | 2 并行 | 1 + 1 shim |
| autoresearch 文件 | 27 扁平 | 4 子包分组 |
| 总测试数 | 1049 | ~1230（+181）|
| pre-existing 失败 | 3 | 0 |

---

## 进度日志

每完成一个 commit 在此追加一行：

```
2026-06-05 | Phase 1 #1-C1 | ae8021c⁻¹ | docs: PLAN.md tracker
2026-06-05 | Phase 1 #1-C1 | d7641ed⁻¹ | refactor(llm): add canonical home
2026-06-05 | Phase 1 #1-C2 | d7641ed   | refactor(llm): StreamableLLMClient extends LLMClient
2026-06-05 | Phase 1 #1-C3 | fba2a9f   | refactor(autoresearch): import from new home
2026-06-05 | Phase 1 #1-C4 | 3555764⁻¹ | refactor(agent): collapse adapters.py to shim
2026-06-05 | Phase 1 #1-C5 | ef31d2f   | test(providers): validate provider compat
2026-06-05 | Phase 1 #1-C6 | (this)   | docs: Phase 1 #1 closure + graph update
```

```

## 最终评估（2026-06-06，7-item 重构 + 预存在修复完成后）

### God Node 演化

| Phase | WikiCLI | WikiAnalyzer | Wiki | ResearchEngine | WikiProtocol | PromptReg |
|-------|---------|--------------|------|----------------|--------------|-----------|
| 06-05（pre）| **65** ⭐ | 59 | 111 | 67 | 66 | 132 |
| Phase 1 后 | gone | 67 | 111 | 71 | 74 | 149 |
| Phase 2/3 后 | gone | 67 | 111 | 71 | 74 | 149 |

⭐ WikiCLI 已退出 top-10 god nodes（从 65 边降到不在列表）

### 文件结构健康度

| 指标 | Before | After | Δ |
|------|--------|-------|---|
| `cli/commands.py` LOC | 2200 | 335 | **−85%** |
| `core/wiki_analyzer.py` LOC | 929 | 520 | **−44%** |
| `core/lint/` 新文件 | 0 | 9 | (8 rules + 1 engine) |
| `autoresearch/engine.py` LOC | 885 | 526 | **−40%** |
| `mcp/server.py` LOC | 140 | 50 | **−64%** |
| `mcp/server.py` 3 函数 | 3 inline | 3 1-line 委托 | 简化 |
| `WikiAnalyzer(self)` 重复实例化 | 16/call | 1 cached | **−94%** |
| 直接 emoji `print("❌")` 模式 | 4+ | 0 | 全消除 |
| 内部 deprecation warning | 1 | 0 | **−1** |

### 整个 7-item 重构最终统计

| 项 | Commits | Tests | 状态 |
|----|---------|-------|------|
| #1 LLM 客户端去重 | 6 | +30 | ✅ |
| #2 CLI 命令拆解 | 3 | +94 | ✅ |
| #3 WikiAnalyzer rule-based | 2 | +28 | ✅ |
| #4 Wiki 13-mixin 收敛 | 1 | +6 | ✅ |
| #5 autoresearch 内部重组 | 3 | +30 | ✅ |
| #6 MCP 整合 | 2 | +7 | ✅ |
| #7 错误/日志统一 | 1 | +14 | ✅ |
| pre-existing fixes | 1 | (修 20) | ✅ |
| **Total** | **19** | **+209** | **7/7** |

### 公共 API 兼容性

- 0 公共 API 破坏
- `WikiCLI`, `LLMClient`, `StreamableLLMClient`, `WikiAnalyzer`, `ResearchEngine` 全部保持原签名
- MCP 客户端配置（`command: ['llmwikify', 'mcp']`）继续工作（向后兼容）
- `from llmwikify.cli.commands import WikiCLI/main` 仍工作（PEP 562 延迟 re-export）

### 7-item 重构全部完成 ✅

---

## Post-7-item: Level 2 WikiBackend 实施 (2 commits, +31 测试)

按 `docs/wiki-backend-interface.md` 计划执行，将 Wiki god node 的存储抽象出独立 backend。

| 项 | 起始 commit | 完成 commit | 测试增量 | 状态 |
|----|------------|------------|---------|------|
| WikiBackend Protocol + LocalFileBackend | cff301f⁻¹ | cff301f | +20 | ✅ |
| Wire Wiki to use backend | 624b268⁻¹ | 624b268 | +11 | ✅ |

### 实施结果

- **新文件**：`src/llmwikify/core/wiki_backend.py` (+349 LOC, WikiBackend Protocol + LocalFileBackend 13 方法)
- **新测试**：`tests/test_wiki_backend.py` (+200 LOC, 20 tests) + `tests/test_wiki_uses_backend.py` (+257 LOC, 11 tests)
- **Wiki 类改造**：`__init__` 接受 `backend=None`，eagerly 创建 backend + WikiIndex；10 个新 helper 方法
- **Mixin 改造**：8 个 mixin 文件，27 个 fs ops → Wiki helper 调用
- **22 storage 方法** → 1-line 委托 (`write_page`, `read_page`, `append_log`, `_update_index_file`, `_cache_source_analysis`, `_get_cached_source_analysis`, `_load_page_type_mapping`, `_merge_wiki_md` 等)
- **公共 API 100% 向后兼容**：`Wiki(root)` 仍工作

### graphify-out 度量对比

| 指标 | 7-item refactor 后 (9ea7955) | Level 2 后 (624b268) | Δ |
|------|------|------|---|
| 节点数 | 11371 | 11572 | +201 |
| 边数 | 18869 | 19239 | +370 |
| 社区数 | 753 | 747 | −6 (consolidation) |
| Wiki god node 总边数 | 334 (119+114+101) | 348 (119+115+114) | +14 |
| WikiProtocol 边数 | 74 | 85 | +11 (新 helper methods) |
| WikiAnalyzer 边数 | 87 | 88 | +1 |
| 新社区: "Storage Layer" | — | 46 节点 (LocalFileBackend, _build_merge_notice, _find_insertion_point, _parse_h2_sections, ...) | 新增 |
| 新社区: "Backend tests" | — | 42 节点 (test_wiki_backend.py) | 新增 |
| 新社区: "Wiki-uses-backend" | — | 23 节点 (test_wiki_uses_backend.py) | 新增 |

Wiki in-degree 未显著下降（method count 未变，100+ public methods 保留），但 storage 现在是独立 swappable 抽象。WikiBackend 是 1 个 cohesion 0.05 的独立社区（自包含，连接少 = 目标）。

### 未来加 backends

- **InMemoryBackend**：1 commit + ~100 LOC, 3-4h（5-6s 测试加速）
- **RemoteWikiBackend**：1 commit + ~150 LOC, ~6h
- **CloudWikiBackend**：1 commit + ~200 LOC, ~8h

`WikiIndex(db_path=Path(":memory:"))` 复用现有 SQLite 即可，**不需要 InMemoryWikiIndex**。
