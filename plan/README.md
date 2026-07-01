# Plan

`plan/` 目录存放**已批准但未实施**的设计/重构方案 (in-flight 草案)。

## 目录规则

| 状态 | 走向 |
|---|---|
| 草案（待实现） | 留在 `plan/` |
| 实施中 | 移到 `docs/designs/<name>.md` + 标注 "WIP" |
| 已实施 | 移到 `docs/releases/vX.Y.Z.md` 或 `docs/designs/done/` |
| 废弃 | 移到 `docs/archive/plans/` + 加日期 |

## 当前内容

| File | 状态 | 关联 |
|---|---|---|
| `multi_factor_paper.md` | 草案（待实现） | reproduction/ 101_alphas 多因子提取流程 |

## 与 `docs/designs/` 的区别

- `docs/designs/`: 已确定要做的设计稿（WIP / 已完成）
- `plan/`: 还在讨论阶段，**未进入设计 / 实施** 的草案

> 草案落地后立即迁移到 `docs/designs/`，本目录仅留 in-flight 项。
