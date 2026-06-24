# LLM Compile Loop v4 — 设计文档

> 创建时间：2026-06-10
> 状态：已实施（4 个模块 + 1 个修改）
> 版本目标：v0.37（Loop v4 主路径接入）
> 关联：`docs/designs/loop_v4_main_path_integration.md`

---

## 1. 背景

LLM Compile Loop v4 是将量化因子公式（LaTeX/自然语言）编译为可执行 `polars.Expr` 的 4 阶段循环。核心思路：

- **LLM 不直接生成可执行代码**，而是生成类型化的 AST JSON（Pydantic 校验）
- **确定性编译器**将 AST 转换为 `polars.Expr`，无运行时不确定性
- **多采样 + 结构化错误反馈**提升首次编译成功率

---

## 2. 4 阶段循环

```
┌─────────────────────────────────────────────────────────────┐
│ Stage 0: Build Self-Context Prompt                           │
│   factor YAML (L1-L4) + 5 hand-curated examples            │
│   → SYSTEM_PROMPT (自包含，无外部依赖)                       │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Stage 1: Multi-Sample K=3 → Extract → Compile               │
│   LLM K=3 samples → extract_ast() → compile_ast()           │
│   每个 sample 独立校验 + 编译                                │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Stage 2: First Valid Wins                                    │
│   3 个 sample 中第一个编译成功即返回                          │
│   全部失败 → 结构化错误反馈 → 重新 prompt                    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Stage 2.5: Complexity Check                                 │
│   check_complexity(ast, l2_steps) → COMPLETE / INCOMPLETE   │
│   INCOMPLETE → 重新 prompt（LLM 输出过于简化）               │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ Stage 3: Cache Successful AST                                │
│   ~/.llmwikify/factor_cache/{factor_hash}.json              │
│   后续调用直接从 cache 读取，跳过 LLM                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. AST 节点类型（`ast_nodes.py`）

### 3.1 设计

- Pydantic `BaseModel` 定义 `ASTNode`
- 157 个 QuantNodes 算子名作为 `Literal` 枚举（熵减 40%）
- 节点类型：`col`（列引用）、`lit`（字面量）、算子节点

### 3.2 节点结构

```json
{
  "op": "rolling_mean",
  "args": [{"op": "col", "value": "close"}],
  "kwargs": {"window": 20}
}
```

### 3.3 支持的算子类别

| 类别 | 示例 | 参数 |
|---|---|---|
| Leaf | `col`, `lit` | `value` |
| Arithmetic | `add`, `sub`, `mul`, `div`, `pow` | 2 args |
| Unary | `abs`, `sign`, `log`, `sqrt`, `neg` | 1 arg |
| Polars native | `pl_when`, `pl_max_h`, `pl_min_h` | 1-3 args |
| Rolling | `rolling_mean`, `rolling_std`, `rolling_corr` | 1-2 args + `window` |
| Time-series | `ts_argmax`, `ts_rank`, `ts_delta`, `ts_lag` | 1 arg + `periods` |
| EWM | `ewm_mean`, `ewm_std`, `ewm_corr` | 1-2 args + `span` |
| Cross-sectional | `rank`, `scale`, `zscore`, `winsorize` | 1 arg |
| QuantNodes (157) | 全部来自 `_OPERATOR_REGISTRY` | 各异 |

---

## 4. 确定性编译器（`ast_compiler.py`）

### 4.1 设计原则

- **无 LLM 参与**：纯函数 AST → `pl.Expr`
- **dispatch table**：`_ARITH_FNS`、`_POLARS_FNS`、`_QN_FNS` 三张表
- **结构化错误**：`CompileError(kind, message, context)`

### 4.2 编译流程

```python
def compile_ast(node: ASTNode, schema: dict) -> pl.Expr:
    """递归编译 ASTNode → polars.Expr."""
    if node.op in _LEAF_FNS:
        return _LEAF_FNS[node.op](node)
    if node.op in _ARITH_FNS:
        children = [compile_ast(a, schema) for a in node.args]
        return _ARITH_FNS[node.op](children)
    if node.op in _POLARS_FNS:
        children = [compile_ast(a, schema) for a in node.args]
        return _POLARS_FNS[node.op](node, children)
    if node.op in _QN_FNS:
        # QuantNodes 算子需要从 registry 查签名
        return _call_qn_op(node, schema)
    raise CompileError("UnknownOp", f"Operator {node.op!r} not in known operators")
