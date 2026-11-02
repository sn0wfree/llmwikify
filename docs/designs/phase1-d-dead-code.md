# Phase 1 / D — 死代码清理（含两处实测更正）

日期: 2026-11-02 · 分支: v0.41-dev

## 架构评审的原始判断

方案 8 列出「清死代码：`unified/`（15 文件）、`research_engine/`（9 文件）、
`WikiCLI` 双轨」。动手前逐项实测，**两项判断有误**。

| 原判断 | 实测 | 处置 |
|--------|------|------|
| `apps/chat/research_engine/` 是 `sys.modules` 替换 shim → 死代码 | **不是**：`apps/chat/clarifier.py:13` 与 `apps/chat/harness/review.py:10` 在 import 它的 `llm_step` | 保留，不动 |
| `WikiCLI` 是意外的双轨 → 删除 | **不是**：有意的 backward-compat 公开 API（`llmwikify/__init__.py` 导出，供外部 `WikiCLI(...).X(args)`） | 保留，加显式弃用说明 |
| `apps/chat/agent/unified/` 生产零引用 → 死代码 | 判断正确 | **删除** |

## 删除内容

`src/llmwikify/apps/chat/agent/unified/` —— 13 文件 / 1,119 LOC：

| 文件 | 内容 |
|------|------|
| `core.py` | kernel.agent 的 re-export |
| `spec.py` | kernel.agent.spec 的 re-export + 一份死掉的 `ChatSpec` |
| `loop.py` / `steps/` / `pipelines/codegen.py` | 纯 shim |
| `events.py` | **第二份事件词表**（Phase 1/A 已改为 re-export） |
| `hook_adapter.py` | AgentHook(13) → UnifiedHook(16) 的桥接层（P1-02 双 Hook 体系的桥） |
| `registry.py` | mode 注册表 + `create_agent_loop` 工厂 |
| `handlers/chat_reasoner.py`、`handlers/tool_actor.py` | 被 `runner_v2` 取代的旧实现 |

**判据**：全 `src/` 精确扫描 `^\s*(from|import)\s+.*\bunified\b`（排除 unified 自身）
→ **零命中**。`kernel/agent/` 本身是活框架（`codegen_pipeline.py` 在用
`UnifiedAgentLoop`），只有 `apps/` 下这个 shim 包是死的。

## 保留活代码的测试覆盖

`test_unified_codegen.py` / `test_unified_codegen_extra.py` 通过 shim 测的是
**kernel 的活代码**（`generate_factor_code` / `UnifiedAgentLoop`），不能一起删。
处理：

- 重命名为 `test_codegen_pipeline.py` / `test_codegen_pipeline_extra.py`
- import 改指 `llmwikify.kernel.agent` / `llmwikify.kernel.agent.spec`
- 5 处 `create_agent_loop("codegen", llm_client=llm)` 内联为测试内的
  `_codegen_loop()` 助手（把 mode 注册表的 codegen 配置写出来：
  `CodegenReasoner` + `CodeActor` + `CheckSuccessStep`）

→ 端到端 codegen 循环测试全部保留，覆盖不降。

删除 7 个纯 shim 测试文件（测的是被删掉的死实现）：
`test_unified_chat.py` / `test_unified_chat_extra.py` / `test_unified_core.py` /
`test_unified_loop.py` / `test_unified_loop_extra.py` / `test_unified_registry.py` /
`test_unified_steps.py`

## WikiCLI：把「双轨」变成有意的决定

```python
class WikiCLI:
    """CLI command handler — **deprecated**, kept for backward compatibility.
    ...
    This class remains because it is part of the published API — it is
    re-exported from ``llmwikify/__init__.py`` — so it will not be
    removed without a major version bump. New methods must not be
    added here.
    """
```

## 回归网

`tests/test_chat_events_contract.py` 新增一条：
`test_there_is_no_second_event_vocabulary` —— 断言
`llmwikify.apps.chat.agent.unified` **不可导入**。第二份词表回来就会红。

## 验证

```
import llmwikify / runner_v2 / orchestrator      → ok
受影响测试失败清单                            → 无新增（少 8 项：被删文件的 polars 缺失失败）
基线失败 39 → 现 31
```

架构文档（HTML + md）同步更正了这两处判断。

## 顺带得到

- 第二份事件词表彻底消失（Phase 1/A 是改 re-export，这里是删文件）
- 双 Hook 体系的桥接层（`hook_adapter.py`）随 shim 一起消失
