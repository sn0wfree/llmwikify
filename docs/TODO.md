# TODO: Phase 3+ 优化待办

## 优先级: P1 (近期)

### 1. 复杂因子拆分为子因子

**背景**: 某些 alpha 代码实现复杂（如 decay_linear + indneutralize 组合），单个因子可能包含多个子逻辑。

**目标**: Phase 3 LLM 提取时识别复杂因子，建议拆分为子因子，便于理解和复现。

**方案**: 在现有 YAML 中添加 `sub_factors` 字段，记录子因子拆分建议（不创建新文件）。

**YAML 结构**:
```yaml
factor:
  sub_factors:
    - name: "子因子1名称"
      formula: "子因子1公式"
      description: "子因子1描述"
    - name: "子因子2名称"
      formula: "子因子2公式"
      description: "子因子2描述"
```

**修改点**:
1. SYSTEM_PROMPT_METADATA 添加 `sub_factors` 字段
2. SYSTEM_PROMPT_METADATA_V2 添加 `sub_factors` 字段
3. WebUI FactorDetail.tsx 显示子因子（可选）

**状态**: 待实施

---

## 优先级: P2 (中期)

### 1. QuantNodes Pandas 兼容

**背景**: QuantNodes 算子当前仅支持 Polars，pandas 用户无法直接使用。

**方案**: 双态算子方案，分批实施:
- Phase 1: time_ops (30 个算子)
- Phase 2: section_ops (40 个算子)
- Phase 3: math_ops + composite_ops (87 个算子)

**状态**: 待评估

### 2. 其他论文 Phase 1-3 合并输入

**背景**: 当前仅 101 Alphas 使用合并输入方案，其他论文（招商证券等）也应使用。

**状态**: 待实施

---

## 优先级: P3 (长期)

### 1. WebUI 因子库增强

- 子因子展示
- 因子对比功能
- 因子搜索优化

### 2. LLM 代码生成优化

- 多 LLM 对比
- 自动 prompt 优化
- 代码质量评估
