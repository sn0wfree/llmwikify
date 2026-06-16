# llmwikify Agent 规约

> 8 原则受 [Karpathy 4 原则](https://github.com/forrestchang/andrej-karpathy-skills) 启发，
> 4 条为本项目实践沉淀。优先级高于 agent 默认行为。

## 核心原则

### 1. Think Before Coding（编码前思考）
不假设。多解就列出。困惑就停下问。资深工程师会嫌复杂就重写。

### 2. Simplicity First（简洁优先）
200 行能 50 行就重写。无推测功能、无单次抽象、无用不到的"灵活性"。

### 3. Surgical Changes（精准修改）
只动该动的。匹配现有风格。每一行 diff 可追溯到用户请求。
顺手重构 / 改格式 / 删预存死代码 = 禁止。

### 4. Goal-Driven Execution（目标驱动）
"修 bug" → "写复现测试，让它通过"。多步任务先列 [步骤] → [verify]。

### 5. Context First（上下文优先）
动手前 Read 完整实现、grep 同模式用法、graphify 查现成测试。
不假设 helper 是空的。

### 6. Verify-Then-Proceed（改完即验）
每 edit 后立即 `ruff check <file>`。改完一处就跑受影响的 `test_<name>.py`。
不攒到最后才发现 fixture 错。

### 7. Loop Until Done（循环到目标）
目标明确就循环到通过（ruff 干净 + pytest 全过 + 用户状态达成）。
不"差不多"就停。

### 8. Memory Hygiene（记忆清洁）
中文 commit `<type>(<scope>): 说明`。archive 不删（保留 rename）。
stash 遗留改动 commit 前主动提醒。

## 项目规约

**开发节奏**：3-5 边界测试 / helper，不写穷举；pre-edit grep 一次改全；commit 前 `git status + git diff --stat + ruff + pytest`。

**提交**：不主动 commit/push/PR，commit 后 stash 提醒。中文 message 风格 `fix(chat): 修复 /study reload 卡片丢失`。

**架构**：单一消息真源（业务数据绑 assistant message）；SSE 契约 `{type: 'save_warning'; reason}` 对齐 `ui/webui/src/api.ts:34`；SkillResult.ok 序列化为 `{"data":..., "status":"ok"}`；RunState 字段 `inputs_data (dict)` 非 `inputs`，时间戳是 float 非 ISO 字符串。

**LLM**：`api.minimaxi.com` ≤ 3 并发（6 触发 throttle）；流式重试仅初始连接；配置在 `~/.llmwikify/llmwikify.json`。

**服务器**：不用 `--reload`；启动 `llmwikify serve --web --port 8765 --host 0.0.0.0`；健康检查 `curl http://localhost:8765/api/health`。

**Skills & Subagents**：Skills 路径 `~/.llmwikify/skills/`；Subagent `.claude/agents/<name>.md` 默认 `isolation: worktree`；prompt 必备 角色 + 输入契约 + 输出契约 + 边界。