```

### 4.3 Polars Native 算子（PR-3 扩展到 8 个）

| 算子 | 说明 |
|---|---|
| `pl_when` | 条件表达式 |
| `pl_max_h` | 水平最大值 |
| `pl_min_h` | 水平最小值 |
| `pl_concat_list` | 列表拼接 |
| `pl_str_contains` | 字符串包含 |
| `pl_str_length` | 字符串长度 |
| `pl_dt_year` | 年份提取 |
| `pl_dt_month` | 月份提取 |

---

## 5. AST 提取器（`ast_extractor.py`）

### 5.1 问题

LLM 输出不总是干净的 JSON。常见格式：
- Markdown fence：` ```json { ... } ``` `
- Chain-of-thought：先写推理，再输出 JSON
- Chatty prose：夹杂解释文字

### 5.2 解决方案：BAML-style SAP（Schema-Aligned Parsing）

```python
def extract_ast(raw_text: str) -> ASTNode:
    """从 LLM 输出中定位并解析 AST JSON."""
    # 1. 尝试 markdown fence
    m = _JSON_FENCE.search(raw_text)
    if m:
        return ASTNode.model_validate_json(m.group(1))
    # 2. 尝试裸 JSON
    m = _BARE_JSON.search(raw_text)
    if m:
        return ASTNode.model_validate_json(m.group(0))
    # 3. 尝试第一个 JSON 对象
    m = _FIRST_OBJECT.search(raw_text)
    if m:
        return ASTNode.model_validate_json(m.group(0))
    raise ExtractError("No valid JSON found in LLM output")
```

---

## 6. AST 复杂度检查（`ast_complexity.py`，Stage 2.5）

### 6.1 问题

LLM 有时输出简化的 AST（如只有 `diff` 而不是完整的 `rank(diff(returns, 3)) * correlation(open, volume, 10)`）。AST 编译成功但不匹配 L2 步骤数。

### 6.2 解决方案

```python
class ComplexityVerdict(Enum):
    COMPLETE = "complete"    # AST 可能代表完整表达式
    INCOMPLETE = "incomplete"  # AST 过小，需重新 prompt

def check_complexity(ast: ASTNode, l2_steps: int) -> ComplexityVerdict:
    """比较 AST 节点数与 L2 步骤数，判断是否完整."""
    node_count = count_nodes(ast)
    op_set = collect_ops(ast)
    # 启发式：节点数 >= l2_steps * 0.6 且包含所有预期算子
    if node_count >= l2_steps * 0.6:
        return ComplexityVerdict.COMPLETE
    return ComplexityVerdict.INCOMPLETE
```

---

## 7. 错误分类器（`error_categorizer.py`）

将原始异常转换为结构化 `{kind, message, suggestion}`，供重新 prompt 使用。

### 7.1 错误类别

| Kind | 触发条件 | 建议 |
|---|---|---|
| `UnknownOp` | 算子不在 157 个已知列表中 | 用已知算子替换 |
| `WrongArgCount` | 参数数量错误 | 检查算子元数 |
| `MissingKwarg` | 缺少必需 kwarg | 添加 window/periods/span |
| `UnknownKwarg` | 未知 kwarg | 移除多余 kwarg |
| `TypeMismatch` | 类型不匹配 | col.value 用字符串，lit.value 用数字 |
| `UnknownColumn` | 列名不存在 | 使用 schema 中的列名 |
| `QNCallFailed` | QuantNodes 算子调用失败 | 检查签名和 kwarg 类型 |
| `InvalidJSON` | LLM 输出非合法 JSON | 只输出 JSON |
| `SchemaValidation` | JSON 解析但 ASTNode 校验失败 | 每个节点需有 op/args/kwargs |
| `Other` | 其他错误 | 重新阅读 SYSTEM_PROMPT |

---

## 8. FactorCompiler（`factor_compiler.py`）

### 8.1 编译流程

```python
class FactorCompiler:
    """4 阶段循环的顶层编排."""

    def compile(self, factor_data: dict) -> CompileResult:
        # Stage 0: 构建 prompt
        prompt = self._build_prompt(factor_data)

        # Stage 1: Multi-sample K=3
        for iteration in range(self.max_iterations):
            samples = self.llm.generate(prompt, n=self.n_samples)
            for sample in samples:
                try:
                    ast = extract_ast(sample)
                    compile_ast(ast, self.schema)  # 确定性编译
                except (ExtractError, CompileError) as e:
                    error = categorize_compile_error(e)
                    continue
                # Stage 2.5: 复杂度检查
                if check_complexity(ast, l2_steps) == ComplexityVerdict.INCOMPLETE:
                    continue
                # Stage 3: 成功，缓存
                self._cache_result(factor_data, ast)
                return CompileResult(is_valid=True, code=ast_to_json(ast))

            # 全部 sample 失败 → 结构化错误反馈
            prompt = self._append_error(prompt, error)

        return CompileResult(is_valid=False, error_message="All iterations failed")
