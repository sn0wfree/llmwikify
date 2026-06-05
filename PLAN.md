# llmwikify 重构路线图 v1.0

> **范围**：7 项全做（14-20 commit · 2-3 周）
> **决策**：弃用 shim 保留 1 release cycle · 顺手修 3 个 pre-existing 失败 · 每 Phase 后更新 graph

---

## 进度总览

| # | 候选 | Phase | 状态 | 起始 commit | 完成 commit | 测试增量 |
|---|------|-------|------|------------|------------|---------|
| 1 | LLM 客户端去重 | 1 | 🔵 in_progress | — | — | +30 |
| 2 | CLI 命令拆解 | 1 | 🔵 planned | — | — | +50 |
| 3 | WikiAnalyzer rule-based | 1 | 🔵 planned | — | — | +30 |
| 4 | Wiki 13-mixin 收敛 | 2 | 🔵 planned | — | — | +5 |
| 5 | autoresearch 内部重组 | 2 | 🔵 planned | — | — | +30 |
| 6 | MCP 整合 | 3 | 🔵 planned | — | — | +5 |
| 7 | 错误/日志统一 | 3 | 🔵 planned | — | — | +20 |

**状态图标**：🔵 planned · 🟡 in_progress · ✅ done · ❌ blocked

---

## Pre-existing 待修

- [ ] `tests/e2e/` 2 failures
- [ ] `tests/test_relation_engine.py` 1 failure

不阻塞重构主路径；失败归失败，顺手处理时单独 commit。

---

## Phase 1 — 奠基

### #1 LLM 客户端去重（5-6 commit · +30 测试）

```
C1: 新建 src/llmwikify/llm/streamable.py（StreamableLLMClient 复制）
C2: 合并 __init__ / 父类引用 LLMClient
C3: autoresearch import 改 → llmwikify.llm.streamable
C4: agent/backend/adapters.py 变 5 行 shim + DeprecationWarning
C5: providers/registry.py 内部仍走 agent.backend
C6: graph 更新 + 全套测试验证
```

### #2 CLI 命令拆解（2-3 commit · +50 测试）

```
C1: cli/_base.py + cli/_output.py + cli/_config.py
C2: 简单命令迁移（10 个）
C3: 复杂命令迁移（16 个）+ main() 改用 registry
```

### #3 WikiAnalyzer rule-based（1-2 commit · +30 测试）

```
C1: core/lint/ 新建 + 17 个 rule 文件
C2: WikiAnalyzer 变 aggregator + WikiLintMixin 全委托
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

### #6 MCP 整合（1-2 commit · +5 测试）

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
YYYY-MM-DD HH:MM | Phase X #Y-CZ | <commit-hash> | <one-line summary>
```
