# Migration — Dependency Map

> **状态**：in-flight 草案（待 subagent 执行）
> **目标**：把 `llmwikify/reproduction/` 整包迁到 `quantnodes/research/`，让 QuantNodes 仓库独立跑通。本轮**不动 llmwikify/ 任何 src 文件**。
> **关联**：`.claude/agents/migration-quant.md`（subagent prompt）· `MIGRATION_DISPATCH_GUIDE.md`（派发指南）

---

## 0. 速览

| 维度 | 数据 |
|---|---|
| 源包 | `/home/ll/llmwikify/src/llmwikify/reproduction/` |
| 源测试 | `/home/ll/llmwikify/tests/reproduction/` |
| 目标包 | `/home/ll/QuantNodes/QuantNodes/research/` |
| 目标测试 | `/home/ll/QuantNodes/tests/research/` |
| 源生产代码 | 119 个 `.py` / ~24K LoC / 16 子目录 |
| 源测试代码 | 90 个 `.py` / ~18K LoC |
| 源脚本 | 9 个（专用 reproduction scripts）|
| 源示例 | 1 个目录（`05_paper_to_factor`）|
| 总迁移量 | ~42K LoC（prod + tests）+ 9 scripts + 1 dir |
| 外部依赖需处理 | **5 处**（vendor 到 quantnodes.research，零重复）|
| 内部 import 改写 | regex 机械替换 |
| 工作分支 | `dev/repro-merge-2026-07-04`（仅本地，不推）|
| 写 llmwikify/ 树 | **仅 1 个新文件**：`<DATE>.md` migration report |

---

## 1. 子包级迁移映射（16 子目录，整包 cp）

源 `src/llmwikify/reproduction/<sub>/` → 目标 `QuantNodes/research/<sub>/`

| # | 子目录（源 & 目标同名）| 备注 |
|---|---|---|
| 1 | `paper_understanding/` | 7K LoC，主入口之一（含子目录 `llm_extraction/`）|
| 2 | `paper_understanding/llm_extraction/` | 嵌套子目录，独立 stage0-3 |
| 3 | `backtest_pkg/` | 4.5K LoC，回测核心（含 l5_orchestrator）|
| 4 | `data_source/` | 2.2K LoC，data adapter |
| 5 | `persist/` | 1.4K LoC，DB 持久化（run/sessions/factor_library/...）|
| 6 | `pipeline/` | 1.5K LoC，stages + workspace |
| 7 | `common/` | 880 LoC，shared utils（含 `llm_factory.py` 待 vendor）|
| 8 | `factor/` | 542 LoC，因子定义 |
| 9 | `prompts/` | 145 LoC，prompts registry |
| 10 | `reporting/` | 349 LoC，报告生成 |
| 11 | `sink/` | 405 LoC，输出（yaml/duckdb/single_json）|
| 12 | `signal_source/` | 328 LoC，信号源 |
| 13 | `core/` | 379 LoC，recipe/stage/pipeline 基类 |
| 14 | `backtest/` | 264 LoC（旧 backtest 子包，与 backtest_pkg 不同）|
| 15 | `llm_extraction/` | 空目录（占位）|
| 16 | `codegen/` | 3.8K LoC，ReAct codegen（vendor dep #2 也放这里）|

每个子目录独立 cp，每个子目录下都建 `__init__.py`。

---

## 2. 外部依赖映射（5 处，**全部 vendor，零重复**）

> **核心原则**：不复制粘贴任何已有代码，要么引用 quantnodes 自带（**B 方案**），要么整文件 vendor（**A 方案**）。

### 依赖 #1 — `feedback_templates.py`（15 行，单常量）

| 项 | 内容 |
|---|---|
| 源 | `/home/ll/llmwikify/src/llmwikify/kernel/codegen/feedback_templates.py` |
| 目标 | `/home/ll/QuantNodes/QuantNodes/research/codegen/feedback_templates.py` |
| 内容 | 1 个 string `OBSERVE_FEEDBACK_TEMPLATE`（~50 行 ReAct feedback 模板）|
| 方案 | **A 强制**：纯 string constant，无外部依赖，可直接 vendor |
| LoC | 15 |

