# llmwikify Agent 规约

> 8 原则受 [Karpathy 4 原则](https://github.com/forrestchang/andrej-karpathy-skills) 启发，
> 4 条为本项目实践沉淀。优先级高于 agent 默认行为。

## 核心原则

### 1. Think Before Coding（编码前思考）
不假设。多解就列出。困惑就停下问。资深工程师会嫌复杂就重写。
**When in doubt, ask。** 停下来，说出困惑，问清楚再动手。

### 2. Simplicity First（简洁优先）
200 行能 50 行就重写。无推测功能、无单次抽象、无用不到的"灵活性"。

### 3. Surgical Changes（精准修改）
只动该动的。匹配现有风格。每一行 diff 可追溯到用户请求。
顺手重构 / 改格式 / 删预存死代码 = 禁止。
发现无关死代码 → **提，不删**。发现无关未跟踪文件 → **不动，除非用户请求**。

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

### Before Acting Checklist（操作前清单）
**每次修改文件/删除/提交前，必须过这 5 步：**

1. 这个操作需要做吗？（YAGNI — 不需要就别做）
2. 这是用户明确请求的吗？（未请求 → 不动）
3. 会影响其他文件吗？（grep 改动范围）
4. 改完后 ruff / test 会过吗？（验证）
5. 用户确认了吗？（commit/删除/大改动必须确认）

## 项目规约

**开发节奏**：3-5 边界测试 / helper，不写穷举；pre-edit grep 一次改全；commit 前 `git status + git diff --stat + ruff + pytest`。

**提交**：不主动 commit/push/PR。用户说「commit」/「提交」/「git」时，**先列出要提交的文件清单 + diff stat，等用户确认**。commit 前必须 `git status` 并报告 untracked 文件。stash 遗留改动 **commit 前主动提醒**。中文 message 风格 `fix(chat): 修复 /study reload 卡片丢失`。

**commit 前 checklist（缺一不可）**：
1. `git status` → 报告所有变更 + untracked
2. `git diff --stat` → 列出实际改了什么
3. ruff check（相关文件）
4. pytest（相关测试）
5. 用户确认文件清单
6. 确认 stash / untracked 处理方式

**架构**：单一消息真源（业务数据绑 assistant message）；SSE 契约 `{type: 'save_warning'; reason}` 对齐 `ui/webui/src/api.ts:34`；SkillResult.ok 序列化为 `{"data":..., "status":"ok"}`；RunState 字段 `inputs_data (dict)` 非 `inputs`，时间戳是 float 非 ISO 字符串。

**LLM**：`api.minimaxi.com` ≤ 3 并发（6 触发 throttle）；流式重试仅初始连接；配置在 `~/.llmwikify/llmwikify.json`。

**服务器**：不用 `--reload`；启动 `llmwikify serve --web --port 8765 --host 0.0.0.0`；健康检查 `curl http://localhost:8765/api/health`。

**WebUI 构建**：改 `ui/webui/src/**` 后必须 `cd ui/webui && npm run build`（或 `pnpm build`），仅 `tsc --noEmit` 类型检查不会更新 `ui/webui/dist/assets/AgentChat-*.js` 等 bundle；浏览器会继续加载旧 hash 的 chunk，源码修复"看不见"。dist/ 在 `.gitignore` 里不入仓，但 serve 时被 FastAPI 静态挂载到 `/assets/*`。验证：`grep -c "final_response" ui/webui/dist/assets/AgentChat-*.js` 应返回 0。

**Skills & Subagents**：Skills 路径 `~/.llmwikify/skills/`；Subagent `.claude/agents/<name>.md` 默认 `isolation: worktree`；prompt 必备 角色 + 输入契约 + 输出契约 + 边界。

**CompositeHook**（`foundation/callback/`）：新增 agent 钩子必用 `AgentHook` 基类（13 钩子点：wants_streaming / before_iteration / on_stream / on_stream_end / emit_reasoning / emit_reasoning_end / before_execute_tools / after_tool_executed / on_tool_error / on_confirmation / after_iteration / finalize_content / on_error）；`CompositeHook` fan-out 错误隔离（async 方法自动 try/except log warning，`finalize_content` 透传异常）；业务 hook 放 `integrations/` 子包（WikiHook / DreamSyncHook / AutoIngestHook）。

**ChatRunner**（`apps/chat/agent/runner.py`）：dataclass 输入用 `ChatRunSpec`（~18 字段，含 microcompact 配置），输出用 `ChatRunResult`（final_content / messages / tools_used / usage / stop_reason / error / compacted_count / total_compacted_chars_saved）；Runner 是 ReActEngine + ChatReActBridge 的薄包装, 不替代主循环；新业务流（Harness / Research / Track B）优先 `ChatRunner.run_to_completion(spec)`，避免直接 new ReActEngine；新 spec 字段加到 `ChatRunSpec`（含 microcompact 子段）而非塞 ReActConfig。

**microcompact**（`apps/chat/agent/microcompact.py`）：默认 ON（`spec.microcompact=True`），`microcompact_keep_chars=1000`；`microcompact_compactable_tools` 默认 `DEFAULT_COMPACTABLE_TOOLS`（read_file / exec / grep / find_files / web_search / web_fetch / list_dir，借鉴 nanobot v0.2.1 `_COMPACTABLE_TOOLS`）；marker 格式 `[Tool result compacted] Tool: ... Original: N chars Kept: M chars ID: ...`；原结果缓存 `spec._compacted_results[call_id]`（per-run 内存，run 结束 GC）；DB 持久化与 observation 生成仍用原 result, 仅 `conversation_messages.append` 用 marker。
