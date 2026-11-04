# 中优契约修复 — skill 信封 / list_runs / wiki write 校验

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查中优契约类

## 问题与修复

### 1. `status: "executed"` 信封未被消费方解包

确认流（posthoc / approve）返回：
```json
{"status": "executed", "result": {"status": "ok", "data": {...}}}
```
但 `orchestrator` 和 `chat_persistence` 只认 `status == "ok"` 的
SkillResult 信封，导致 `run_id` 提取失败（research_run_started 不发）。

**修复**：新增 `_unwrap_skill_payload()` 统一解包三种信封
（ok / executed 嵌套 / 裸 dict），两处消费方改用它。

### 2. `list_runs` 只 glob `wf_*.json`

`save()` 写 `{run_id}.json`（任意前缀），但 `list_runs` 只列
`wf_*` 前缀——自定义 run_id 永远列不出。

**修复**：改 glob `*.json`（atomic write 的临时文件后缀 `.tmp`
不会匹配）。

### 3. wiki write / confirm 裸 `body.get()` 无校验

- `wiki_write_page` / `wiki_write_page_by_id`：`page_name` 缺失
  默认 `""`，静默写空页名
- `approve_confirmation`：裸 `json.loads`，类型不校验

**修复**：
- 新增 `WikiWritePageRequest`（`page_name` min_length=1 必填）
- 新增 `ConfirmApproveRequest`（保留 response 静默纠正语义，
  不改成 422）

## 不改（评估后）

- **`SkillResult.data` 形状不统一**（wiki_query 包 `result` vs 平铺）：
  消费方已按 skill 各自适配（`detect/_base.py` 读 `.result`），
  统一会破坏现有消费方，留待大版本
- **`stop_reason` 裸 str**：纯类型标注，无运行时影响

## 验证

- 新增 `tests/test_contract_fixes.py`（18 tests）
- 相关回归：persistence / run_store / confirmation / orchestrator
  与 stash 基线一致（2 个 research_skill failed 为既存）