### 依赖 #2 — codegen 4 文件 + `__init__.py`

| 源文件（绝对路径）| 目标文件 | LoC |
|---|---|---|
| `/home/ll/llmwikify/src/llmwikify/kernel/codegen/code_tools.py` | `QuantNodes/research/codegen/code_tools.py` | ~150 |
| `/home/ll/llmwikify/src/llmwikify/kernel/codegen/json_extract.py` | `QuantNodes/research/codegen/json_extract.py` | ~50 |
| `/home/ll/llmwikify/src/llmwikify/kernel/codegen/prompts.py` | `QuantNodes/research/codegen/prompts.py` | ~30 |
| `/home/ll/llmwikify/src/llmwikify/kernel/codegen/feedback_templates.py` | `QuantNodes/research/codegen/feedback_templates.py` | 15 |
| 重写 `/home/ll/QuantNodes/QuantNodes/research/codegen/__init__.py` | 内容见 subagent prompt Phase 4.2 | ~25 |
| 方案 | **A 强制**：pure building blocks，只依赖 polars + QuantNodes 第三方 |
| 总 LoC | ~270 |

### 依赖 #3 — UnifiedHook

| 项 | 内容 |
|---|---|
| 源 | `/home/ll/llmwikify/src/llmwikify/kernel/agent/hook.py` |
| 目标 | `/home/ll/QuantNodes/QuantNodes/research/codegen/unified_hook.py` |
| 内容 | `class UnifiedHook`（16 个 hook no-op 事件点的抽象基类）|
| 方案 | **A 强制**：pure interface，无 LLM 依赖。改名避免与 quantnodes agent 命名冲突 |
| LoC | ~150 |

### 依赖 #4 — LLM client（**优先 B → fallback A**）

| 项 | 内容 |
|---|---|
| 源 | `/home/ll/llmwikify/src/llmwikify/foundation/llm/client.py` |
| 目标 | **B**：写在 `QuantNodes/research/common/llm/client.py` 薄 adapter；**A fallback**：直接 cp |
| 内容 | `build_llm_client()` / `load_llm_config()` / `CONFIG_PATH` / `_PROVIDER_INFO` |
| 关键决策 | **B 优先** 探查 `QuantNodes.X` 自带 LLM client（OpenAI/Anthropic wrapper）；**fallback A** 默认行为是 cp 文件 |
| LoC | ~80 |

**B 方案判定逻辑**（subagent 执行）：
```bash
ls /home/ll/QuantNodes/QuantNodes/ | grep -iE "llm|client|provider|model"
grep -rn "class .*\(Provider\|Client\|LLM\)" /home/ll/QuantNodes/QuantNodes/ \
  --include="*.py" 2>/dev/null | head -10
```

### 依赖 #5 — extractors（5 个文件）

| 源文件（绝对路径）| 目标文件 |
|---|---|
| `/home/ll/llmwikify/src/llmwikify/foundation/extractors/base.py` | `QuantNodes/research/common/extractors/base.py` |
| `/home/ll/llmwikify/src/llmwikify/foundation/extractors/markitdown_extractor.py` | `QuantNodes/research/common/extractors/markitdown_extractor.py` |
| `/home/ll/llmwikify/src/llmwikify/foundation/extractors/pdf.py` | `QuantNodes/research/common/extractors/pdf.py` |
| `/home/ll/llmwikify/src/llmwikify/foundation/extractors/text.py` | `QuantNodes/research/common/extractors/text.py` |
| `/home/ll/llmwikify/src/llmwikify/foundation/extractors/__init__.py` | `QuantNodes/research/common/extractors/__init__.py` |
| 方案 | **A 强制**：pure extraction utils，依赖 markitdown（PyPI）|
| LoC | ~250 |

**重要**：`extract_paper.py` 也引用 `extractors.pdf.extract_pdf` + `extractors.web.extract_url`，但 web.py **不需要 cp**（web 提取 reproduction 不直接用），只保留 vendor 文件足够。如有遗漏由 sed 全局捕获。

