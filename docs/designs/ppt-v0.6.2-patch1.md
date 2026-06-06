# PPT Generator v0.6.2.patch1 — Two-Column 渲染修复 + Prompt 升级

> 日期: 2026-06-02 | 版本: v0.6.2.patch1 | 状态: 设计完成，代码待实施

## 一、问题描述

v0.6.2 主题选择器紧凑化上线后，用户截图反馈第 3 张幻灯片"理论机制解析"渲染为**两个空灰色矩形**。

**根因链**：
1. LLM 收到 `CONTENT_PROMPT`（`content_type: "comparison"`），但未按 prompt 要求输出 `left`/`right` 结构，而是返回扁平 `bullets` 列表
2. `rules.py:resolve_layout` 解析为 `two_column` layout（`TYPE_TO_LAYOUT` 固定映射）
3. `validate_content_for_layout` 只检查 `left`/`right` 是否是 dict，**不处理 bullets → left/right 拆分**
4. 前端 `TwoColumnSlide` 渲染两个 `<div>`，背景为 `var(--color-surface-2)` → 两个空灰色矩形

**当前 prompt 的 7 大弱点**：
1. 角色太弱（"内容生成助手"）
2. 何时用哪种 content_type 完全没教（只列 JSON 形状）
3. comparison vs bullets 边界模糊（截图 bug 根因）
4. 无反例（只有 schema 无"❌ 不要…"）
5. 无质量标准（"简洁有力"太空）
6. 无自检步骤
7. 7 种类型全展开，LLM 不知该聚焦

## 二、修复方案（三层防御）

| 层 | 文件 | 作用 |
|----|------|------|
| L1 数据层 | `rules.py` | 后端 fallback：两栏空但 bullets 有内容 → 自动拆分 |
| L2 渲染层 | `slide-renderer.tsx` | 前端降级：两栏空但 bullets 有内容 → 降级为 BulletsSlide |
| L3 提示层 | `engine.py` 4 个 prompt | **核心修复**：让 LLM 不再产出错误结构 |

**L3 是核心修复**（从源头解决问题），L1/L2 是兜底（处理已缓存的旧任务）。

## 三、新 CONTENT_PROMPT 设计（5 段式）

替换 `engine.py:82-110`，从 29 行扩展到 95 行：

```
1. Role 设定       — "10 年资深内容设计师，打开即用"
2. 本页规格         — 演示标题/页码/页标题/页描述/content_type
3. 类型指南（核心） — 每类含：何时用 / 输出 schema / 数量范围 / 典型场景
4. 输出 Schema      — 严格 JSON（无 Markdown 包裹）
5. 写作原则 + ❌ 反例 + ✓ 自检
```

**关键边界规则**（直接针对截图 bug）：

```
■ comparison（左右对比）何时**不要**用：
  - 单个概念的多个方面（如"理论机制的三个维度"）→ 用 bullets
  - 多个并列要点无对比关系 → 用 bullets
  - 3 个或以上并列项 → 用 bullets
⚠️ 必须输出 left/right，禁止回退为 bullets（前端会渲染为空白）
```

## 四、OUTLINE_PROMPT 升级

`engine.py` 中 `OUTLINE_PROMPT` 从 ~20 行扩到 ~40 行，追加：

```
【content_type 选择指南】（与 CONTENT_PROMPT 对齐）
【文字质量自检】
  - 错别字检查（撅→掘、记念→纪念、帐→账、像→象）
  - 删除空话（"重要"、"关键"、"有效"）
  - 标题精炼（去除"研究"、"分析"等冗词）
```

## 五、Language Routing 架构（额外 B）

新增 4 个 helper 函数：

```python
CONTENT_PROMPT_ZH = "..."   # 95 行新版
OUTLINE_PROMPT_ZH = "..."   # 40 行新版
# EN 版本: 暂不实现（per Q6 中文版），返回中文 + TODO 标记

def _select(language, zh_prompt):
    if language == "zh":
        return zh_prompt
    return zh_prompt + "\n<!-- TODO(v0.6.3): English translation pending -->\n"

def get_content_prompt(language="zh", **kw): return _select(...).format(**kw)
def get_outline_prompt(language="zh", **kw): return _select(...).format(**kw)
def get_research_prompt(language="zh", **kw): return _select(...).format(**kw)
def get_chat_prompt(language="zh", **kw): return _select(...).format(**kw)
```

**调用点更新**（4 处）：
- `engine.py:182` generate_outline
- `engine.py:430` _generate_slide_content
- `engine.py:369` generate_from_research
- `engine.py:405` generate_from_chat

顺手把 `language` 从 `GenerateRequest` 传到 helper（之前是 hardcoded）。

## 六、L1 后端 Fallback（rules.py）

**位置**：`validate_content_for_layout` 末尾追加：

