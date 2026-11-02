# Phase 1 / B — 显式能力声明（替换隐式契约）

日期: 2026-11-02 · 分支: v0.41-dev

## 问题

架构评审的 P1-03 与 P1-05：两处「不写对就静默失效」的隐藏契约。

### P1-03 lint 快照

`kernel/wiki/lint/__init__.py` 用反射决定规则能否走快照路径：

```python
if type(self).run is not Rule.run:          # 规则自己实现了 run()
    return self.run(wiki)
if type(self)._iter_pages is not Rule._iter_pages:
    return self.run(wiki)
```

新规则作者若覆写了 `run()` 而不知道这条隐藏协议，**快照优化静默失效**——
退回逐页读盘，没有任何提示。

### P1-05 Skill 白名单

`apps/agent/tools/skill_adapter.py` 硬编码一份暴露名单：

```python
default_exposed = ["dynamic_workflow", "autoresearch_compound",
                    "web_search", "web_fetch"]
```

新注册的 skill 默认**调不到**，且不知道该找谁改——「注册了却调不到」的最常见坑。

## 方案

### lint：`Rule.snapshot_mode`

```python
class Rule:
    snapshot_mode: ClassVar[str] = "template"   # 或 "custom"
```

| 值 | 含义 |
|----|------|
| `"template"` | 通用逐页模板；规则只实现 `detect()`，天然支持快照 |
| `"custom"` | 规则自己实现 `run()`，同时自己实现 `run_with_snapshot()` |

反射判断全部删除，改读声明。当前 8 条规则：

| 规则 | 模式 | 原因 |
|------|------|------|
| `DataGapsRule` / `OutdatedPagesRule` | template | 只实现 `detect()` |
| `DatedClaimsRule` | custom | 先扫 raw 目录 |
| `KnowledgeGapsRule` | custom | 自定义 source 候选集 |
| `QueryPageOverlapRule` | custom | 需要页面 stem 而非 display name |
| `RedundancyRule` | custom | 只需页面名，不要正文 |

### Skill：`Skill.exposed`

```python
class Skill(ABC):
    exposed: bool = False   # 默认内部，显式 opt-in
```

策略从 adapter 搬到 skill 自身，`SkillRegistry.exposed_names()` 汇总，
adapter 向注册表询问。当前暴露的 4 个 skill 标记 `exposed = True`：
`web_search` / `web_fetch` / `dynamic_workflow` / `autoresearch_compound`。

`subagent` **不**标记：它的暴露依赖 `SubagentManager` 是否存在，
仍由 adapter 条件添加（`SubagentSkill.exposed` 保持 False 并注明原因）。

## 回归网

`tests/test_capability_declarations.py`（16 项）：

**lint 侧**

1. `snapshot_mode` 只能是两个已知值（拼错不会静默关闭快照）
2. `"template"` 规则**不得**覆写 `run()` / `_iter_pages()` / `_load_pages()`
   —— 声明与实现矛盾时报错（这正是原反射藏起来的情况）
3. `"custom"` 规则**必须**自己实现 `run_with_snapshot()`
4. `"custom"` 规则**必须**覆写 `run()`（否则声明自相矛盾）
5. 模板规则与自定义规则都非空（否则代码路径是死的）

**skill 侧**

6. `Skill.exposed` 默认 False
7. `registry.exposed_names()` == 声明了 `exposed=True` 的 skill 集合
8. adapter 的默认暴露集 == 注册表的声明集
9. adapter 不暴露未 opt-in 的 skill（逐个工具核对 `_name_map`）
10. 调用方显式传 `exposed_skills` 仍然优先
11. 旧版注册表（无 `exposed_names`）不崩溃，且不静默暴露工具
12. `exposed_names()` 有序
13. 4 个对外 skill 仍暴露 / 6 个内部 skill 仍不暴露

## 验证

```
pytest tests/test_capability_declarations.py        → 16 passed
pytest test_lint_snapshot + counts + subagent_wire   → 75 passed
计数门禁 cold 311/2 未变（反射移除不改变行为）
大范围回归失败清单与基线逐条一致（少 2 个 flaky 计时用例）
ruff check                                          → clean
```

## 副作用

`tests/test_apps_agent_skill_adapter_subagent_wire.py` 的 mock 注册表需要
提供 `exposed_names()`——契约变了（策略从 adapter 移到 skill），测试随之更新。
生产代码无行为变化：暴露的工具集合与改动前完全相同。