---

## 3. 内部 import 改写规则（regex，机械）

### 旧 → 新映射

```python
# 两个 regex，anchor 行首（含缩进），处理 multiline + indented
r"""
  ^(?P<indent>\s*)
  (?:from\s+llmwikify\.reproduction\.(?P<path>[\w.]+)\s+import\s+
   |import\s+llmwikify\.reproduction\.(?P<path>[\w.]+)\s*$)
"""
→
r"\g<indent>from quantnodes.research.\g<path> import | import quantnodes.research.\g<path>"
```

### 处理范围 & 跳过

| 范围 | 处理 |
|---|---|
| `QuantNodes/research/**/*.py`（除下面跳过项）| 改 |
| `tests/research/**/*.py` | 改 |
| `scripts/research/*.py` | 改 |
| `examples/paper_to_factor/*.py` | 改 |
| `QuantNodes/research/wiki.py` | 跳过（已有）|
| `QuantNodes/research/report_reproducer.py` | 跳过（已有）|
| `QuantNodes/research/factor_test/` | 跳过（已有目录）|
| `QuantNodes/research/quant_alpha/` | 跳过（已有目录）|
| `QuantNodes/research/_legacy_3c/` | 跳过（已有目录）|

### 实测统计

- 内含 `from llmwikify.reproduction` 形式的文件：~10（大多在 `pipeline/` 和 `core/__init__.py`）
- 含缩进 + 多行 import 的：~3-5 处（典型 in `sink/yaml_duckdb.py`、`backtest_pkg/l5_orchestrator.py`、`core/__init__.py`）

---

## 4. 测试迁移（90 文件）

源 `/home/ll/llmwikify/tests/reproduction/`（90 个 `.py`）→ 目标 `/home/ll/QuantNodes/tests/research/`

整包 `cp -rn` 即可。内部已用 `from llmwikify.reproduction.X` 的 import，会被 Phase 3 同步改写。

**潜在风险**：
- `conftest.py` 在 `tests/reproduction/conftest.py` → `tests/research/conftest.py`，可能含 fixture path 硬编码（仓库根目录假设）
- 部分测试 `pytest.fixture(scope="session")` 引用 `quant/factor.duckdb`（用户数据目录，绝对路径或 relative 假设）
- → Phase 5 跑测试时若失败，针对性修 `conftest.py`

---

## 5. 脚本迁移（9 个）

源 `scripts/<name>.py` → 目标 `scripts/research/<name>.py`

| 序号 | 文件名 | LoC |
|---|---|---|
| 1 | `aggregate_alpha_results.py` | 110 |
| 2 | `analyze_alpha_results.py` | 160 |
| 3 | `cross_validate_factor.py` | 127 |
| 4 | `deep_compare_alphalens.py` | 241 |
| 5 | `merge_alpha_data.py` | 207 |
| 6 | `run_101_alphas_v2.py` | 996 |
| 7 | `validate_alphalens.py` | 190 |
| 8 | `validate_backtrader.py` | 266 |
| 9 | `validate_qn_nodes.py` | 225 |

合计 ~2.5K LoC。

含 `import scripts.research.X` 或类似相对引用 → Phase 3 改写。
含 import `from llmwikify.reproduction` → Phase 3 改写。

---

## 6. 示例迁移（1 个目录）

`/home/ll/llmwikify/examples/05_paper_to_factor/` → `/home/ll/QuantNodes/examples/paper_to_factor/`

含 `README.md` + `play.py` + `fixtures/`，整 cp。

`play.py` 用到 `from llmwikify.reproduction.X` → Phase 3 改写。

---

## 7. 不动清单（**明确不修改**）

