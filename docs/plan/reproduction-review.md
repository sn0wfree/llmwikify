# 研报复现功能 — 评审材料

> 版本: v1.0
> 日期: 2026-06-12
> 用途: 评审重整规划、原则、决策的对照清单
> 状态: 等待评审
> 配套: `docs/plan/reproduction-realignment.md` v0.5.1, `docs/principles/reproduction-principles.md` v1.1

---

## A. 评审范围

本次评审覆盖：

| 文件 | 状态 |
|---|---|
| `docs/plan/reproduction-realignment.md` (v0.5.1) | 新建，等待评审 |
| `docs/principles/reproduction-principles.md` (v1.1) | 新建，等待评审 |
| 4 个实施决策 (1A/2A/3A/4A) | 定稿，等待评审 |
| 5 个 Stage 路线图 | 规划，等待评审 |

**不**在评审范围：v0.4 之前的历史 spec / dataflow / frontend-plan（视为历史背景，保留供参考）。

---

## B. 评审 Checklist（5 个维度 × 10 项强制）

每项勾 ✅/❌/✏️，❌ 需写明 issue。

### B.1 重整规划（realignment.md）

- [ ] 现状盘点 §3：12 项断链全部对得上代码
- [ ] 根因分析 §3.1：5 个根因（双轨制、路径硬编码、责任链、配置不同步、反馈环缺失）能解释所有断链
- [ ] 重整架构 §4：单一闭环图、5 子系统边界清晰
- [ ] 路径统一 §4.2：迁移脚本 idempotent 设计成立
- [ ] Schema 契约 §4.4：4 类 Page Pydantic 字段覆盖现有 frontmatter
- [ ] Stage 0-5 路线图 §5：每个 Stage 端到端可验证

### B.2 开发原则（reproduction-principles.md）

- [ ] 0 元规则：原则 vs 规范 vs 决策边界清楚
- [ ] 强度标注（🔒/⚠️/💡）一致：🔒 在 CI 强制，⚠️ 文档化豁免
- [ ] P1-P10 每条都有：陈述 / 规则 / 反模式 / 正模式 / 验收 / 业内参考
- [ ] 业内参考带原始引用（不是空泛"参考 Clean Code"）
- [ ] 附录 A 全景表覆盖 24 个业内原则，无 P1-P10 是凭空捏造
- [ ] 附录 C PR checklist 可直接复制到 PR template
- [ ] 附录 E 反例库指向真实代码（不是杜撰）

### B.3 4 个实施决策

- [ ] 决策 1A 迁移脚本设计 (idempotent / 错误处理 / 备份)
- [ ] 决策 2A QuantNodes 全替换风险（边界 case / baseline 对齐）
- [ ] 决策 3A 启动校验与路由 503 的契约清晰
- [ ] 决策 4A 5 个 PR 边界无重叠（每个 PR 独立可部署）
- [ ] 决策彼此不矛盾（决策 1 删 trading 别名 + 决策 2 QN 替换路径无冲突）

### B.4 端到端可执行性

- [ ] 每个 Stage 端到端验证命令可写（pytest / curl / 浏览器截图）
- [ ] 边界 case 已识别（HS300 缺 23 只、调仓日过滤、equity curve 缺失等）
- [ ] 失败时知道如何回退（每个 Stage 的回退点）

### B.5 风险与对策

- [ ] §6 风险表覆盖：LLM 质量、QN 兼容、路径迁移破坏、equity 状态机、trading calendar、数据缺失
- [ ] 每条风险有具体对策，不是"加强测试"这种空话
- [ ] 未识别的风险列在"未识别"区域（透明声明）

---

## C. 关键讨论记录（按时间序）

### C.1 起点：发现 n_stocks_per_date=12 的数字错位

| 发现 | 原因 |
|---|---|
| 调仓 12 次（应有 24） | `n_stocks_per_date` 在 IC 循环内 append，只统计 IC 有效日；`n_stocks_per_date` 被误用为"调仓日总数" |
| 截面 276/300 | router 阶段 23 只股票失败（数据问题，非 tradability 过滤） |
| longshort 全 0 | QuantNodes `daily_net_simp` 全 NaN → 我们的 ffill 后变成全 1.0 |
| group_metrics.n_stocks=0 | `memberships[first_d]` 取 dict 空（first_d 取值不对） |

