# QuantNodes Migration (v0.40)

llmwikify v0.40 把 quant 模块（paper / factor / reproduction / backtest / strategy / quant-related docs）全部迁到 [quantnodes](https://github.com/sn0wfree/quantnodes)（本地: `/home/ll/Public/QuantNodes`）。

## 迁走的资源 (2026-07-06, Plan D Phase 11)

| 类别 | 数量 | 目标位置 |
|------|------|----------|
| React .tsx 组件 (backtest/factor/paper/reproduction/strategy) | 30 | `quantnodes/frontend/src/_archived_react/components/` |
| React shared 图表 | 12 | `quantnodes/frontend/src/_archived_react/components/shared/` |
| shadcn/ui (Radix) 组件 | 25 | `quantnodes/frontend/src/_archived_react/components/ui/` |
| lib util (cn, posNegColor) | 2 | `quantnodes/frontend/src/_archived_react/lib/` |
| lib API (paper, reproduction) | 2 | `quantnodes/frontend/src/_archived_react/lib/` |
| design docs (从 pre tag 恢复) | 3 | `quantnodes/docs/_migrated_from_llmwikify/designs/` |
| design docs (mv 自 docs/designs) | 8 | 同上 |
| plan docs (mv 自 docs/plan) | 10 | `quantnodes/docs/_migrated_from_llmwikify/plan/` |
| research docs (mv 自 docs/research) | 2 | `quantnodes/docs/_migrated_from_llmwikify/research/` |
| principles docs (mv 自 docs/principles) | 1 | `quantnodes/docs/_migrated_from_llmwikify/principles/` |
| poc docs (mv 自 docs/poc) | 1 | `quantnodes/docs/_migrated_from_llmwikify/poc/` |
| archive docs (mv 自 docs/archive) | 2 | `quantnodes/docs/_migrated_from_llmwikify/archive/` |
| 顶级 docs (TUTORIAL, quantnodes, tutorials/real_world_scenarios) | 3 | `quantnodes/docs/_migrated_from_llmwikify/` |
| repro_*.yaml (从 pre tag 恢复) | 22 | `quantnodes/quant/prompts/_repro_from_llmwikify/` |
| fixtures (engle_2002, fama_french_1993) | 2 | `quantnodes/quant/fixtures/` |
| screenshots (backtest, factor) | 2 | `quantnodes/docs/screenshots/` |
| migration-quant agent | 1 | `quantnodes/.agent/archive/migration-quant.md` |
| **合计** | **128** | - |

## 状态

- **llmwikify v0.40.0-dev**: 核心保留 **Knowledge + Chat + Research Assistant** 三块
- **quantnodes 接收**: 64 React 代码 + 30 docs + 22 yaml + 2 fixtures + 2 screenshots + 1 agent
- **迁移后**: llmwikify 净减 **~10,000 行** quant 相关代码

## WebUI 5 redirect 路由 (llmwikify)

仍在 `ui/webui/src/App.tsx`：
- `/reproduction` `/paper` `/factor` `/strategy` `/backtest`
- 全部跳转到 `/agent/chat?notice=*-moved-to-quantnodes`

## quantnodes Vue 3 重写任务

64 个 React .tsx 文件需要在 quantnodes 重写为 Vue 3 + ECharts + Ant Design Vue。详见 `quantnodes/frontend/src/_archived_react/README.md` 路线图。

## 引用

- quantnodes 仓库: `/home/ll/Public/QuantNodes`
- 完整迁移 commit: `git log --all --oneline | grep "Plan 11\|Phase 11"`
- v0.40 release notes: `plan/v0.40-release-notes-draft.md`
- migration agent: `.opencode/agents/archive/migration-quant.md`
