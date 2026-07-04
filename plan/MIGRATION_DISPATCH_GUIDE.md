# Migration — Dispatch Guide

> **状态**：in-flight 草案
> **使用**：派发 subagent 前必读 + 派发后核验
> **关联**：`.claude/agents/migration-quant.md`（subagent prompt）· `MIGRATION_DEPENDENCY_MAP.md`（依赖分析）

---

## 🚦 本文件的目的

用户已决定将 `llmwikify/reproduction/` 迁移到 `quantnodes/research/`，由 subagent 执行。本指南：

1. 帮用户决定**派发方式**
2. 提供派发前的**预检清单**
3. 提供派发后的**核验步骤**
4. 包含**回滚 / 失败处理**

---

## 1. 准备状态（**已 done**）

| 步骤 | 文件 | 状态 |
|---|---|---|
| ✅ 写 subagent prompt | `/home/ll/llmwikify/.claude/agents/migration-quant.md` | 已存在（~330 行）|
| ✅ 写依赖分析 | `/home/ll/llmwikify/plan/MIGRATION_DEPENDENCY_MAP.md` | 已存在 |
| ✅ 写派发指南（本文件）| `/home/ll/llmwikify/plan/MIGRATION_DISPATCH_GUIDE.md` | 已存在 |
| ✅ Dry-run 路径核对 | dry-run 报告见下 §6 | 已完成 |

---

## 2. 派发前 5 步预检（**用户来核**）

| # | 检查 | 命令 | 期望 |
|---|------|------|------|
| 1 | subagent prompt 文件存在 | `ls /home/ll/llmwikify/.claude/agents/migration-quant.md` | 文件存在 |
| 2 | 本指南存在 | `ls /home/ll/llmwikify/plan/MIGRATION_DISPATCH_GUIDE.md` | 存在 |
| 3 | 依赖分析存在 | `ls /home/ll/llmwikify/plan/MIGRATION_DEPENDENCY_MAP.md` | 存在 |
| 4 | llmwikify 工作树干净 | `cd /home/ll/llmwikify && git status --short` | 仅 plan/ 新文件 |
| 5 | Python 3.11 可用 | `/usr/bin/python3.11 --version` | `Python 3.11.x` 或更高 |

---

## 3. 派发方式（**3 种选 1**）

### 方式 A — Claude Code / opencode `task` tool

```python
# 在 Claude Code 会话窗口中：
task(
  description="迁移 reproduction → quantnodes",
  prompt=$(cat /home/ll/llmwikify/.claude/agents/migration-quant.md),
  subagent_type="general"
)
```

或（手动粘贴）：
```python
task(
  description="迁移 reproduction → quantnodes",
  prompt=<粘贴 .claude/agents/migration-quant.md 整段文本>,
  subagent_type="general"
)
```

**优点**：Claude Code 原生集成，进度自动回报 main 会话。
**缺点**：依赖用户当前会话系统支持。

### 方式 B — Claude Code CLI 后台

```bash
# 启动一个独立 Claude Code 会话跑这个 subagent
cd /home/ll/llmwikify
claude-code --task "$(cat .claude/agents/migration-quant.md)" \
  --isolation worktree \
  --output-json
```

**优点**：独立会话，可后台运行，用户可同时做别的。
**缺点**：需要在终端手动启。

### 方式 C — 手动执行（**不推荐，仅作 fallback**）

按 subagent prompt 内容逐步执行：
```bash
# Phase 1
if [ ! -d "/home/ll/QuantNodes/.git" ]; then
  git clone https://github.com/sn0wfree/QuantNodes.git /home/ll/QuantNodes
fi
cd /home/ll/QuantNodes
# ... (后续按 subagent prompt Phase 1-6 顺序执行)
```

**优点**：完全控制进度。
**缺点**：耗时（手动预计 8-12 小时），易出错。

---

## 4. 推荐：用方式 A（task tool 派发）

因为：
- 自动汇报进度（用户能监视）
- 自动隔离（worktree 隔离避免污染主仓）
- 自动错误处理
- 派发后用户可同时做其它事

---

## 5. 派发命令模板

### 5.1 派发到 Claude Code

```
派发 subagent 完成 llmwikify/reproduction/ → quantnodes/research/ 迁移。

使用 subagent_type="general"。
完整 prompt 见文件：/home/ll/llmwikify/.claude/agents/migration-quant.md（已 ~330 行）。

预期耗时：~6-8 小时。
预期结果：
- /home/ll/QuantNodes/QuantNodes/research/ 下新增 16 子目录 + 5 vendored deps
- pytest tests/research/ > 90% pass
- /home/ll/llmwikify/src/** 0 行被修改
- 仅 1 个新文件写入 llmwikify/plan/: MIGRATION_REPORT_<DATE>.md
- 不推任何 origin

完成后请用 subagent 的"Final Output Format"格式汇报。
```