→ 引出"这系统整体有问题，需要重新规划"的判断。

### C.2 重整规划 v0.5.0

确立 5 Stage 端到端路线图 + 10 项原则候选。

### C.3 原则合并 v1.0 → v1.1

P1-P4 独立文件 → 合并为 `reproduction-principles.md` 单一文件；补充 P5-P10；附录 5 块（全景表 / 重整对应 / PR checklist / 实践指南 / 反例库）；业内参考带原始引用。

### C.4 4 个决策定稿

| 决策 | 选项 | 理由 |
|---|---|---|
| 路径统一 | A 一次性删别名 | 符合 P6 兼容窗口=0 |
| QN 替换 | A 全替换 | 符合 P5 算法单一；baseline 对齐可控 |
| LLM 兜底 | A 启动时强校验 | 符合 P7 但强约束（避免 silent failure） |
| 提交节奏 | A Stage 0-5 5 个 PR | 符合 P4 端到端提交 |

---

## D. 跨文档一致性检查

| 检查项 | 期望 | 实际 |
|---|---|---|
| 枚举值名一致（`factor_class`） | spec.md / contracts.py / 代码 | 待 Stage 0 统一 |
| Wiki 目录名一致 | spec.md 写 `wiki/factor/`，代码读 `wiki/factors/` | spec 与代码脱节，Stage 0 修 |
| Stage 列表与 checklist 对应 | realignment §5 ↔ principles 附录 C | 5 Stage 都在 checklist 端到端项内 |
| 风险表与反例库对应 | realignment §6 ↔ principles 附录 E | 反例库标了"不来源"，决策落地后会被填满 |

---

## E. 未识别 / 待补充项

| 项 | 说明 | 处理时机 |
|---|---|---|
| 行业中性化 (FactorNeutralizeNode) | 决定不在本期范围（realignment §8） | 下一版规划 |
| LLM 评测（paper 提取质量） | 决定不在本期范围 | 决策 3A 落地后考虑 |
| 真实 QuantNodes PipelineRunner | 决定不在本期范围（factor-backtest-universe.md Step 2-3） | Stage 5 后另开规划 |
| 性能优化 | 决定不在本期范围（除非明显瓶颈） | Stage 5 |
| 跨语言 i18n | 决定不在本期范围 | 后续 |
| SLO / Error Budget | principles §11.4 提议但未实施 | Stage 5 |
| CI/CD 自动化 | principles §11.4 提议但未实施 | Stage 5 |

---

## F. 评审通过的下一步

| 评审结果 | 后续动作 |
|---|---|
| 全部 ✅ | 进入 Stage 0 实施：paths.py + contracts.py + router 注册 + LLM 健康校验 + 迁移脚本 |
| 部分 ✏️ | 修订后重新走一遍 checklist |
| 重大 ❌ | 重新走 C 阶段讨论，重写规划/原则 |

---

## G. 评审记录

| 评审者 | 日期 | 结论 | 备注 |
|---|---|---|---|
| (待填) | (待填) | (待填) | (待填) |
| (待填) | (待填) | (待填) | (待填) |

---

## H. 文档索引（评审涉及的所有文档）

| 文档 | 路径 | 版本 | 角色 |
|---|---|---|---|
| 重整规划 | `docs/plan/reproduction-realignment.md` | v0.5.1 | 路线图、决策、风险 |
| 开发原则 | `docs/principles/reproduction-principles.md` | v1.1 | P1-P10 原则 |
| 评审材料（本文） | `docs/plan/reproduction-review.md` | v1.0 | 评审对照 |
| 命名规范 | `docs/plan/reproduction-spec.md` | v0.4 | 历史 spec，待 Stage 0 修 |
| 数据流 | `docs/plan/reproduction-dataflow.md` | v0.4 | 历史背景 |
| 因子回测路线 | `docs/plan/factor-backtest-universe.md` | v0.4.1 | Stage 2 子参考 |
| 前端规划 | `docs/plan/reproduction-frontend-plan.md` | v0.4 | 暂未在本次评审 |
| 论文研报 | `docs/plan/paper-reproduction.md` | v0.4 | 暂未在本次评审 |
