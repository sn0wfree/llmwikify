# llmwikify 升级设计文档 — Loop v4 主路径接入 + 4 层抽象算子体系

> **配套项目**: QuantNodes (PR-QN-1/2/3, 详见 `~/Public/QuantNodes/docs/25-LLM算子层升级设计.md`)
> **本文档**: llmwikify 侧的所有改动设计
> **状态**: 设计完成，等待实施
> **版本目标**: llmwikify v0.37

## 0. 背景与动机

### 0.1 现状

llmwikify Loop v4 已实施（commits `225b650 / fdd68e9 / c5cf44b`），包含：
- `ast_nodes.py` (Pydantic AST, 157 ops enum)
- `ast_compiler.py` (deterministic dispatch)
- `ast_extractor.py` (LLM output → AST)
- `ast_complexity.py` (Stage 2.5)
- `error_categorizer.py` (8 类结构化)
- `factor_compiler.py` (4 阶段 orchestrator)
- `clickhouse_data.py` (HTTP → H5)

但 Loop v4 **未接入主路径**（仅 101 Alphas benchmark 使用）：
- `/api/factor/{slug}/backtest` 走 free-form CodeSandbox (Python eval)
- `/api/paper/start` multi-factor branch kwargs bug（5 个未知参数）
- 主路径完全没有 LLM 编译能力

### 0.2 战略目标

**Loop v4 作为主路径**，同时引入**4 层抽象算子体系**：

| 层 | 归属 | 实施位置 |
|----|------|---------|
| Primitive（157+ ops） | QuantNodes | 直接复用 |
| Polars Native（pl.when / pl.max_h 等）| **llmwikify** | `ast_nodes.py` 已有 3 个，扩展到 6-8 个 |
| Composite（DAG 模板）| **QuantNodes** | 用 PR-QN-3 提供的 API |
| Semantic（业务语义）| **llmwikify** | 新建 `semantic_registry.py` |
| Self-Repairing Compiler | **llmwikify** | 新建 `self_repairing_compiler.py` |

### 0.3 业界对标