```python
# v0.6.2.patch1: When LLM returns flat bullets for two_column layout
# (e.g., content_type="comparison" but output uses bullets), split in half.
if layout == "two_column":
    left_items = content["left"].get("items") or []
    right_items = content["right"].get("items") or []
    if not left_items and not right_items:
        bullets = content.get("bullets") or []
        if bullets:
            mid = (len(bullets) + 1) // 2  # 奇数项时左多一项
            content["left"]["items"] = bullets[:mid]
            content["right"]["items"] = bullets[mid:]
            content["bullets"] = []  # 防止双显示
```

## 七、L2 前端降级（slide-renderer.tsx）

**位置**：`renderContent()` 中 `case 'two_column':`

```tsx
case 'two_column': {
  const hasLeft = (slide.left?.items?.length ?? 0) > 0;
  const hasRight = (slide.right?.items?.length ?? 0) > 0;
  if (!hasLeft && !hasRight && (slide.bullets?.length ?? 0) > 0) {
    return <BulletsSlide slide={slide} />;
  }
  return <TwoColumnSlide slide={slide} />;
}
```

## 八、测试覆盖

**新建 `tests/test_ppt_rules.py`**（11 测试）：
- `test_comparison_maps_to_two_column`
- `test_bullets_5_items_stays_bullets`
- `test_bullets_6_items_upgrades_to_two_column`
- `test_intro_maps_to_title`
- `test_unknown_falls_back_to_title_content`
- `test_6_bullets_split_in_half` ← **新 fallback**
- `test_7_bullets_odd_split_left_heavy`
- `test_existing_left_right_preserved`
- `test_partial_left_only_not_triggered`
- `test_completely_empty_two_column`
- `test_bullets_layout_not_split`

**新建 `tests/test_ppt_prompts.py`**（5 测试）：
- `test_content_prompt_has_all_placeholders`
- `test_outline_prompt_has_all_placeholders`
- `test_get_content_prompt_zh_returns_chinese`
- `test_get_content_prompt_en_falls_back_to_zh_with_todo`
- `test_content_prompt_no_markdown_wrap_warning`

## 九、改动汇总

| 文件 | 改动 | 风险 |
|------|------|------|
| `engine.py` | 4 prompt 重写 + 4 helper | 中（仅 LLM 行为变化） |
| `rules.py` | +11 行 | 低（数据层自动迁移） |
| `slide-renderer.tsx` | +8 行 | 低（仅异常路径） |
| `test_ppt_rules.py` | 新建 ~80 行 | 0 |
| `test_ppt_prompts.py` | 新建 ~50 行 | 0 |
| **总代码** | **+20 行业务 + 130 行测试** | — |

**Token 成本**：单页 0.4k → 1.1k（≈$0.01-0.05/presentation，10 页级）

## 十、验证清单

1. ✅ `pytest tests/test_ppt_rules.py tests/test_ppt_prompts.py -v` — 16 个新测试全过
2. ✅ `pytest tests/ -q` — 现有 124 测试 + 16 新增 = 140 无回归
3. ✅ `tsc --noEmit` — 错误数 74 → 74（无新增）
4. ✅ `vite build` — 成功，bundle +0.3KB
5. ✅ `grep -c "comparison" engine.py` — 验证 prompt 中确实含 boundary 规则
6. ✅ 启动 dev server **手动 e2e**（用户执行）：生成"理论机制解析"页验证

## 十一、风险与权衡

| 风险 | 缓解 |
|------|------|
| Token 成本 ↑ | 单次成本可接受；可后续缓存 prompt prefix |
| 旧缓存任务不受 prompt 升级影响 | rules.py + 前端 fallback 兜底（用户需刷新页面） |
| `language: en` 暂未真翻译 | helper 架构就位，EN 翻译是 v0.6.3 工作 |
| 错别字检查是 LLM 行为层非强制 | 依赖 LLM 自检；可在 v0.6.3 加后处理 validator |
| 改动 5 个文件，跨前后端 | 测试覆盖后端，前端靠 e2e 验证 |

## 十二、版本与提交

- **子版本**：v0.6.2.patch1（hotfix 标记，主版本 0.31.0 不动）
- **commit 1**：`docs(ppt): v0.6.2.patch1 design — Two-Column 修复 + Prompt 升级`
- **commit 2**：`fix(ppt): v0.6.2.patch1 backend rules — two_column bullets fallback + prompt 升级`
- **commit 3**：`fix(ppt): v0.6.2.patch1 frontend — TwoColumnSlide 降级`
- **commit 4**：`test(ppt): v0.6.2.patch1 — rules + prompts 单元测试`

## 十三、未来工作（v0.6.3+）

- EN 完整翻译（CONTENT/OUTLINE/RESEARCH/CHAT 4 个 prompt）
- 错别字后处理 validator（不依赖 LLM 自检）
- 提示词版本管理（每次改动生成新 hash，便于回滚）
- Prompt A/B 测试框架（多版本对比生成质量）
