# 06 — 主动触发 wiki lint 8 rules

> 对应 [docs/TUTORIAL.md §Part 3 — 功能 Playbook 索引 (06 lint_8_rules)](../../docs/TUTORIAL.md#part-3--功能-playbook-索引)

## 跑法

```bash
cd examples/06_lint_8_rules
PYTHONPATH=../.. python3 play.py
```

## 目标

现有 `examples/01_personal_reading_notes` 只调 `wiki.lint()` 看 `issue_count`,
**没有主动构造场景触发各 rule**。这个 playbook 通过精心设计的内容触发
8 条 lint rule 中的核心几条,展示每条 rule 的实际触发条件和报告格式。

## 8 条 Rule 触发矩阵

| Rule | 触发条件 | 本剧本触发? | 备注 |
|---|---|---|---|
| `dated_claim` | wiki 页面引用年份 X, raw 源最新年份 Y, Y - X ≥ 2 | ✓ | 2018 vs 2024, gap 6 |
| `potentially_outdated` | 页面有 `(raw/...)` 引用, 年份距今 ≥ 2 | ✓ | 2019 距 2026 |
| `topic_overlap` | `Query:` 页面 jaccard ≥ 0.85 | · | 阈值/算法差异 |
| `missing_cross_ref` | 页面提到其他 topic 但无 `[[wikilink]]` | · | 需 wikilink 解析 |
| `contradiction` | 两页内容互相矛盾 (LLM 驱动) | · | 需 LLM 调用 |
| `redundancy` | 两页内容高度相似 | · | 需 LLM 调用 |
| `data_gap` (unsourced_claims) | 页面有断言但无 source 引用 | ✓ | 3 个页面 |
| `knowledge_gap` | 有 raw 源但无 wiki 页链接 | · | 路径需特定结构 |

3/8 rule 在本剧本中触发 (其中 `unsourced_claims` 是 `data_gap` 的子类型)。
其余 5 个需要 LLM 调用或特定 wikilink 结构, 不在 0-LLM 范围内。

## 涉及 API

- `llmwikify.create_wiki(path)` — 创建 wiki
- `wiki.write_page(name, content)` — 写页面
- `wiki.lint()` / `wiki.lint(mode="brief")` — 健康检查
- 内部 `kernel/wiki/lint/` — 8 个 rule class

## 预期输出 (节选)

```
=== Step 1: Write 2 pages with high content overlap (redundancy) ===

=== Step 6: Run wiki.lint() and group issues by rule ===

   Total issues (across all categories): 10

   [dated_claim] 1 issue(s):
      - company-info-2018: 'company-info-2018' references 2018, but the latest raw source is from 2024. The gap is 6 years. ...

   [potentially_outdated] 1 issue(s):
      - company-info-2018: 'company-info-2018' references 2019 as latest date. May need review with newer sources.

   [unsourced_claims] 3 issue(s):
      - machine-learning-basics: 'machine-learning-basics' contains 5 assertion(s) without cited sources

=== Step 8: Rule coverage summary (which fired) ===
   ✓ dated_claim
   ✓ potentially_outdated
   ✓ unsourced_claims
```

## 对应 TUTORIAL

- **TUTORIAL.md §1.6** — `wiki.lint()` 基础调用 (本剧本扩展)
- **ARCHITECTURE.md** — `kernel/wiki/lint/` 8 rules 概览