### 5.2 在 Claude Code 中实际派发

直接在主对话窗口说：

```
请用 task tool 派发 subagent：
- description: "迁移 reproduction → quantnodes"
- subagent_type: "general"
- prompt: <粘贴 .claude/agents/migration-quant.md 整段>
```

或者：

```
请执行 .claude/agents/migration-quant.md 描述的 subagent 任务（隔离模式 worktree）。
```

---

## 6. Dry-Run Findings（**已完成**）

派发前已对子 agent 的假设做 read-only 验证：

### 6.1 路径存在性（全部 ✅）

```
✅ /home/ll/llmwikify/.git
✅ /home/ll/llmwikify/src/llmwikify/reproduction (16 sub-dirs, 119 .py files)
✅ /home/ll/llmwikify/src/llmwikify/kernel/codegen/{feedback_templates, code_tools, json_extract, prompts}.py
✅ /home/ll/llmwikify/src/llmwikify/kernel/agent/hook.py (UnifiedHook 定义)
✅ /home/ll/llmwikify/src/llmwikify/foundation/llm/client.py
✅ /home/ll/llmwikify/src/llmwikify/foundation/extractors/ (5 files)
✅ /home/ll/llmwikify/scripts/{aggregate_alpha_results, analyze_alpha_results, cross_validate_factor, deep_compare_alphalens, merge_alpha_data, run_101_alphas_v2, validate_alphalens, validate_backtrader, validate_qn_nodes}.py (9/9)
✅ /home/ll/llmwikify/examples/05_paper_to_factor/ (4 files)
✅ /usr/bin/git + /usr/bin/python3.11
✅ QuantNodes/research/ 在 GitHub 已存在（含 wiki.py / report_reproducer.py / factor_test/ / quant_alpha/ / _legacy_3c/）
```

### 6.2 调整项（subagent prompt 已反映）

| 调整 | 原文 | 修正后 |
|---|---|---|
| 子目录数 | "24 子包" | "**16 子目录**" |
| 测试文件数 | "91 文件" | "**90 文件**" |
| 外部依赖处数 | "5 处 vendor" | "**5 处 vendor**（6 个源文件，含 extract_paper.py）" |
| Phase 3 verification regex | `^from llmwikify\.reproduction`（漏缩进）| 改用 `grep -rn "llmwikify\.reproduction\." ... | grep -E "from\|import"` |

### 6.3 Python 版本

- `/usr/bin/python3` = Python 3.10.12（默认）
- `/usr/bin/python3.11` = **3.11.x**（满足 quantnodes requires-python=">=3.11"）
- subagent prompt Phase 1.3 已明确指引用 `/usr/bin/python3.11`

---

## 7. 派发后立即监控

subagent 开始执行后，**用户/主 agent 应监控**：

| 信号 | 含义 | 动作 |
|---|---|---|
| `[1/6]` 进度回报 | Phase 1 开始 | 无需动作 |
| `[2/6]` 进度回报 | Phase 2 物理迁移完 | 检查文件数对不对 |
| `[3/6]` 进度回报 | Phase 3 import 改写完 | 检查 0 残留 |
| `[4/6]` 进度回报 | Phase 4 外部 dep 处理完 | 检查 vendor 文件存在 |
| `[5/6]` 进度回报 | Phase 5 测试结果 | **关键节点**：看 passed/skip/failed 比例 |
| `[6/6]` 进度回报 | Phase 6 报告写完 | 准备进入验收 |
| `MIGRATION COMPLETE` | 最终 | 检查报告 + log |

如 subagent 超 4 小时无进度（Phase 5 卡死）→ 见 §9 失败处理。

---

## 8. 派发后验收（**用户必做**）

subagent 报 `MIGRATION COMPLETE` 后，用户应跑这些命令验证：

```bash
# === 1. 文件结构 ===
ls /home/ll/QuantNodes/QuantNodes/research/ | head
# 期望: 看到 paper_understanding/ + backtest_pkg/ + codegen/ + ... 共 16+ 目录 + 现有 wiki.py / report_reproducer.py

# === 2. import 残留 ===
grep -rn "from\s\+llmwikify\|import\s\+llmwikify" \
  /home/ll/QuantNodes/QuantNodes/research/ \
  2>/dev/null
# 期望: 0 行

# === 3. llmwikify 干净 ===
cd /home/ll/llmwikify
git status --short
# 期望: 只有 plan/MIGRATION_REPORT_<DATE>.md 一个新文件

# === 4. 报告存在 ===
ls /home/ll/llmwikify/plan/MIGRATION_REPORT_<DATE>.md
cat /home/ll/llmwikify/plan/MIGRATION_REPORT_<DATE>.md
# 期望: 报告内容详尽，含 PASSED/SKIPPED/FAILED 数字

# === 5. 测试日志 ===
ls /home/ll/QuantNodes/MIGRATION_TEST_LOG.md
tail -30 /home/ll/QuantNodes/MIGRATION_TEST_LOG.md
# 期望: pytest 输出最后几行

# === 6. 提交存在但未推 ===
cd /home/ll/QuantNodes
git log --oneline dev/repro-merge-2026-07-04 | head -3
git log --oneline origin/dev/repro-merge-2026-07-04 2>&1 | head
# 期望: 本地分支有 commit；origin 分支不存在（**未推**）

# === 7. pytest 实际跑（独立核验）===
cd /home/ll/QuantNodes
pytest tests/research/ -q --timeout=120 2>&1 | tail -5
# 期望: 通过率 ≥ subagent 报告

# === 8. quantnodes 现状未动 ===
cd /home/ll/QuantNodes
diff <(git show master:QuantNodes/research/wiki.py) QuantNodes/research/wiki.py
git status QuantNodes/research/wiki.py QuantNodes/research/report_reproducer.py \
          QuantNodes/research/factor_test QuantNodes/research/quant_alpha \
          QuantNodes/research/_legacy_3c 2>&1
# 期望: 0 改动
```