```

### 8.2 Mock 模式

`FACTOR_COMPILER_MOCK=1` 环境变量启用 mock 模式，跳过 LLM 调用，使用预定义 AST。用于测试和 benchmark。

---

## 9. ClickHouse 集成（`clickhouse_data.py`）

### 9.1 用途

从 ClickHouse `quote.cn_stock` 表获取 A 股日线数据，构建 QuantNodes 兼容的 HDF5 缓存。

### 9.2 连接信息

```
协议: clickhouse://default:***@0.0.0.0:8123/quote
端口: 9000 (native), 8123 (HTTP)
driver: clickhouse-driver 0.2.10
表: cn_stock
```

### 9.3 数据流

```
ClickHouse query → pd.DataFrame → HDF5 (stk_daily.h5 + index_daily.h5)
                                    ↓
                              QuantNodes factor_node 消费
```

---

## 10. 文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/llmwikify/reproduction/codegen/ast/nodes.py` | ~319 | Pydantic AST + 157 ops enum |
| `src/llmwikify/reproduction/codegen/ast/compiler.py` | ~192 | 确定性 AST → pl.Expr |
| `src/llmwikify/reproduction/codegen/ast/extractor.py` | ~60 | LLM output → AST JSON |
| `src/llmwikify/reproduction/codegen/ast/complexity.py` | ~50 | Stage 2.5 复杂度检查 |
| `src/llmwikify/reproduction/codegen/compiler.py` | ~638 | FactorCompiler 4 阶段编排 |
| `src/llmwikify/reproduction/common/errors.py` | ~156 | 结构化错误分类 |
| `src/llmwikify/reproduction/data_source/clickhouse.py` | ~182 | ClickHouse 数据加载 |

---

## 11. 关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| LLM 输出格式 | AST JSON（非代码） | 确定性编译，无运行时不确定性 |
| 校验方式 | Pydantic BaseModel | 类型安全 + 自动校验 |
| 重试策略 | 结构化错误反馈（非 raw traceback） | LLM 可理解并修复 |
| 多采样 | K=3 | 首次成功率 ~85%（实测） |
| 复杂度检查 | 节点数 vs L2 步骤数 | 防止 LLM 输出过于简化 |
| 缓存 | 本地 JSON 文件 | 跳过重复 LLM 调用 |
| ClickHouse | HTTP API | 无额外依赖，直接 urllib |

---

## 12. 实测结果

### 101 Alphas Benchmark

- **Mock benchmark**: 97/97 success（所有 alpha 都能编译）
- **LLM benchmark**: 1/1（alpha-014，32s，MiniMax-M2.7）
- **ClickHouse 集成**: 5 codes × 3 months = 270 rows + 256KB H5

### 已知限制

- LLM 输出 `<think>...</think>` 块需 strip
- LLM 偏好 `self.p.xxx`（path B 用 backtrader 时需容忍）
- `max_tokens=2000` 经常截断（建议 4000+）