| 路径 | 类型 | 理由 |
|---|---|---|
| `/home/ll/QuantNodes/QuantNodes/research/wiki.py` | quantnodes 现有 | 与迁移无关 |
| `/home/ll/QuantNodes/QuantNodes/research/report_reproducer.py` | quantnodes 现有 | 与迁移无关 |
| `/home/ll/QuantNodes/QuantNodes/research/factor_test/` | quantnodes 现有目录 | 同上 |
| `/home/ll/QuantNodes/QuantNodes/research/quant_alpha/` | quantnodes 现有目录 | 同上 |
| `/home/ll/QuantNodes/QuantNodes/research/_legacy_3c/` | quantnodes 现有目录 | 同上 |
| `/home/ll/QuantNodes/QuantNodes/agent/` | quantnodes 已有 | 不抽上移（用户决策）|
| `/home/ll/QuantNodes/QuantNodes/codegen/` | quantnodes 已有（如有） | 同上 |
| `/home/ll/llmwikify/src/**` | **用户硬约束** | 整个源不动 |
| `/home/ll/llmwikify/CHANGELOG.md` | 用户硬约束 | 同上 |
| `/home/ll/llmwikify/pyproject.toml` | 用户硬约束 | 同上 |
| `/home/ll/llmwikify/MIGRATION*.md` | 用户硬约束 | 同上 |

---

## 8. 风险与缓解

| 风险 | 严重度 | 缓解 |
|---|---|---|
| Phase 5 fixture path 假设 `repo_root = llmwikify/` | 中 | 改 `pathlib.Path(__file__).parents[N]` |
| `nanobot-ai<0.3.0,>=0.2.1` 与 llmwikify 的 nanobot 调用 API 不一致 | 中 | Phase 5 跑出 `ImportError` 时针对性修 |
| `extractors.web` 被 reference 但不在 vendor 列表 | 低 | sed regex 覆盖；如遗漏手工加 web.py vendor |
| 91 -> 90 test 文件数差 | 低 | 文档差异，cp 行为无影响 |
| LLM client B 方案需新写 adapter | 中 | fallback A 默认 vendor；省时 |
| `extract_paper.py` import 路径 `extractors.pdf.extract_pdf` | 低 | sed regex 一次改 |

---

## 9. 总验收（**subagent 全绿才算成功**）

| # | 命令 | 期望 |
|---|---|---|
| 1 | `grep -rn "from\s\+llmwikify\|import\s\+llmwikify" /home/ll/QuantNodes/QuantNodes/research/` | 0 行 |
| 2 | `grep -rn "from\s\+llmwikify\|import\s\+llmwikify" /home/ll/QuantNodes/tests/research/` | 0 行 |
| 3 | `pytest /home/ll/QuantNodes/tests/research/ -q` | > 90% pass |
| 4 | `git -C /home/ll/llmwikify status --short` | 仅 plan/MIGRATION_REPORT_<DATE>.md 新文件 |
| 5 | `ls /home/ll/llmwikify/plan/MIGRATION_REPORT_<DATE>.md` | 存在 |
| 6 | `ls /home/ll/QuantNodes/MIGRATION_TEST_LOG.md` | 存在 |
| 7 | `git -C /home/ll/QuantNodes branch --list \| grep dev/repro-merge-2026-07-04` | 存在 |
| 8 | `git -C /home/ll/QuantNodes log --branches --remotes \| grep dev/repro-merge-2026-07-04` | 不存在（**未推**）|

---

## 10. 下一步（用户决策后）

1. **用户审批 push**：把 `dev/repro-merge-2026-07-04` 推到 `sn0wfree/QuantNodes` origin
2. **合并到 master**：发 PR → review → merge
3. **quantnodes v4.0.0 发布**：breaking change（reproduction 整合）
4. **llmwikify v0.40.0**（不同轮次）：
   - 加 shim re-export to `src/llmwikify/reproduction/__init__.py`
   - 更新 `interfaces/server/http/*.py` imports → `quantnodes.research.X`
   - 更新 `interfaces/cli/commands/reproduce_cmd.py`
   - 删 `tests/reproduction/`（已迁）
   - CHANGELOG breaking change section
   - 新写 `docs/MIGRATION_v0.40.md`
5. **本文件归档**：实施完后移到 `docs/releases/v0.40-migration.md`
