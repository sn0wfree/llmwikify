# mypy 基线复测与分批修复计划 · 2026-11-06

> 承接 [feature-completeness-2026-11.md](feature-completeness-2026-11.md) **C3**。
> 决策（2026-11-06）：本轮只做**配置清理**，702 错出分批报告、**不修**。

---

## 1. 实测（mypy 2.4.0，`mypy src/llmwikify`，414→415 文件）

| 口径 | 结果 |
|---|---|
| 豁免清单生效时 | **140 错 / 34 文件**（清理后 141，见 §3） |
| 关闭全部 `ignore_errors` | **702 错 / 147 文件** |
| 豁免掩盖量 | **562 错 / 113 文件** |
| 配置原注释 | 「681 错 / 138 文件」（2026-10-14）→ **已过期** |

## 2. 错误构成（702）

| 类型 | 数量 | 占比 | 修复性质 |
|---|---:|---:|---|
| `no-any-return` | 230 | 33% | 机械：补返回类型标注 / `cast` |
| `no-untyped-def` | 103 | 15% | 机械：补参数与返回标注 |
| `attr-defined` | 65 | 9% | **需判断**：可能藏真 bug |
| `arg-type` | 43 | 6% | **需判断**：可能藏真 bug |
| `misc` | 37 | 5% | 逐个看 |
| `var-annotated` / `has-type` / `assignment` | 73 | 10% | 半机械 |
| `func-returns-value` / `return-value` / `override` | 64 | 9% | 需判断（`override` 21 条集中在 `foundation/callback/composite.py`） |
| `union-attr` | 16 | 2% | 需判断 |
| `import-not-found` / `import-untyped` | 29 | 4% | **环境**：本机缺 `types-PyYAML` 等（dev 依赖已含），装依赖即消 |
| 其余 | 22 | 3% | — |

> `import-*` 29 条**不要用 `ignore_missing_imports` 掩盖**——`types-PyYAML>=6.0`
> 已在 `[project.optional-dependencies].dev`，完整安装环境下不报。

## 3. 已完成：配置清理（本轮）

| 动作 | 结果 |
|---|---|
| 删除 21 个失效 `ignore_errors` 条目 | `apps/chat/db/*` → 已迁 `apps/chat_db/*` 等，mypy 自报 unused-section |
| 删除 4 个 unused 三方条目 | `networkx` / `networkx.*` / `pyvis.*` / `community`（networkx 已自带类型） |
| 刷新基线注释 | 681/138 → 实测 140/34 与 702/147 |

**验证**：`unused section(s)` 警告消失；逐文件比对 **仅 `apps/wiki/tool_registry.py` 6→7**，其余 33 个文件错误数零变化。该 +1 来自同批 P0 修复（越界相对导入改绝对导入）后 mypy 才能解析 `RelationEngine`，暴露出 `_graph_action` 里 5 个真实类型错（返回 `list` 却标 `dict`、`str | None` 传给 `str`）——属真问题，已计入下表。

## 4. 分批计划（累计，按错误数降序）

| 批 | 范围 | 错误数 | 累计 | 备注 |
|---|---|---:|---:|---|
| 1 | top 10 文件 | 222 | 31% | `research_delegate` 33（32 条机械）· `runner_v2` 33 · `research/runner` 27 |
| 2 | top 11–30 | 184 | 46% | 含 `composite.py` 12 条 `override`（hook 协议对齐，一次修完） |
| 3 | top 31–80 | 205 | 73% | 分 2–3 个 commit |
| 4 | 其余 67 文件长尾 | 91 | 100% | 单文件多为 1–2 错 |

**节奏**：每批 = 从豁免清单摘除该批模块 → 修到 0 → `mypy` 复验 → 独立 commit（可单独回滚）。任一批修不完就停在该批，清单保持可回滚状态。

## 5. Top 30 文件

```
 33  apps/chat_db/research_delegate.py       no-any-return:32
 33  apps/chat/agent/runner_v2.py            func-returns-value:18, attr-defined:6
 27  apps/research/runner.py                 has-type:24
 22  apps/chat/memory/__init__.py            no-any-return:16, valid-type:5
 21  apps/chat/skills/research_skill.py      misc:14
 20  apps/research/actions.py                no-untyped-def:12, union-attr:5
 18  apps/chat_db/wiki_delegate.py           no-any-return:17
 18  apps/wiki/service.py                    no-any-return:13
 16  interfaces/server/http/wiki/wiki_routes.py  no-untyped-def:16
 14  kernel/wiki/mixins/core/init.py         attr-defined:8
 12  foundation/callback/composite.py        override:12
 12  apps/chat/agent/orchestrator.py         arg-type:8, index:3
 12  kernel/graph/analyzer.py                no-untyped-def:8
 11  interfaces/server/http/middleware.py    no-any-return:7
 11  kernel/wiki/mixins/io/page_io.py        attr-defined:5
 11  kernel/wiki/mixins/io/source_analysis.py  attr-defined:7
 10  kernel/wiki/mixins/analysis/lint.py     no-any-return:10
  9  kernel/storage/watcher.py               no-untyped-def:6, import-not-found:2
  9  kernel/multi_wiki/remote.py             return-value:8
  9  kernel/wiki/protocols.py                unused-ignore:9
  9  kernel/wiki/mixins/core/utility.py      no-any-return:3, override:3
  9  apps/research/engine.py                 no-untyped-def:6, arg-type:3
  8  foundation/config.py                    no-any-return:3, index:2
  8  interfaces/server/utils/webui.py        no-any-return:6
  8  apps/agent/maintenance/auto_ingest.py   union-attr:4, arg-type:2
  8  kernel/wiki/mixins/analysis/llm.py      no-any-return:5, attr-defined:3
  7  kernel/codegen/code_tools.py            import-not-found:3, attr-defined:3
  7  foundation/llm/resolver.py              no-any-return:5
  7  apps/chat/agent/builtin_commands.py     attr-defined:4, arg-type:1
  7  apps/research/reasoner.py               return-value:4
```

## 6. 复现

```bash
# 豁免生效
mypy src/llmwikify                       # 期望 141 错 / 34 文件
# 全量（临时配置，不动仓库）
python -c "import re,pathlib; t=pathlib.Path('pyproject.toml').read_text(encoding='utf-8'); pathlib.Path('/tmp/noexempt.toml').write_text(re.sub(r'(?m)^(ignore_errors = true)\$', r'# \\1', t), encoding='utf-8')"
mypy --config-file /tmp/noexempt.toml src/llmwikify   # 期望 702 错 / 147 文件
```
