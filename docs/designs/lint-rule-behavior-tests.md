# Lint 规则行为测试补强

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查高优 #3

## 问题

1. **弱断言**：`tests/scenarios/test_06_lint_rules.py` 5 个测试只断言
   `"issues" in result`——`lint()` 永远返回该 key，规则是否触发完全不验证。
   docstring 宣称的 `unsourced_claims / orphan_page / broken_link`
   也不在断言范围内。
2. **零覆盖**：`DataGapsRule` / `OutdatedPagesRule` / `KnowledgeGapsRule` /
   `PotentialContradictionsRule` 4 条规则在 tests/ 中无任何
   `run`/`detect` 行为调用（仅 import 冒烟）。

## 修复

### test_06 弱断言 → 强断言

- 新增 `_rule_types(result)` 递归收集 lint 结果中所有 `type` 字段
- 每个测试断言**具体规则 type 出现**，失败时打印实际 types
- `dated_claim` 测试补 raw 源（该规则需要 `latest_source_year` 才能触发）
- `potentially_outdated` 测试补 `(raw/...)` 引用 + 5 年前年份
- `unsourced_claims` 测试补足 3 条长断言行（`MIN_ASSERTIONS_FOR_GAP`）

### 新增 tests/test_lint_rules_behavior.py（19 tests）

| 规则 | 触发 | 不触发 |
|---|---|---|
| DataGapsRule | unsourced_claims（3+ 长断言无 Sources）、vague_temporal | 有 Sources / 断言不足 / 无模糊词 |
| OutdatedPagesRule | 有 raw 引用 + 年份差 ≥2 | 无 raw 引用 / 年份新鲜 |
| KnowledgeGapsRule | sources/ 无 wikilinks → isolated_source | 有 wikilinks / 无 sources 目录 |
| PotentialContradictionsRule | value_conflict / year_conflict / negation_pattern | 干净 wiki |
| lint 集成 | data_gaps 路由到 `investigations.data_gaps` | brief 模式返回 issue_count |

## 关键发现

- `data_gaps` / `contradictions` / `outdated_pages` / `knowledge_gaps`
  在 `lint()` 结果的 **`investigations` 子 dict** 下，不在顶层
- `DatedClaimsRule` 在无 raw 源时直接返回 `[]`（`latest_source_year==0`）

## 验证

- `test_lint_rules_behavior.py` 19 passed
- `test_06_lint_rules.py` 5 断言全过（5 个 teardown ERROR 为既知 SQLite 锁）
- ruff 通过
