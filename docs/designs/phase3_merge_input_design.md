# Phase 3 合并输入设计文档

## 背景

Phase 3 (LLM 元数据提取) 当前从零提取 L2/L3/L4/L6，但对于其他论文（如招商证券），Phase 1 (pass2) 已经提取了 L2/L3/L4。这导致：
1. 重复 LLM 调用
2. 可能产生不一致的元数据
3. 浪费计算资源

## 目标

Phase 3 不是重新提取，而是基于 Phase 1 输出进行"验证 + 补全 + 增强"。

## 架构设计

```
Phase 1 输出 (pass2.json)
    ↓ 读取 l2/l3/l4
Phase 3 输入: formula_brief + code + 已有 l2/l3/l4
    ↓ LLM 验证 + 补全 + 增强
Phase 3 输出: 验证后的 l2/l3/l4 + 新增 l6
    ↓ 深度合并
YAML 文件 (保留 Phase 1 的 l1, 合并 l2/l3/l4, 新增 l6)
```

## 修改清单

| 文件 | 修改内容 | 行数估计 |
|------|---------|---------|
| `factor_extractor.py` | SYSTEM_PROMPT_METADATA → V2 + `_process_one` 合并逻辑 + 深度合并写入 | ~80 行 |
| `run_101_alphas.py` | 无改动（Phase 3 命令不变） | 0 行 |

## 详细设计

### 1. SYSTEM_PROMPT_METADATA_V2

```python
SYSTEM_PROMPT_METADATA_V2 = """你是量化研究助手, 负责验证和补充 factor metadata.

给定:
  - formula_brief: 原始 alpha 公式
  - code: Python 实现
  - 已有元数据 (来自研报提取): l2, l3, l4 (可能为空)

任务:
1. 验证已有 l2/l3/l4 是否准确 (如有错误请修正)
2. 补充缺失字段
3. 新增 l6 (风险分析)

输出严格的 JSON (用 ```json ... ``` 包裹), 字段如下:

```json
{
  "verified": true,  // 如果已有元数据完全正确, 设为 true
  "l2": { ... },
  "l3": { ... },
  "l4": { ... },
  "l6": { ... }
}
```

要求:
- 如果已有元数据准确, 设 verified=true, 只补充缺失字段
- 如果发现错误, 修正并设 verified=false
- l6 必须新增 (Phase 1 不提取)
- 全部中文输出 (除 JSON 字段名)
- 必须用 ```json``` 包裹输出"""
```

### 2. extract_factor_metadata 修改

新增 `existing_metadata` 参数：

```python
def extract_factor_metadata(
    llm: Any,
    formula_brief: str,
    code: str,
    existing_metadata: dict | None = None,  # 新增
    temperature: float = 0.3,
    max_retries: int = 1,
) -> dict:
```

用户 prompt 构建：
- 无已有元数据：当前行为
- 有已有元数据：添加到 prompt，要求验证 + 补全

### 3. _process_one 合并逻辑

新增 `_load_phase1_metadata` 函数：
- 搜索 `pass2.json` 文件
- 匹配 alpha_index
- 提取 l2/l3/l4

### 4. 深度合并写入

```python
def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base。"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

写入逻辑：
```python
for layer_key in ("l2", "l3", "l4", "l6"):
    if layer_key in metadata and isinstance(metadata[layer_key], dict):
        existing_layer = existing["factor"].get(layer_key, {})
        merged = _deep_merge(existing_layer, metadata[layer_key])
        existing["factor"][layer_key] = merged
```

### 5. extract_batch 修改

新增 `papers_dir` 参数，传递给 `_process_one`。

## 执行流程

1. 读取 `single_factor_NNN.json` (formula_brief + code)
2. 搜索 `pass2.json` 找到对应 alpha 的 Phase 1 输出
3. 提取已有 l2/l3/l4
4. 调用 LLM: formula_brief + code + 已有 l2/l3/l4
5. LLM 返回: verified + l2/l3/l4 (验证后) + l6 (新增)
6. 深度合并: YAML 已有 l1 + Phase 1 l2/l3/l4 + Phase 3 l2/l3/l4/l6
7. 写入 YAML

## 测试用例

| 测试场景 | 输入 | 预期输出 |
|---------|------|---------|
| 101 Alphas (无 Phase 1 l2/l3/l4) | formula_brief + code | LLM 生成完整 l2/l3/l4/l6 |
| 招商证券 (有 Phase 1 l2/l3/l4) | formula_brief + code + l2/l3/l4 | LLM 验证 + 补全 l6 |
| 部分缺失 (只有 l2) | formula_brief + code + l2 | LLM 补全 l3/l4/l6 |

## 预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 101 Alphas L3 | 空 | 有内容 |
| 其他论文 L6 | 缺失 | 补全 |
| LLM 调用次数 | 99 次 | 99 次 (不变) |
| 元数据质量 | 无验证 | LLM 验证 + 增强 |

## 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM "修正"正确的 Phase 1 输出 | 元数据被错误覆盖 | verified 字段 + 深度合并保留已有 |
| pass2.json 格式不一致 | 无法读取 Phase 1 输出 | `_load_phase1_metadata` 返回 None，回退到当前行为 |
| LLM 调用成本 | 99 次调用 ~60s/次 | 可接受，与当前一致 |
