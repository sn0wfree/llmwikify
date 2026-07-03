<!-- agents-sync managed · edit locally, then: agents-sync push -->

# llmwikify Agent 规约

> **v1.3.0** · **最后审查**: 2026-07-02 · **下次审查**: 2026-10-02 (3 个月)
> **Gist 源**: https://gist.github.com/sn0wfree/4496c389faca9f3a2de36fb23aa37fa1
> **维护者**: sn0wfree
>
> 8 原则受 [Karpathy 4 原则](https://github.com/forrestchang/andrej-karpathy-skills) 启发，
> 4 条为本项目实践沉淀。优先级高于 agent 默认行为。

## 变更日志

### v1.3.0 (2026-07-02)
- 新增原则 9（Safety First / 破坏性操作红线）
- Before Acting Checklist +2 项（docker 状态 + dry-run 强制）
- 添加"教训记录"段：2026-07-02 docker 误删事故
- 加版本号 + 审查周期头部
- 加"维护政策"段
- 由 agents-sync 工具托管

### v1.2.0 (2026-06-15)
- 新增 microcompact 规范
- ChatRunner / CompositeHook / ChatReActBridge 规则

### v1.1.0 (2026-05-20)
- 8 核心原则（Karpathy 4 + 项目沉淀 4）

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

### 9. Safety First（破坏性操作红线）

**`docker` / `pkill` / `rm -rf` / `git push --force` 永远指定目标，禁止模糊匹配。**

| 禁止 | 必须替代为 | 原因 |
|------|-----------|------|
| `docker rm -f $(docker ps -aq)` | `docker rm -f <container_id>` | `ps -aq` 包含**所有**容器（含其他服务），`-f` 强删 = 误杀 |
| `pkill -f <pattern>` | `kill <pid>` 或 `pkill -x <exact_name>` | `-f` 匹配整条命令行，可能误杀同名进程 |
| `rm -rf $path`（变量未引号） | 先 `ls "$path"` 确认范围，加 `set -e` 早停 | 变量未引号 = 灾难 |
| `git push --force` | 永远先 `git status` + `git log --oneline` | 误覆盖他人提交 |

**debug 卡住进程的顺序**：
1. `docker logs <id>` / `docker exec <id> ps aux` 看具体卡哪
2. `docker stop <id>`（指定单个，给 10s 优雅停）
3. 实在不行才 `docker kill <id>` + `docker rm <id>`（指定单个）
4. **绝不**用 `$(docker ps -aq)` 或 `pkill -f` 一锅端

## Before Acting Checklist（操作前清单）
**每次修改文件/删除/提交前，必须过这 7 步：**

0. （**docker/systemd/全局进程**）先 `docker ps` / `ps aux` 列出**当前所有**在跑的容器/进程，操作前报告「会动哪些」给用户
0. （**破坏性批量命令**）`rm -f <list>` 类必须先 dry-run（`docker ps -q --filter name=...` 列出）再执行
1. 这个操作需要做吗？（YAGNI — 不需要就别做）
2. 这是用户明确请求的吗？（未请求 → 不动）
3. 会影响其他文件吗？（grep 改动范围）
4. 改完后 ruff / test 会过吗？（验证）
5. 用户确认了吗？（commit/删除/大改动必须确认）

## 教训记录

### 2026-07-02：误删所有 docker 容器

**事故**：`docker rm -f $(docker ps -aq)` 用于停一个卡住的测试容器，但 `ps -aq`
**返回了所有 25+ 个容器**（含 opencode-nginx-proxy、insight-trendradar、
quantnodes-mysql、caddy、redis 等），全部被 `-f` 强删。容器配置（端口、env、
卷挂载）随实例消失。

**根因**：
1. `ps -aq` 本身没错，错在**用 `-f` + 模糊匹配**做破坏性操作
2. 没有先看 `docker ps` 报告"我要操作哪些容器"
3. 卡住进程时直接用全局命令，没有先用 `docker logs <id>` debug

**修复**：
- 镜像 + 数据卷**全部还在**（没误删），可重建容器
- 重建需 35+ 个 compose 文件 + 启动参数（部分通过 `/home/ll/Public/*/docker-compose.yml` + `/home/ll/Public/opencode_ngnix/start.sh` 找到）
- 部分服务配置无法恢复（需凭记忆或文档）

**预防**：见原则 9（破坏性操作红线）+ Before Acting Checklist 第 0 项。
详见 `DOCKER_RECOVERY_NOTES.md`。

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

## 维护政策

1. **审查周期**：每 3 个月（或重大事故后立即）
2. **修订流程**：
   - `agents-sync edit` 改本地
   - `agents-sync push` 推 gist（公开可见）
   - 其他机器 `agents-sync pull` 同步
3. **冲突解决**：在 gist 评论段讨论；分歧无法调和时 revert
4. **过期清理**：标记 DEPRECATED 的规则 6 个月后删除
5. **跨项目兼容**：任何规则如果只对单个项目有效，加 `[project: <name>]` 标签

## 架构分层 (G+Y 2026-06-30 commit b83b472..c..+)

依赖方向（单向，禁止反向）:
```
interfaces  →  apps, kernel, reproduction, foundation
apps        →  foundation, kernel
kernel      →  foundation              ← 严格不依赖 apps/reproduction
reproduction → foundation, kernel      ← 不依赖 apps
foundation  →  (self only)
```

包职责:
- `foundation/` — 零依赖基础设施 (LLM 协议/callback/extractor)
- `kernel/agent/` — 通用 agent 框架 (UnifiedAgentLoop / StepHandler / Hook / Spec)
- `kernel/codegen/` — LLM 代码生成工具 (extract/validate/execute)
- `kernel/{wiki,graph,search,storage}/` — 知识图谱相关
- `apps/` — 应用层 (chat/wiki/research)，含 chat-specific 业务逻辑
- `reproduction/` — 量化复现管线 (paper→factor→backtest→report)
- `interfaces/` — 入口层 (CLI/MCP/HTTP)

禁止:
- `kernel/ → apps/` 任何 import (含 runtime lazy)
- `foundation/ → kernel/apps/reproduction/`
- `reproduction/ → apps/` 任何 import
- `kernel/quant/` 业务命名（已删）

backward-compat shim 保留:
- `apps/chat/agent/unified/` — 通用框架已迁 kernel/agent/, 此处为 shim
- `apps/chat/agent/execution_context.py` — AgentExecutionContext 已迁 kernel/agent/
- `kernel/quant/llm_client.py` — build_llm_client 已下沉 foundation/llm/client.py

验证:
- `python scripts/check_architecture.py` 必须 0 violation
- 反向依赖 grep 必须为空
- 422+ tests 通过

<!-- /agents-sync -->