- **Loop v4 design** (`docs/designs/llm_compile_loop_v4.md`): 已规划的 4 阶段循环
- **Self-Repair** (Reflexion / CRITIC): 自我修复机制
- **AlphaAgent** (KDD'25): AST-similarity rejection
- **R&D-Agent-Quant** (NeurIPS'25): 3-agent + dynamic op discovery

---

## 1. 升级总览（7 个 PR）

| PR | 标题 | 行数 | 工作量 | 风险 |
|----|------|------|--------|------|
| **PR-1** | 替换私有 API（`_OPERATOR_REGISTRY` → `get_operator`）| -2 / +2 | 5 min | 🟢 极低 |
| **PR-2** | 声明 QuantNodes 依赖（pyproject.toml）| +5 | 5 min | 🟢 极低 |
| **PR-3** | Polars Native ops 扩展（6-8 个）| +30 | 0.5 day | 🟢 低 |
| **PR-4** | Loop v4 主路径接入（factor.py + paper.py）| ~200 | 1.5 day | 🟡 中 |
| **PR-5** | Semantic Registry（50 op, YAML 配置）| +300 | 2 days | 🟡 中 |
| **PR-6** | Self-Repairing Compiler（5 FixStrategy）| +350 | 1 day | 🟡 中 |
| **PR-7** | Loop v4 系统收尾 + clickhouse 合并 + telemetry | +200 | 1 day | 🟡 中 |
| **总计** | — | ~1100 行 | **~7 days** | 中 |

---

## 2. 项目依赖与现状

### 2.1 当前依赖问题

llmwikify 当前 `pyproject.toml:14` **没有声明 QuantNodes 依赖**：

```toml
[project]
dependencies = [
    "jinja2",
    "pyaml",
    "requests",
    # ⚠️ 缺少 quantnodes 声明
]
```

**隐患**：新克隆项目会 `ImportError: No module named QuantNodes`。

### 2.2 私有 API 依赖

`ast_compiler.py:89` 和 `quantnodes_repro.py:442` 使用 **QuantNodes 私有 API**：

```python
# 当前（不推荐）：
from QuantNodes.operators.proxy import _OPERATOR_REGISTRY  # 带下划线 = 私有
```

应改为 **公共 API**（PR-QN-3 后 `get_composite_spec` + `is_composite_op` 可用）。

### 2.3 与 QuantNodes 公共 API 的对接

```python
# 下行接口（llmwikify → QuantNodes），全部使用 Public API：
from QuantNodes.factor_node.factor_functions import (
    get_operator,           # Primitive ops
    list_operators,         # 列出 ops
    operator_info,          # op 元信息
    register_operator,      # @decorator
)
from QuantNodes.operators import (
    is_composite_op,        # Composite ops (PR-QN-3)
    get_composite_spec,
    list_composite_ops,
    get_composite_doc_for_llm,
)
from QuantNodes.ai.sandbox import CodeSandbox
from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner
from QuantNodes.database_node import ClickHouseNode
```

---

## 3. PR-1: 替换私有 API（5 min）

### 3.1 背景

llmwikify 用了 2 处 QuantNodes 私有 API（带下划线），上游改名会爆。

### 3.2 改动

**文件 1**: `src/llmwikify/reproduction/ast_compiler.py:89`

```python
# 现状：
from QuantNodes.operators.proxy import _OPERATOR_REGISTRY

# 改后：
from QuantNodes.factor_node.factor_functions import get_operator
from QuantNodes.operators import is_composite_op, get_composite_spec
```

**文件 2**: `src/llmwikify/reproduction/quantnodes_repro.py:442`

```python
# 同上替换
```

### 3.3 行为差异

无。`get_operator()` 与 `_OPERATOR_REGISTRY[cat][name]["func"]` 行为完全一致。

### 3.4 测试

```bash
# 现有测试应全部通过
pytest tests/reproduction/test_quant.py -v
FACTOR_COMPILER_MOCK=1 python tests/ab_testing/test_101_quantnodes.py --limit 5
```

### 3.5 风险评估

- 🟢 极低（公共 API 等价替换）

---

## 4. PR-2: 声明依赖（5 min）

### 4.1 改动

**文件**: `pyproject.toml`

```toml
[project]
dependencies = [
    "jinja2",
    "pyaml",
    "requests",
]

[project.optional-dependencies]
quant = [
    "quantnodes>=2.7.0",  # NEW: 需要 PR-QN-3 合并后的版本
]
dev = [
    "pytest>=8.0",
    "ruff>=0.1",
    "quantnodes>=2.7.0",  # NEW: dev 模式自动包含
]
```

### 4.2 README 补充

```markdown
## 安装

```bash
# 基础安装（无 quant）
pip install -e .

# 完整安装（含 QuantNodes）
pip install -e ".[quant]"
```

QuantNodes 依赖是 **可选的**：未安装时 llmwikify 仍可运行大部分功能（factor library / L5 validation / Wiki），但无法跑 backtest。
```

### 4.3 风险评估

- 🟢 极低（pure addition）

---

## 5. PR-3: Polars Native ops 扩展（0.5 day）

### 5.1 背景

当前 `ast_nodes.py:69-71` 仅有 3 个 polars native op：

```python
PL_WHEN = "pl_when"
PL_MAX_H = "pl_max_h"
PL_MIN_H = "pl_min_h"
```

LLM 可能表达更多 polars 原生语义，需扩展。

### 5.2 改动

**文件**: `src/llmwikify/reproduction/ast_nodes.py`

```python
# 在 NodeType 或 PL_NATIVE 枚举中新增

PL_LIT = "pl_lit"
PL_COL_ALIAS = "pl_col_alias"
PL_CONCAT_LIST = "pl_concat_list"
PL_DT_ACCESS = "pl_dt_access"  # pl.col("date").dt.year()
PL_STR_ACCESS = "pl_str_access"  # pl.col("code").str.slice(0, 6)
PL_CONCAT_STR = "pl_concat_str"
PL_IS_NULL = "pl_is_null"
PL_FILL_NULL = "pl_fill_null"
```

### 5.3 `ast_compiler.py` 新增 5 个 native handler

```python
_POLARS_FNS: dict[str, Callable] = {
    "pl_when": lambda n, c: pl.when(c[0]).then(c[1]).otherwise(c[2]),
    "pl_max_h": lambda n, c: pl.max_horizontal(*c),
    "pl_min_h": lambda n, c: pl.min_horizontal(*c),
    # NEW
    "pl_lit": lambda n, c: pl.lit(n.kwargs.get("value")),
    "pl_concat_list": lambda n, c: pl.concat_list(c),
    "pl_col_alias": lambda n, c: c[0].alias(n.kwargs.get("name", "x")),
    "pl_fill_null": lambda n, c: c[0].fill_null(n.kwargs.get("strategy", "forward")),
    "pl_is_null": lambda n, c: c[0].is_null(),
}
```

### 5.4 测试

```python
# tests/reproduction/test_polish_native.py

class TestPolishNative:
    def test_pl_lit(self):
        ast = ASTNode(op="pl_lit", kwargs={"value": 0.5})
        expr = compile_ast(ast)
        result = pl.DataFrame({"x": [1.0, 2.0]}).with_columns(expr.alias("lit"))
        assert result["lit"].to_list() == [0.5, 0.5]

    def test_pl_max_h(self):
        ast = ASTNode(op="pl_max_h", args=[
            ASTNode(op="col", value="a"),
            ASTNode(op="col", value="b"),
        ])
        expr = compile_ast(ast)
        df = pl.DataFrame({"a": [1.0, 5.0], "b": [3.0, 2.0]})
        result = df.with_columns(expr.alias("max"))
        assert result["max"].to_list() == [3.0, 5.0]

    # ... 其他 6 个
```

### 5.5 风险评估

- 🟢 低（pure addition，不改现有 3 个）

---

## 6. PR-4: Loop v4 主路径接入（1.5 days）

### 6.1 背景

把 `FactorCompiler` 从"101 Alphas benchmark 专用"提升为"主路径"。当前主路径：

- `/api/factor/{slug}/backtest` (factor.py:249) → `factor_class` 字符串 → `_compute_factor_matrix`
- `/api/paper/start` multi-factor (paper.py:349-453) → 4 个 kwargs bug

### 6.2 改动 1: `factor.py:272` LLM 化

**文件**: `src/llmwikify/interfaces/server/http/factor.py`

```python
# 现状：
factor_class = factor.get("subcategory", factor.get("factor_class", "momentum"))

# 改后：
from llmwikify.reproduction.factor_compiler import FactorCompiler

def _resolve_factor_class(factor: dict, llm_client=None) -> tuple[str, dict]:
    """根据 YAML 解析 factor_class + params，必要时调 LLM 编译."""
    # 1. 已编译 cache (l5.ast)
    ast_json = factor.get("l5", {}).get("ast")
    if ast_json and isinstance(ast_json, dict) and "op" in ast_json:
        return "ast_compiled", {"ast": ast_json}

    # 2. l1.code 已存在（手工写）
    code = factor.get("l1", {}).get("code", "")
    if code:
        return "formula", {"code": code}

    # 3. l1.formula 非空 → LLM 编译
    if factor.get("l1", {}).get("formula"):
        compiler = FactorCompiler(llm=llm_client)
        result = compiler.compile(factor)
        if result.is_valid:
            return "ast_compiled", {"ast": result.code}

    # 4. fallback
    return factor.get("subcategory", "momentum"), factor.get("l1", {}).get("default_params", {})
```

### 6.3 改动 2: `factor_value_store.compute_and_store_factor` 接 AST

**文件**: `src/llmwikify/reproduction/factor_value_store.py:175-203`

```python
def compute_and_store_factor(
    close_wide: pd.DataFrame,
    factor_name: str,
    factor_class: str,
    factor_params: dict,
    db_path=None,
) -> int:
    from .factor_backtest import _compute_factor_matrix
    factor_wide = _compute_factor_matrix(close_wide, factor_class, factor_params)
    if factor_wide.empty:
        return 0
    return store_factor_values(factor_wide, factor_name, db_path)
```

**新增 `_compute_factor_matrix_from_ast`**（在 `factor_backtest.py`）:

```python
def _compute_factor_matrix_from_ast(close_wide: pd.DataFrame, ast_dict: dict) -> pd.DataFrame:
    """AST 路径：用 QuantNodes 编译并应用到 wide format."""
    from QuantNodes.operators import is_composite_op, get_composite_spec
    from .ast_compiler import compile_ast
    
    ast = ASTNode(**ast_dict)
    expr = compile_ast(ast)  # QuantNodes dispatch + composite
    pl_df = pl.from_pandas(close_wide.reset_index())
    
    # Apply per code
    return pl_df.with_columns(
        expr.over("code").alias("factor")
    ).select(["date", "code", "factor"]).to_pandas()
```

### 6.4 改动 3: `factor_backtest.py:498` 加 AST 分支

```python
def _compute_factor_matrix(close_wide, factor_class, factor_params):
    # NEW: AST 路径
    if factor_class == "ast_compiled":
        return _compute_factor_matrix_from_ast(close_wide, factor_params["ast"])
    # ... 原 9 个 fixed class 分支保留
```

### 6.5 改动 4: `paper.py:402-453` 修复 4 个 bug

| 行号 | Bug | 修复 |
|------|-----|------|
| 405-416 | `data_router/symbols/start_date/end_date/cost_bps` 未知 kwargs | 改用 `universe=universe_spec` |
| 417 | `result["result"]` (dict 访问错) | `bt_result = result` (dataclass) |
| 431-435 | `store_factor_values(... source=...)` 未知 kwarg | 用 `compute_and_store_factor(...)` |

```python
# paper.py:402-453 改后（示意）
for fl in factor_list_factors:
    factor_name = fl["name"]
    factor_data = fl["factor"]
    try:
        # 1. LLM 编译（如有 LLM client）
        compiler = FactorCompiler(llm=_LLM_CLIENT)
        compile_result = compiler.compile(factor_data)
        if compile_result.is_valid:
            factor_class = "ast_compiled"
            factor_params = {"ast": compile_result.code}
            factor_data["l5"] = factor_data.get("l5", {}) | {"ast": compile_result.code}
        else:
            factor_class = factor_data.get("subcategory", "momentum")
            factor_params = factor_data.get("l1", {}).get("default_params", {})

        # 2. 回测（用正确签名）
        result = await asyncio.to_thread(
            run_factor_backtest_universe,
            factor_class=factor_class,
            factor_params=factor_params,
            adj_mode="D",
            n_groups=5,
        )

        # 3. DuckDB 持久化
        from llmwikify.reproduction.factor_value_store import compute_and_store_factor
        await asyncio.to_thread(
            compute_and_store_factor,
            close_wide,  # 需 fetch
            factor_name, factor_class, factor_params,
        )
    except Exception as exc:
        logger.warning(f"Factor {factor_name} backtest failed: {exc}")
        backtest_results.append({"factor_name": factor_name, "error": str(exc)})
```

### 6.6 并发控制

**文件**: `paper.py:386` 之前

```python
import asyncio

PASS2_MAX_CONCURRENCY = 3  # 与 track_b.py 一致
semaphore = asyncio.Semaphore(PASS2_MAX_CONCURRENCY)

async def _run_backtest_one_async(fl, semaphore, ...):
    async with semaphore:
        return await _do_backtest(fl)

tasks = [
    _run_backtest_one_async(fl, semaphore, ...)
    for fl in factor_list_factors
]
backtest_results = []
async for coro in asyncio.as_completed(tasks):
    try:
        backtest_results.append(await coro)
    except Exception as exc:
        backtest_results.append({"error": str(exc)})
```

### 6.7 测试

```python
# tests/reproduction/test_loop_v4_main_path.py

class TestLoopV4MainPath:
    def test_factor_backtest_with_ast(self, factor_with_ast):
        """l5.ast 已存在的 factor 走 AST 路径."""
        result = factor_backtest(factor_with_ast)
        assert result.factor_class_used == "ast_compiled"

    def test_factor_backtest_with_llm(self, factor_with_formula):
        """l1.formula 存在但 l5.ast 缺失 → 调 LLM 编译."""
        with patch("llmwikify.reproduction.factor_compiler.FactorCompiler") as mock:
            mock.return_value.compile.return_value = CompileResult(is_valid=True, code={...})
            result = factor_backtest(factor_with_formula, llm_client=mock)
            assert result.factor_class_used == "ast_compiled"

    def test_factor_backtest_llm_fail_fallback(self):
        """LLM 编译失败 → fallback to subcategory."""
        with patch("llmwikify.reproduction.factor_compiler.FactorCompiler") as mock:
            mock.return_value.compile.return_value = CompileResult(is_valid=False)
            result = factor_backtest(factor_with_formula, llm_client=mock)
            assert result.factor_class_used == "momentum"

    def test_paper_multi_factor_concurrency(self):
        """多因子 paper 用 Semaphore(3) 控制并发."""
        # 模拟 10 个因子同时回测，验证不超过 3 个并发
```

### 6.8 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 回归 101 alphas 测试失败 | 🟡 中 | 跑 `tests/ab_testing/test_101_quantnodes.py` 验证 mock 97/97 不退化 |
| LLM API 限流 | 🟡 中 | `asyncio.Semaphore(3)` + retry |
| `_compute_factor_matrix_from_ast` 与 CodeSandbox 行为差异 | 🟡 中 | 对比 101 alphas IC 差异 < 5% |

---

## 7. PR-5: Semantic Registry（2 days）

### 7.1 背景

**Semantic 层（业务语义）完全属于 llmwikify**——QuantNodes 不懂 quant 业务。Semantic Registry 把"业务概念"（momentum_20d / reversal_5d / value_pe）映射到 QuantNodes composite 或 primitive 序列。

### 7.2 新增文件

- `src/llmwikify/reproduction/semantic_registry.py` (~200 行)
- `~/.llmwikify/semantic_registry.yaml` (50+ op)
- `tests/reproduction/test_semantic_registry.py` (~150 行)

### 7.3 完整代码设计

```python
"""Semantic Op Registry — 业务语义到 primitive/composite 的映射.

Level 3 抽象：把 quant 研究员熟悉的"业务概念"映射到 QuantNodes op 序列。
用户可在 ~/.llmwikify/semantic_registry.yaml 扩展。

对齐规范: docs/designs/llm_compile_loop_v4.md §5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Iterator
import logging

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticOp:
    """业务语义 op.

    Attributes:
        name: 语义名（如 "momentum_20d"）
        family: 7 family 之一（momentum / reversal / value / volatility / volume / quality / conditional）
        expansion: 展开模板（如 "ts_pct_change(close, {window})"）
        defaults: 默认参数（如 {"window": 20}）
        doc: 文档（中文）
        examples: 例子（用于 LLM prompt）
    """
    name: str
    family: str
    expansion: str
    defaults: dict = field(default_factory=dict)
    doc: str = ""
    examples: list[dict] = field(default_factory=list)


@dataclass
class SemanticResolution:
    """Semantic 解析结果."""
    template: str           # 展开后的模板字符串
    params: dict            # 实际参数（含默认）
    family: str
    source: str             # "builtin" / "yaml" / "user"


class SemanticOpRegistry:
    """业务语义 op 注册表."""

    def __init__(self):
        self._ops: dict[str, SemanticOp] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        """加载内置 50+ semantic op."""
        for op in BUILTIN_SEMANTIC_OPS:
            self.register(op)

    def register(self, op: SemanticOp) -> None:
        """注册 semantic op."""
        if op.name in self._ops:
            raise ValueError(f"Semantic '{op.name}' already registered")
        self._ops[op.name] = op

    def resolve(self, semantic_ref: str, **overrides: Any) -> SemanticResolution:
        """解析 semantic ref 为模板字符串 + 参数.

        Args:
            semantic_ref: 如 "momentum_20d" 或 "momentum_short(window=10)"
            overrides: 覆盖默认参数

        Returns:
            SemanticResolution with template + params
        """
        # 解析 ref: "name(param=value, ...)"
        if "(" in semantic_ref:
            name, args_str = semantic_ref.split("(", 1)
            args_str = args_str.rstrip(")")
            overrides_from_ref = self._parse_kwargs(args_str)
        else:
            name = semantic_ref
            overrides_from_ref = {}

        if name not in self._ops:
            raise KeyError(f"Semantic op '{name}' not registered")

        op = self._ops[name]
        # 合并默认 + 覆盖
        params = {**op.defaults, **overrides_from_ref, **overrides}

        # 替换模板中的占位符
        template = op.expansion.format(**params)

        return SemanticResolution(
            template=template,
            params=params,
            family=op.family,
            source="builtin",
        )

    def list_by_family(self, family: str) -> list[str]:
        """列出某 family 的所有 semantic op."""
        return [name for name, op in self._ops.items() if op.family == family]

    def all_ops(self) -> Iterator[SemanticOp]:
        return iter(self._ops.values())

    def load_from_yaml(self, yaml_path: str | Path) -> int:
        """从 YAML 加载用户扩展 semantic op."""
        p = Path(yaml_path).expanduser()
        if not p.exists():
            logger.warning("YAML not found: %s", yaml_path)
            return 0
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or "semantic_ops" not in data:
            return 0
        count = 0
        for entry in data["semantic_ops"]:
            op = SemanticOp(
                name=entry["name"],
                family=entry["family"],
                expansion=entry["expansion"],
                defaults=entry.get("defaults", {}),
                doc=entry.get("doc", ""),
                examples=entry.get("examples", []),
            )
            self.register(op)
            count += 1
        return count

    def get_doc_for_llm(self) -> str:
        """生成 LLM prompt 用的 semantic op 文档."""
        lines = ["# Available Semantic Operators\n"]
        for family in ["momentum", "reversal", "value", "volatility", "volume", "quality", "conditional"]:
            family_ops = self.list_by_family(family)
            if not family_ops:
                continue
            lines.append(f"## Family: {family}")
            for name in family_ops:
                op = self._ops[name]
                lines.append(f"  - {name}: {op.doc}")
                if op.examples:
                    lines.append(f"    Example: {op.examples[0]}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_kwargs(s: str) -> dict:
        """解析 'k1=v1, k2=v2' 字符串."""
        result = {}
        for pair in s.split(","):
            pair = pair.strip()
            if not pair:
                continue
            k, v = pair.split("=", 1)
            # 简单类型转换
            v = v.strip()
            if v.isdigit():
                v = int(v)
            elif v.replace(".", "").isdigit():
                v = float(v)
            result[k.strip()] = v
        return result


# ============== 内置 50+ Semantic Op ==============

BUILTIN_SEMANTIC_OPS: list[SemanticOp] = [
    # Momentum (5)
    SemanticOp("momentum_5d", "momentum", "ts_pct_change(close, {window})",
               {"window": 5}, "5 日动量"),
    SemanticOp("momentum_10d", "momentum", "ts_pct_change(close, {window})",
               {"window": 10}, "10 日动量"),
    SemanticOp("momentum_20d", "momentum", "ts_pct_change(close, {window})",
               {"window": 20}, "20 日动量（经典）"),
    SemanticOp("momentum_60d", "momentum", "ts_pct_change(close, {window})",
               {"window": 60}, "60 日动量"),
    SemanticOp("momentum_accel", "momentum",
               "sub(ts_pct_change(close, {short}), ts_pct_change(close, {long}))",
               {"short": 5, "long": 20}, "动量加速度"),

    # Reversal (4)
    SemanticOp("reversal_1d", "reversal", "neg(ts_pct_change(close, {window}))",
               {"window": 1}, "1 日反转"),
    SemanticOp("reversal_5d", "reversal", "neg(ts_pct_change(close, {window}))",
               {"window": 5}, "5 日反转"),
    SemanticOp("reversal_20d", "reversal", "neg(ts_pct_change(close, {window}))",
               {"window": 20}, "20 日反转"),
    SemanticOp("reversal_accel", "reversal",
               "neg(sub(ts_pct_change(close, {short}), ts_pct_change(close, {long})))",
               {"short": 1, "long": 5}, "反转加速度"),

    # Value (6)
    SemanticOp("value_pe", "value", "div(close, eps)",
               {"eps": "eps_ttm"}, "市盈率倒数（E/P）"),
    SemanticOp("value_pb", "value", "div(close, book_value)",
               {"book_value": "bvps"}, "市净率倒数（B/P）"),
    SemanticOp("value_ps", "value", "div(close, sales_per_share)",
               {"sales_per_share": "sps"}, "市销率倒数"),
    SemanticOp("value_ev_ebitda", "value", "div(enterprise_value, ebitda)",
               {"enterprise_value": "ev", "ebitda": "ebitda"}, "EV/EBITDA 倒数"),
    SemanticOp("value_dividend_yield", "value", "div(dividend, close)",
               {"dividend": "dps"}, "股息率"),
    SemanticOp("value_fcf_yield", "value", "div(free_cash_flow, market_cap)",
               {"free_cash_flow": "fcf"}, "自由现金流收益率"),

    # Volatility (4)
    SemanticOp("volatility_5d", "volatility", "rolling_std(returns, {window})",
               {"window": 5}, "5 日波动率"),
    SemanticOp("volatility_20d", "volatility", "rolling_std(returns, {window})",
               {"window": 20}, "20 日波动率"),
    SemanticOp("volatility_60d", "volatility", "rolling_std(returns, {window})",
               {"window": 60}, "60 日波动率"),
    SemanticOp("volatility_of_vol", "volatility",
               "rolling_std(rolling_std(returns, 20), 20)",
               {}, "波动率的波动率"),

    # Volume (4)
    SemanticOp("volume_trend_20d", "volume", "ts_pct_change(volume, {window})",
               {"window": 20}, "20 日成交量趋势"),
    SemanticOp("volume_price_corr_20d", "volume",
               "rolling_corr(volume, returns, {window})",
               {"window": 20}, "量价相关性"),
    SemanticOp("volume_breakout", "volume",
               "div(volume, rolling_mean(volume, 20))",
               {}, "成交量突破（量比）"),
    SemanticOp("volume_obv", "volume", "cum_sum(sign(returns) * volume)",
               {}, "能量潮指标"),

    # Quality (5)
    SemanticOp("quality_roe", "quality", "div(net_income, equity)",
               {"net_income": "ni", "equity": "equity"}, "ROE"),
    SemanticOp("quality_roa", "quality", "div(net_income, total_assets)",
               {"net_income": "ni", "total_assets": "ta"}, "ROA"),
    SemanticOp("quality_gross_margin", "quality", "div(gross_profit, revenue)",
               {"gross_profit": "gp", "revenue": "rev"}, "毛利率"),
    SemanticOp("quality_asset_turnover", "quality", "div(revenue, total_assets)",
               {"revenue": "rev", "total_assets": "ta"}, "资产周转率"),
    SemanticOp("quality_accruals", "quality",
               "div(sub(net_income, cashflow_from_ops), total_assets)",
               {}, "应计利润"),

    # Conditional (3)
    SemanticOp("conditional_up_down", "conditional",
               "pl_when(gt(returns, 0), rolling_mean(returns, 5), neg(rolling_mean(abs(returns), 5)))",
               {}, "涨/跌不对称"),
    SemanticOp("conditional_high_volume", "conditional",
               "pl_when(gt(volume, rolling_mean(volume, 20)), momentum_20d, lit(0))",
               {}, "高量动量"),
    SemanticOp("conditional_breakout", "conditional",
               "pl_when(gt(close, rolling_max(close, 20)), lit(1), lit(0))",
               {}, "突破信号"),
]


# ============== 全局单例 ==============

_REGISTRY: Optional[SemanticOpRegistry] = None


def get_semantic_registry() -> SemanticOpRegistry:
    """获取全局 semantic registry（懒加载 + 自动加载用户 YAML）."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SemanticOpRegistry()
        # 自动加载用户扩展
        user_yaml = Path.home() / ".llmwikify" / "semantic_registry.yaml"
        if user_yaml.exists():
            count = _REGISTRY.load_from_yaml(user_yaml)
            logger.info("Loaded %d user semantic ops from %s", count, user_yaml)
    return _REGISTRY
```

### 7.4 `~/.llmwikify/semantic_registry.yaml` 示例

```yaml
semantic_ops:
  # 用户自定义
  - name: custom_momentum
    family: momentum
    expansion: "ts_pct_change(close, {window})"
    defaults: {window: 30}
    doc: "我的自定义 30 日动量"
    examples:
      - ref: "custom_momentum(window=45)"
        expect: "ts_pct_change(close, 45)"

  - name: industry_neutral_momentum
    family: momentum
    expansion: "industry_neutralize(momentum_20d, industry_col={industry_col})"
    defaults: {industry_col: citic_1}
    doc: "行业中性化动量"
```

### 7.5 集成到 `ast_compiler`

```python
# ast_compiler.py 新增

def compile_ast(node: ASTNode) -> pl.Expr:
    # Layer 0: Primitive (QuantNodes)
    fn = get_operator(node.op)
    if fn is not None:
        children = [compile_ast(c) for c in node.args]
        return fn(*children, **node.kwargs)

    # Layer 1: Composite (QuantNodes PR-QN-3)
    if is_composite_op(node.op):
        spec = get_composite_spec(node.op)
        kwargs = {
            pname: _resolve_value(node.kwargs.get(pname))
            for pname in spec.params
        }
        return spec.instantiate(**kwargs)

    # Layer 2: Semantic (llmwikify, NEW)
    from .semantic_registry import get_semantic_registry
    registry = get_semantic_registry()
    try:
        resolution = registry.resolve(node.op, **node.kwargs)
        # 展开为 AST 子节点，递归编译
        sub_ast = _template_string_to_ast(resolution.template)
        return compile_ast(sub_ast)
    except KeyError:
        pass

    # Layer 3: Polars Native
    if node.op in PL_NATIVE_OPS:
        return _compile_polars_native(node)

    raise CompileError("UnknownOp", f"'{node.op}' not found in any layer")
```

### 7.6 测试

```python
# tests/reproduction/test_semantic_registry.py

class TestSemanticRegistry:
    def test_50_builtins_registered(self):
        registry = SemanticOpRegistry()
        all_ops = list(registry.all_ops())
        assert len(all_ops) >= 50

    def test_resolve_momentum(self):
        registry = SemanticOpRegistry()
        res = registry.resolve("momentum_20d")
        assert res.template == "ts_pct_change(close, 20)"
        assert res.family == "momentum"

    def test_resolve_with_override(self):
        registry = SemanticOpRegistry()
        res = registry.resolve("momentum_20d", window=30)
        assert res.template == "ts_pct_change(close, 30)"

    def test_resolve_unknown_raises(self):
        registry = SemanticOpRegistry()
        with pytest.raises(KeyError):
            registry.resolve("unknown_op")

    def test_list_by_family(self):
        registry = SemanticOpRegistry()
        momentum_ops = registry.list_by_family("momentum")
        assert "momentum_20d" in momentum_ops
        assert "momentum_60d" in momentum_ops

    def test_load_user_yaml(self, tmp_path):
        yaml_content = """
semantic_ops:
  - name: my_custom
    family: momentum
    expansion: "ts_pct_change(close, {window})"
    defaults: {window: 30}
    doc: 测试
"""
        yaml_file = tmp_path / "semantic.yaml"
        yaml_file.write_text(yaml_content)

        registry = SemanticOpRegistry()
        count = registry.load_from_yaml(yaml_file)
        assert count == 1
        assert "my_custom" in [op.name for op in registry.all_ops()]

    def test_get_doc_for_llm(self):
        registry = SemanticOpRegistry()
        doc = registry.get_doc_for_llm()
        assert "## Family: momentum" in doc
        assert "momentum_20d" in doc
```

### 7.7 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| LLM 误用 semantic 模板 | 🟢 低 | Strict validation + few-shot examples |
| YAML 加载错误 | 🟢 低 | try/except + warning log |
| 与 QuantNodes composite 混淆 | 🟢 低 | 通过 family 区分（semantic 有 family，composite 无） |

---

## 8. PR-6: Self-Repairing Compiler（1 day）

### 8.1 背景

当前 `FactorCompiler.compile()` 的 4 阶段循环中，错误处理是 **单一重试**（max_iter=2）。业界共识：累积多轮错误 + 5 层递进校验更有效。

### 8.2 5 层 FixStrategy 设计

| Strategy | 触发条件 | 修复动作 |
|----------|---------|---------|
| **SchemaFix** | Pydantic ValidationError | 重新 emit（结构错） |
| **CompileFix** | CompileError 5 类 | 替换 op / 补 kwarg / 改 arity |
| **SemanticFix** | Semantic Registry miss | 提议 Composite 或降级 Layer 0 |
| **CompositeFix** | Composite 模板错 | 简化 DAG / 展开为 primitive |
| **RuntimeFix** | polars.TypeError | 类型转换 / `.cast()` |
| **QualityFix** | IC ≈ 0 / complexity INCOMPLETE | 重写（用真实失败 case） |

### 8.3 新增文件

- `src/llmwikify/reproduction/self_repairing_compiler.py` (~350 行)
- `tests/reproduction/test_self_repair.py` (~150 行)

### 8.4 完整代码设计（核心结构）

```python
"""Self-Repairing Compiler — 5 层递进修复的 LLM 编译框架.

参考业界：
  - Reflexion (Shinn'24): Self-Reflection with verbal feedback
  - CRITIC (Gou'24): LLM critique with tool feedback
  - Self-Refine (Madaan'23): Iterative refinement

对齐规范: docs/designs/llm_compile_loop_v4.md §4
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from collections.abc import Iterator

from .ast_compiler import compile_ast, CompileError
from .ast_extractor import extract_ast
from .ast_complexity import check_complexity
from .ast_nodes import ASTNode
from .error_categorizer import StructuredError, categorize_compile_error
from .factor_compiler import FactorCompiler

logger = logging.getLogger(__name__)


@dataclass
class RepairRound:
    """一轮修复尝试."""
    round_idx: int
    ast_json: dict | None
    error: Optional[StructuredError] = None
    error_layer: str = ""
    fix_action: str = ""
    latency_ms: float = 0.0


@dataclass
class RepairResult:
    """修复结果."""
    is_valid: bool
    final_ast: dict | None
    code: pl.Expr | None
    rounds: list[RepairRound] = field(default_factory=list)
    final_error: Optional[StructuredError] = None
    total_llm_calls: int = 0


class FixStrategy:
    """修复策略基类."""

    def __init__(self, name: str, layer: str):
        self.name = name
        self.layer = layer

    def check(self, ast_json: dict | None, raw_text: str | None,
              factor_data: dict, pl_result: Any = None) -> StructuredError | None:
        """检查是否需要修复. 返回 None 表示通过."""
        raise NotImplementedError

    def suggest_fix(self, error: StructuredError, factor_data: dict) -> str:
        """生成给 LLM 的修复提示."""
        return error.to_prompt()


class SchemaFixStrategy(FixStrategy):
    """Layer 1: Pydantic schema 校验."""

    def __init__(self):
        super().__init__("schema", "schema")

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        if ast_json is None:
            return StructuredError(
                kind="InvalidJSON",
                message="AST 提取失败（JSON 解析错误）",
                suggestion="重新 emit，确保输出是合法 JSON",
            )
        try:
            ASTNode(**ast_json)
            return None
        except Exception as exc:
            return StructuredError(
                kind="SchemaValidation",
                message=f"Schema 校验失败: {exc}",
                suggestion="检查字段名 / 类型是否符合 ASTNode 定义",
            )


class CompileFixStrategy(FixStrategy):
    """Layer 2: compile_ast 校验."""

    def __init__(self):
        super().__init__("compile", "compile")

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        if ast_json is None:
            return None  # Schema 已处理
        try:
            ast = ASTNode(**ast_json)
            compile_ast(ast)
            return None
        except CompileError as exc:
            return categorize_compile_error(exc, factor_data.get("l1", {}).get("input_columns"))
        except Exception as exc:
            return StructuredError(
                kind="UnknownError",
                message=f"Compile 异常: {exc}",
            )


class SemanticFixStrategy(FixStrategy):
    """Layer 3: Semantic Registry 查询."""

    def __init__(self):
        super().__init__("semantic", "semantic")
        from .semantic_registry import get_semantic_registry
        self._registry = get_semantic_registry()

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        if ast_json is None:
            return None
        ast = ASTNode(**ast_json)
        from .ast_compiler import _try_resolve_op  # NEW helper
        try:
            _try_resolve_op(ast)
            return None
        except KeyError:
            op_name = ast.op
            # 提议 Composite 或 Semantic
            suggestions = []
            from QuantNodes.operators import list_composite_ops
            for comp in list_composite_ops():
                if op_name in comp.lower() or comp in op_name.lower():
                    suggestions.append(f"composite: {comp}")
            for sem in self._registry.list_by_family("momentum"):
                if op_name in sem or sem in op_name:
                    suggestions.append(f"semantic: {sem}")
            return StructuredError(
                kind="SemanticMiss",
                message=f"未识别的 op: '{op_name}'",
                suggestion=f"尝试: {' / '.join(suggestions) or '用 Composite 或 Semantic op'}",
            )


class CompositeFixStrategy(FixStrategy):
    """Layer 4: Composite 模板校验."""

    def __init__(self):
        super().__init__("composite", "composite")

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        if ast_json is None:
            return None
        from QuantNodes.operators import is_composite_op, get_composite_spec
        ast = ASTNode(**ast_json)
        if is_composite_op(ast.op):
            spec = get_composite_spec(ast.op)
            try:
                spec.instantiate(**ast.kwargs)
                return None
            except (ValueError, TypeError) as exc:
                return StructuredError(
                    kind="CompositeParamError",
                    message=f"Composite '{ast.op}' 参数错: {exc}",
                    suggestion=f"检查 kwargs: {[p for p in spec.params]}",
                )
        return None


class RuntimeFixStrategy(FixStrategy):
    """Layer 5: polars runtime 校验."""

    def __init__(self):
        super().__init__("runtime", "runtime")

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        # 需要 sample data 来测，此处仅 placeholder
        return None  # 实际在 simulation 阶段统一测


class QualityFixStrategy(FixStrategy):
    """Layer 6: complexity + 完整度校验."""

    def __init__(self):
        super().__init__("quality", "quality")

    def check(self, ast_json, raw_text, factor_data, pl_result=None):
        if ast_json is None:
            return None
        ast = ASTNode(**ast_json)
        l2_steps = len(factor_data.get("l2", {}).get("calculation_steps", []))
        verdict, msg = check_complexity(ast, l2_steps)
        if verdict.value == "incomplete":
            return StructuredError(
                kind="IncompleteAST",
                message=f"AST 不完整: {msg}",
                suggestion=f"补全 sub-tree，当前 l2 步骤: {l2_steps}",
            )
        return None


class SelfRepairingCompiler:
    """自我修复编译器：5 层递进 + 多轮重试."""

    def __init__(
        self,
        llm_client=None,
        max_repair_rounds: int = 3,
        temperature: float = 0.5,
    ):
        self.llm = llm_client
        self.max_repair_rounds = max_repair_rounds
        self.temperature = temperature
        # 5+1 FixStrategy
        self.strategies = [
            SchemaFixStrategy(),
            CompileFixStrategy(),
            SemanticFixStrategy(),
            CompositeFixStrategy(),
            RuntimeFixStrategy(),
            QualityFixStrategy(),
        ]

    def compile(self, factor_data: dict) -> RepairResult:
        """主入口：多轮修复循环."""
        rounds: list[RepairRound] = []
        llm_call_count = 0
        errors_history: list[StructuredError] = []

        for round_idx in range(self.max_repair_rounds):
            t0 = time.monotonic()

            # 1. LLM emit (带错误历史)
            prompt = self._build_prompt(factor_data, errors_history)
            response = self.llm.chat(prompt, temperature=self.temperature)
            llm_call_count += 1

            # 2. 提取 AST
            raw_text = response.text
            ast_json = extract_ast(raw_text)

            # 3. 6 层递进校验
            round_errors: list[tuple[FixStrategy, StructuredError]] = []
            for strategy in self.strategies:
                err = strategy.check(ast_json, raw_text, factor_data)
                if err:
                    round_errors.append((strategy, err))

            # 4. 全部通过？
            if not round_errors:
                # 编译成功
                ast = ASTNode(**ast_json)
                pl_expr = compile_ast(ast)
                rounds.append(RepairRound(
                    round_idx=round_idx,
                    ast_json=ast_json,
                    latency_ms=(time.monotonic() - t0) * 1000,
                ))
                return RepairResult(
                    is_valid=True,
                    final_ast=ast_json,
                    code=pl_expr,
                    rounds=rounds,
                    total_llm_calls=llm_call_count,
                )

            # 5. 累积错误
            errors_history.extend(err for _, err in round_errors)
            rounds.append(RepairRound(
                round_idx=round_idx,
                ast_json=ast_json,
                error=round_errors[0][1],
                error_layer=round_errors[0][0].layer,
                latency_ms=(time.monotonic() - t0) * 1000,
            ))

        # 达到 max_repair_rounds，宣告失败
        return RepairResult(
            is_valid=False,
            final_ast=None,
            code=None,
            rounds=rounds,
            final_error=errors_history[-1] if errors_history else None,
            total_llm_calls=llm_call_count,
        )

    def _build_prompt(self, factor_data: dict, errors_history: list[StructuredError]) -> str:
        """构造 prompt（包含 self-context + 错误历史）."""
        from .factor_compiler import FactorCompiler
        fc = FactorCompiler(self.llm)
        base_prompt = fc._build_user_prompt(factor_data)

        if not errors_history:
            return base_prompt

        # 累积错误展示
        error_lines = ["\n\n## Previous Errors (please fix these)\n"]
        for i, err in enumerate(errors_history, 1):
            error_lines.append(f"{i}. [{err.kind}] {err.message}")
            if err.suggestion:
                error_lines.append(f"   Suggestion: {err.suggestion}")
        return base_prompt + "\n".join(error_lines)
```

### 8.5 测试

```python
# tests/reproduction/test_self_repair.py

class TestSelfRepair:
    def test_first_round_success(self):
        """LLM 一次成功 → 1 轮通过."""
        with patch("llmwikify.reproduction.factor_compiler.FactorCompiler._multi_sample") as mock:
            mock.return_value = [json.dumps({"op": "rank", "args": [{"op": "col", "value": "close"}]})]
            compiler = SelfRepairingCompiler(mock)
            result = compiler.compile({"l1": {"formula": "rank(close)"}})
            assert result.is_valid
            assert len(result.rounds) == 1

    def test_repair_after_compile_error(self):
        """第 1 轮 emit 错 op → 第 2 轮修复."""
        # 模拟 LLM 第 1 轮 emit UnknownOp，第 2 轮 emit correct op
        responses = [
            json.dumps({"op": "unknown_op", "args": []}),
            json.dumps({"op": "rank", "args": [{"op": "col", "value": "close"}]}),
        ]
        with patch.object(self.llm, "chat") as mock:
            mock.side_effect = [Mock(text=r) for r in responses]
            result = compiler.compile(...)
            assert result.is_valid
            assert len(result.rounds) == 2

    def test_max_rounds_exhausted(self):
        """达到 max_repair_rounds → 失败."""
        # 3 轮都 emit 同样的错
        with patch.object(self.llm, "chat") as mock:
            mock.return_value = Mock(text=json.dumps({"op": "bad", "args": []}))
            result = compiler.compile(...)
            assert not result.is_valid
            assert result.total_llm_calls == 3

    def test_error_history_accumulated(self):
        """错误历史累积传给 LLM."""
        # 验证第 3 轮的 prompt 包含前 2 轮的错误
        ...
```

### 8.6 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| LLM 修复循环不收敛 | 🟡 中 | max_repair_rounds=3 + 错误累积展示 |
| Prompt 过长 | 🟡 中 | 限制历史只保留最近 3 个 error |
| 性能开销 | 🟢 低 | 每轮 +1 LLM call（最多 3） |

---

## 9. PR-7: Loop v4 系统收尾（1 day）

### 9.1 背景

最后清理工作：telemetry + dead code 清理 + clickhouse_data 合并 + Self-Repairing 接入 FactorCompiler。

### 9.2 改动清单

| 子任务 | 工作量 | 文件 |
|--------|--------|------|
| **clickhouse_data 合并** | 1 hr | 删 `clickhouse_data.py`，统一用 `router.ClickHouseDataSource` |
| **HDF5 key 命名修复** | 0.5 hr | `cp` → `close`（与 quantnodes_repro 对齐） |
| **error_categorizer 复用** | 1 hr | `extract_paper.py / paper.py:441 / track_b.py` 改用 StructuredError |
| **error_categorizer attribute-based 重构** | 0.5 hr | substring 匹配 → `exc.kind` attribute |
| **telemetry** | 1 hr | `compiler.stats = {success, iter_avg, cache_hits, ...}` |
| **ast_compiler 死代码清理** | 0.5 hr | `_LEAF_FNS` 是空 dispatch table，删除 |
| **OP_SPEC 自动生成** | 1 hr | 从 QuantNodes registry 自动推断（替代 90 行硬编码） |
| **SelfRepairingCompiler 接入 FactorCompiler** | 1 hr | FactorCompiler.compile 改调 SelfRepairingCompiler |
| **SYSTEM_PROMPT 改用 QuantNodes composite doc** | 1 hr | 改用 `get_composite_doc_for_llm()` |
| **end-to-end 集成测试** | 2 hr | 101 alphas mock 97/97 不退化 |

**总计**: ~10 hr / 1 day

### 9.3 clickhouse_data 合并细节

```python
# 删除：src/llmwikify/reproduction/clickhouse_data.py (209 行)

# 统一用：
from llmwikify.reproduction.router import ClickHouseDataSource
ds = ClickHouseDataSource(passwd="...")
df = ds.get("000001.SZ", "2024-01-01", "2024-12-31")

# HDF5 cache: 复用现有 router.CacheNode（而非自己写）
```

### 9.4 HDF5 key 命名修复

```python
# 现状（不一致）：
# clickhouse_data.py 写: pl_df.write_hdf("stk_daily.h5", key="close")
# quantnodes_repro.py 读: pd.read_hdf("stk_daily.h5", key="cp")

# 改后（统一）：
# 写: key="close"
# 读: key="close"
```

### 9.5 error_categorizer 复用 3 处

| 位置 | 当前 | 改后 |
|------|------|------|
| `extract_paper.py:233` JSON parse | `json.JSONDecodeError` raw | `StructuredError(kind="json_truncated", suggestion="increase max_tokens")` |
| `paper.py:441` backtest failure | `logger.warning(str(exc))` | `StructuredError + _DB.record_event` |
| `track_b.py` Pass 2 success=False | inline dict | `StructuredError + DB event` |

### 9.6 telemetry

```python
# factor_compiler.py 新增

@dataclass
class CompilerStats:
    total_calls: int = 0
    successful_compiles: int = 0
    avg_iterations: float = 0.0
    cache_hits: int = 0
    llm_token_usage: int = 0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    def record(self, result: CompileResult, latency_ms: float):
        self.total_calls += 1
        if result.is_valid:
            self.successful_compiles += 1
        self.avg_iterations = (
            (self.avg_iterations * (self.total_calls - 1) + result.iterations)
            / self.total_calls
        )

# 单例 + 持久化
_STATS_FILE = Path.home() / ".llmwikify" / "factor_compiler_stats.json"
```

### 9.7 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 删除 clickhouse_data 破坏 benchmark | 🟡 中 | 跑 `test_101_quantnodes.py` 验证 mock 97/97 |
| telemetry 持久化失败 | 🟢 低 | try/except + warning log |
| Self-Repairing 接入破坏现有行为 | 🟡 中 | mock mode 回归测试 |

---

## 10. 实施时间线（与 QuantNodes 并行）

```
Week 1 (5 工作日):
  QuantNodes 轨道:
    Day 1: PR-QN-1 (1 hr) + PR-QN-2 (1 hr)
    Day 2-3: PR-QN-3a (2 days)
    Day 4-5: PR-QN-3b (2 days)

  llmwikify 轨道 (并行):
    Day 1: PR-1 + PR-2 (10 min) + PR-3 启动 (0.5 day)
    Day 1.5: PR-3 完成 + PR-4 启动 (1.5 days)
    Day 3: PR-4 完成 + PR-5 启动 (2 days)

Week 2 (5 工作日):
  llmwikify 轨道:
    Day 6-7: PR-5 完成 (Semantic Registry)
    Day 8: PR-6 (Self-Repairing Compiler, 1 day)
    Day 9-10: PR-7 (收尾 + 集成测试, 1 day)
```

**关键路径**: 10 工作日 / 2 周

**依赖关系**:
```
PR-1, PR-2, PR-3 (无依赖，立即可做)
PR-4 (依赖 PR-QN-3a 提供的 get_composite_spec)
PR-5 (依赖 PR-QN-3 + 自身)
PR-6 (依赖 PR-4 + PR-5)
PR-7 (依赖 PR-4 + PR-5 + PR-6)
```

---

## 11. 测试矩阵总览

| PR | 测试类型 | 用例数 | 覆盖目标 |
|----|---------|--------|---------|
| PR-1 | 回归 | 0（无新代码） | 替换后行为不变 |
| PR-2 | smoke | 1 | import 测试 |
| PR-3 | 单元 + 端到端 | 8 | 6-8 个 native op |
| PR-4 | 集成 | 4 | factor.py + paper.py 主路径 |
| PR-5 | 单元 + 集成 | 6 | 50 semantic + YAML |
| PR-6 | 单元 | 4 | 5 FixStrategy + 收敛 |
| PR-7 | 回归 + 集成 | 5 | mock 97/97 + clickhouse + telemetry |

**总计**: ~28 个新测试用例

---

## 12. 风险评估汇总

| 风险 | 等级 | 缓解策略 |
|------|------|---------|
| 101 alphas 回归失败 | 🟡 中 | mock 模式不破坏 + 真实 LLM 分批验证 |
| LLM API throttle | 🟡 中 | Semaphore(3) + retry |
| Self-Repairing 循环不收敛 | 🟡 中 | max_repair_rounds=3 + 错误累积 |
| YAML 扩展加载失败 | 🟢 低 | try/except + warning |
| clickhouse 合并破坏 benchmark | 🟡 中 | 删前跑完整测试 |
| 私有 API 改名 | 🟢 低 | PR-1 已替换为公共 API |
| `_OPERATOR_REGISTRY` 注入冲突 | 🟢 低 | `is_composite=True` 标记位 |

---

## 13. 验收标准

### PR-1
- [ ] `_OPERATOR_REGISTRY` import 全部移除
- [ ] `get_operator()` 调用等价
- [ ] 现有测试 706+ 全通过

### PR-2
- [ ] `pyproject.toml` 有 `quant = ["quantnodes>=2.7.0"]`
- [ ] README 说明可选依赖

### PR-3
- [ ] 6-8 个 polars native op 注册
- [ ] `compile_ast()` 支持 native op
- [ ] 8 个测试全通过

### PR-4
- [ ] `/api/factor/{slug}/backtest` 走 AST 路径（当 l5.ast 存在）
- [ ] `/api/paper/start` multi-factor 修 4 个 kwargs bug
- [ ] Semaphore(3) 控制并发
- [ ] 4 个集成测试通过

### PR-5
- [ ] 50+ semantic op 注册
- [ ] YAML 加载接口可用
- [ ] 6 个测试全通过

### PR-6
- [ ] 5 FixStrategy 全部实现
- [ ] Self-RepairingCompiler 主循环工作
- [ ] 4 个测试全通过

### PR-7
- [ ] mock 97/97 不退化
- [ ] HDF5 key 命名统一
- [ ] error_categorizer 在 3 处复用
- [ ] telemetry 持久化工作
- [ ] 5 个集成测试通过

### 整体
- [ ] pytest 全过（706 + 28 新 = 734）
- [ ] ruff check clean
- [ ] 101 alphas mock 97/97 维持
- [ ] 真实 LLM 跑通 ≥10 alphas（不要求 97 全过）

---

## 14. 后续扩展（不在本阶段）

| 扩展 | 说明 |
|------|------|
| MCTS Alpha Discovery | 用 SelfRepairingCompiler 编译 MCTS variants |
| 跨市场 | HS300 → CSI500 / S&P500 |
| 在线学习 | 增量更新 + 自动淘汰 |
| 真实 LLM 100% benchmark | 全量验证 97 alphas（当前 1/97） |

---

## 附录 A: 与 QuantNodes 文档的对应关系

| llmwikify PR | 依赖 QuantNodes PR | 接口 |
|------------|------------------|------|
| PR-1 | — | `get_operator()`（已有） |
| PR-2 | — | pyproject 依赖声明 |
| PR-3 | — | 自建 native ops |
| PR-4 | **PR-QN-3a/b** | `is_composite_op / get_composite_spec / list_composite_ops` |
| PR-5 | **PR-QN-3a/b** | `get_composite_doc_for_llm`（拼装 semantic doc） |
| PR-6 | **PR-QN-1** | `CodeSandbox(allowed_imports=...)` 兜底 |
| PR-7 | **PR-QN-1/2** | `CodeSandbox` + `PipelineRunner(extra_phases=...)` |

---

## 附录 B: 4 层抽象算子最终归属

```
┌─────────────────────────────────────────────────────┐
│                    llmwikify v0.37                   │
│                                                     │
│  ┌────────────────────────────────────────────┐     │
│  │  Self-Repairing Compiler (5 FixStrategy)   │     │
│  │  + Factor Compiler (LLM 编排)              │     │
│  │  + AST Schema + Extractor                   │     │
│  │  + Semantic Registry (50+ 业务语义)         │     │
│  │  + Polars Native (6-8 ops)                  │     │
│  └─────────────────┬──────────────────────────┘     │
│                    ↓                                │
│  ┌────────────────────────────────────────────┐     │
│  │  AST Compiler (AST → pl.Expr)              │     │
│  │   ├─→ Layer 2: Semantic (本地)            │     │
│  │   ├─→ Layer 1: Composite (QN)             │     │
│  │   └─→ Layer 0: Primitive (QN)             │     │
│  └─────────────────┬──────────────────────────┘     │
│                    ↓ 公共 API 边界                  │
└─────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────┐
│              QuantNodes v2.7.0 (基础设施)            │
│                                                     │
│  ┌────────────────────────────────────────────┐     │
│  │  317+ Primitive Operators (5 类)           │     │
│  │  + 20 Composite DAG Templates (新)         │     │
│  │  + CustomOperator (用户扩展)                │     │
│  └────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────┐     │
│  │  CodeSandbox (allowed_imports 可配置)       │     │
│  └────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────┐     │
│  │  PipelineRunner (extra_phases 注入)        │     │
│  └────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────┐     │
│  │  Database Nodes (7 backend)                │     │
│  └────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

**文档结束** | 实施时间 ~10 天 | 风险等级 中 | 7 个 PR 可独立合并