---

## 9. 失败处理（subagent 中途崩 / 报告 FAILED）

### 9.1 报告 `FAILED` 或 `PARTIAL`

1. **用户读** `/home/ll/llmwikify/plan/MIGRATION_REPORT_<DATE>.md` 的 "Issues / Outstanding" 段
2. **看** `/home/ll/QuantNodes/MIGRATION_TEST_LOG.md` 末尾 pytest 报错
3. 决定：
   - **a.** 修 subagent prompt → 重新派发（参数 `-retry` 或新 subagent）
   - **b.** 用户手动补完 Phase 5-6
   - **c.** 回滚（见 §9.2） + 重新设计

### 9.2 回滚方案

```bash
# 安全回滚：subagent 没 push，所有改动都在本地分支
cd /home/ll/QuantNodes

# 选项 A: 保留 work 但撤销 commit
git reset --soft HEAD~1

# 选项 B: 完全删除分支（包括文件）
git checkout master
git branch -D dev/repro-merge-2026-07-04

# 选项 C: 删整个 quantnodes 目录（极端情况）
rm -rf /home/ll/QuantNodes/QuantNodes/research/codegen /home/ll/QuantNodes/QuantNodes/research/common
git checkout master
git branch -D dev/repro-merge-2026-07-04
```

**注**：选项 C 前应 `ls /home/ll/QuantNodes/QuantNodes/research/` 确认现有内容（wiki.py / report_reproducer.py / factor_test/ / quant_alpha/ / _legacy_3c/）未受污染。

### 9.3 subagent 跑超时

| 时长 | 动作 |
|---|---|
| 1-2 小时 | 正常，等 |
| 3-4 小时 | 检查进度：subagent 是否在 Phase 5 卡 pytest fixture |
| 5+ 小时 | 取消 subagent，看报告 → 决定回滚或手动收尾 |

---

## 10. 关于 push 与 merge（**不在本轮**）

subagent 完成后的 push/merge 决策由用户做出。本轮边界：

- ❌ subagent **不推** origin（用户偏好"先不慌的push"）
- ❌ subagent **不合并** master
- ❌ subagent **不发** v4.0.0

下一轮（用户决定时）：

1. 用户 push `dev/repro-merge-2026-07-04` → `origin`
2. 用户（或 PR review）合并到 `master`
3. 发 quantnodes v4.0.0 → PyPI
4. 实施 llmwikify v0.40.0（不同任务）

---

## 11. 关于本指南 / 依赖分析 / subagent prompt 的更新

如发现 prompt 有 bug 或 prompt 应调整：

1. 在 `/home/ll/llmwikify/.claude/agents/migration-quant.md` 修改
2. 在 `/home/ll/llmwikify/plan/` 留下变更说明（不动 CHANGELOG）
3. 重新派发 subagent（带新 prompt）

---

## 12. 检查清单 (✓/✗)

派发前 user 核对：

- [ ] `/home/ll/llmwikify/.claude/agents/migration-quant.md` 存在
- [ ] `/home/ll/llmwikify/plan/MIGRATION_DEPENDENCY_MAP.md` 存在
- [ ] `/home/ll/llmwikify/plan/MIGRATION_DISPATCH_GUIDE.md` 存在
- [ ] Python 3.11 可用
- [ ] llmwikify 工作树除了 plan/ 新文件外干净
- [ ] 已读 dry-run findings（§6）
- [ ] 已确认派发方式（A task tool / B CLI / C 手动）

派发中主 agent 监控：

- [ ] Phase 1-6 进度回报按时收到
- [ ] Phase 5 测试结果 >= 80% pass

派发后 user 验收：

- [ ] §8 全部 8 条验证命令通过
- [ ] 报告文件 + 日志可读
- [ ] llmwikify/src/** 0 行被修改（最强证据 = `git diff --name-only`）
