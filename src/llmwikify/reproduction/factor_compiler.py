"""Factor Compiler — Loop v4: Domain-Specific Compiler + AST + 3-Agent.

LLM emits typed AST JSON (Pydantic). Deterministic compiler turns AST -> polars.Expr.
Multi-sample K=3 + structured error feedback. No raw LLM retry on traceback.

Reference: docs/designs/llm_compile_loop_v4.md
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from .ast_compiler import CompileError, compile_ast
from .ast_extractor import extract_ast
from .ast_nodes import QN_OPS, ASTNode
from .error_categorizer import (
    StructuredError,
    categorize_compile_error,
    categorize_extract_error,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a quant factor formula translator.
Translate a mathematical factor formula into a typed AST (JSON object).

## INPUT
A polars DataFrame with columns: date, code, close, open, high, low, volume, returns, vwap.
(Other columns may be available per factor.)

## OUTPUT FORMAT
Output a JSON object representing an AST. Each node has:
  "op":     string (one of the 157 QuantNodes operators OR a built-in)
  "args":   list of child AST nodes
  "kwargs": dict of keyword args (e.g. {"window": 20})
  "value":  for leaf nodes — string column name (col) or literal value (lit)

## AVAILABLE OPERATORS (157 QuantNodes + polars native)

### Leaves
  col  -> {"op": "col", "value": "close"}            # column reference
  lit  -> {"op": "lit", "value": 0.5}                # literal

### Arithmetic (2 args)
  add, sub, mul, div, pow   -> 2 args
  neg, abs, sign, log, sqrt -> 1 arg
  lt, gt, le, ge, eq        -> 2 args (returns bool)

### Polars native
  pl_when   -> 1 or 3 args. 3-arg: pl.when(cond).then(t).otherwise(o)
  pl_max_h, pl_min_h -> 1+ args

### QuantNodes time-series (require window kwarg)
  rolling_mean, rolling_std, rolling_sum, rolling_max, rolling_min,
  rolling_corr (2 args), rolling_cov (2 args), rolling_argmax, rolling_argmin,
  rolling_rank, rolling_skew, rolling_kurt, rolling_count, rolling_quantile,
  rolling_median, rolling_prod, rolling_var, rolling_change_rate
  ts_argmax, ts_argmin, ts_rank, ts_mean, ts_std, ts_sum, ts_quantile,
  ts_delta, ts_diff, ts_lag, ts_pct_change, ts_corr (2), ts_cov (2)
  decay_linear, decay_exp
  correlation (2), covariance (2)
  -> 1 arg + kwargs={"window": N}; correlation needs 2 args + window

### QuantNodes (require periods kwarg)
  delta, diff, lag, delay, shift, pct_change, ref
  -> 1 arg + kwargs={"periods": N}

### EWM (require span kwarg)
  ewm_mean, ewm_std, ewm_var, ewm_corr (2), ewm_cov (2)
  -> 1 arg + kwargs={"span": N}

### Cross-sectional
  rank, scale, zscore, winsorize, neutralize, indneutralize
  -> 1 arg, no kwargs

### Point-wise
  where (3 args: cond, then, other), if_then_else (3 args)
  sign, abs, log, log1p, sqrt, square, pow (2), clip, ceil, floor, fix,
  fill_null, fill_zero, fillna, isnull, notnull, replace, astype, applymap

## CRITICAL RULES

1. Output ONE JSON object, no prose, no markdown intro.
2. Use ```json { ... } ``` fence.
3. Use string column names like "close" (NOT pl.col()).
4. Use op "pl_when" with 3 child nodes: [cond, then_val, otherwise_val]
5. NO invented operators. NO "log_diff" (use diff(log(x)) instead).
6. NO polars native methods like "rolling" on a col. Use the QN op name.

## EXAMPLES

### Example 1 (alpha-001): conditional std with sign*abs^2
Input LaTeX: rank(Ts_ArgMax(SignedPower((r_t < 0) * σ_{r,20} + (r_t >= 0) * P_t, 2), 5)) - 0.5
Output:
```json
{"op": "sub", "args": [
  {"op": "rank", "args": [
    {"op": "ts_argmax", "kwargs": {"window": 5}, "args": [
      {"op": "mul", "args": [
        {"op": "sign", "args": [
          {"op": "where", "args": [
            {"op": "lt", "args": [{"op": "col", "value": "returns"}, {"op": "lit", "value": 0}]},
            {"op": "rolling_std", "kwargs": {"window": 20}, "args": [{"op": "col", "value": "returns"}]},
            {"op": "col", "value": "close"}
          ]}
        ]},
        {"op": "pow", "args": [
          {"op": "abs", "args": [{"op": "where", "args": [
            {"op": "lt", "args": [{"op": "col", "value": "returns"}, {"op": "lit", "value": 0}]},
            {"op": "rolling_std", "kwargs": {"window": 20}, "args": [{"op": "col", "value": "returns"}]},
            {"op": "col", "value": "close"}
          ]}]},
          {"op": "lit", "value": 2}
        ]}
      ]}
    ]}
  ]},
  {"op": "lit", "value": 0.5}
]}
```

### Example 2 (alpha-002): negative correlation of rank log-diff and rank return
Input: -1 * corr(rank(Δlog(volume,2)), rank((close-open)/open), 6)
Output:
```json
{"op": "neg", "args": [
  {"op": "correlation", "kwargs": {"window": 6}, "args": [
    {"op": "rank", "args": [
      {"op": "diff", "kwargs": {"periods": 2}, "args": [
        {"op": "log", "args": [{"op": "col", "value": "volume"}]}
      ]}
    ]},
    {"op": "rank", "args": [
      {"op": "div", "args": [
        {"op": "sub", "args": [{"op": "col", "value": "close"}, {"op": "col", "value": "open"}]},
        {"op": "col", "value": "open"}
      ]}
    ]}
  ]}
]}
```

### Example 3 (alpha-003): negative rolling correlation
Input: -Corr_10(Rank(open), Rank(volume))
Output:
```json
{"op": "neg", "args": [
  {"op": "rolling_corr", "kwargs": {"window": 10}, "args": [
    {"op": "rank", "args": [{"op": "col", "value": "open"}]},
    {"op": "rank", "args": [{"op": "col", "value": "volume"}]}
  ]}
]}
```

### Example 4 (alpha-004): negative ts_rank
Input: -1 * Ts_Rank(rank(low), 9)
Output:
```json
{"op": "neg", "args": [
  {"op": "ts_rank", "kwargs": {"window": 9}, "args": [
    {"op": "rank", "args": [{"op": "col", "value": "low"}]}
  ]}
]}
```

### Example 5 (alpha-007): pl_when conditional with sign*ts_rank
Input: -1 * (-1 * ts_rank(|Δclose_7|, 60) * sign(Δclose_7)) if volume > adv20 else -1
Output:
```json
{"op": "pl_when", "args": [
  {"op": "gt", "args": [{"op": "col", "value": "volume"}, {"op": "col", "value": "adv20"}]},
  {"op": "neg", "args": [
    {"op": "mul", "args": [
      {"op": "ts_rank", "kwargs": {"window": 60}, "args": [
        {"op": "abs", "args": [
          {"op": "diff", "kwargs": {"periods": 7}, "args": [{"op": "col", "value": "close"}]}
        ]}
      ]},
      {"op": "sign", "args": [
        {"op": "diff", "kwargs": {"periods": 7}, "args": [{"op": "col", "value": "close"}]}
      ]}
    ]}
  ]},
  {"op": "lit", "value": -1}
]}
```
"""


@dataclass
class CompileResult:
    factor_name: str
    code: str  # JSON AST as string
    is_valid: bool
    error_message: str | None = None
    iterations: int = 0
    new_operators: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0
    source: str = "llm"  # "llm" | "mock" | "cache"
    polars_expr: str = ""  # rendered polars expression for debugging

    def to_dict(self) -> dict:
        return asdict(self)


# --- Mock (for FACTOR_COMPILER_MOCK=1) ---

_MOCK_MAP: dict[str, str] = {
    "alpha-001": '{"op": "sub", "args": [{"op": "rank", "args": [{"op": "ts_argmax", "kwargs": {"window": 5}, "args": [{"op": "mul", "args": [{"op": "sign", "args": [{"op": "where", "args": [{"op": "lt", "args": [{"op": "col", "value": "returns"}, {"op": "lit", "value": 0}]}, {"op": "rolling_std", "kwargs": {"window": 20}, "args": [{"op": "col", "value": "returns"}]}, {"op": "col", "value": "close"}]}]}, {"op": "pow", "args": [{"op": "abs", "args": [{"op": "where", "args": [{"op": "lt", "args": [{"op": "col", "value": "returns"}, {"op": "lit", "value": 0}]}, {"op": "rolling_std", "kwargs": {"window": 20}, "args": [{"op": "col", "value": "returns"}]}, {"op": "col", "value": "close"}]}]}, {"op": "lit", "value": 2}]}]}]}]}, {"op": "lit", "value": 0.5}]}',
    "__default__": '{"op": "rank", "args": [{"op": "pct_change", "kwargs": {"periods": 5}, "args": [{"op": "col", "value": "close"}]}]}',
}


def _mock_ast(factor_name: str) -> ASTNode:
    """Return a hand-curated AST for testing."""
    raw = _MOCK_MAP.get(factor_name, _MOCK_MAP["__default__"])
    return ASTNode.model_validate_json(raw)


# --- LLM client builder ---


def _build_default_llm() -> Any:
    """Build default LLM client from ~/.llmwikify/llmwikify.json."""
    from .llm_extraction.llm_factory import build_default_client
    try:
        return build_default_client()
    except Exception:
        # Fallback to env-based
        from QuantNodes.ai.llm.openai import OpenAIClient
        return OpenAIClient(
            api_key=os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY") or os.getenv("LLM_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.minimaxi.com/v1",
            model=os.getenv("LLM_MODEL") or "MiniMax-Text-01",
        )


# --- FactorCompiler ---


class FactorCompiler:
    """Compile factor formulas via LLM emit AST + deterministic compile.

    Loop v4 (4 stages):
    0. Build self-context prompt (L1-L4 + 5 examples)
    1. Multi-sample K=3 -> extract AST -> compile (deterministic)
    2. First valid wins; else structured error feedback
    3. Cache successful AST
    """

    def __init__(
        self,
        llm_client: Any = None,
        max_iterations: int = 2,
        cache_dir: str | Path | None = None,
        n_samples: int = 3,
        temperature: float = 0.5,
    ) -> None:
        self.llm = llm_client or _build_default_llm()
        self.max_iterations = max_iterations
        self.n_samples = n_samples
        self.temperature = temperature
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".llmwikify" / "factor_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compile(self, factor_data: dict, use_cache: bool = True) -> CompileResult:
        factor_name = factor_data.get("name", "unnamed")
        cache_path = self._cache_path(factor_data, factor_name)
        if use_cache and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                return CompileResult(**{k: cached.get(k) for k in CompileResult.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass

        if os.getenv("FACTOR_COMPILER_MOCK") == "1":
            t0 = time.monotonic()
            ast = _mock_ast(factor_name)
            try:
                expr = compile_ast(ast)
                code = ast.model_dump_json()
                result = CompileResult(
                    factor_name=factor_name,
                    code=code,
                    is_valid=True,
                    error_message=None,
                    iterations=0,
                    elapsed_sec=time.monotonic() - t0,
                    source="mock",
                    polars_expr=str(expr),
                )
            except CompileError as exc:
                result = CompileResult(
                    factor_name=factor_name,
                    code=ast.model_dump_json(),
                    is_valid=False,
                    error_message=str(exc),
                    iterations=0,
                    elapsed_sec=time.monotonic() - t0,
                    source="mock",
                )
            self._save_cache(cache_path, result)
            return result

        t0 = time.monotonic()
        base_user_prompt = self._build_user_prompt(factor_data)
        last_structured_err: StructuredError | None = None
        iterations = 0

        for it in range(self.max_iterations + 1):
            iterations = it + 1
            user_prompt = base_user_prompt
            if last_structured_err is not None:
                user_prompt += (
                    f"\n\nPREVIOUS ATTEMPT FAILED:\n{last_structured_err.to_prompt()}\n\n"
                    "Please fix the AST and return ONLY the corrected JSON."
                )

            samples = self._multi_sample(user_prompt, self.n_samples)

            ast_node: ASTNode | None = None
            struct_err: StructuredError | None = None
            polars_expr_str = ""

            for sample_text in samples:
                ast_node = extract_ast(sample_text)
                if ast_node is None:
                    struct_err = categorize_extract_error(
                        ValueError("extract failed"), sample_text
                    )
                    continue
                try:
                    expr = compile_ast(ast_node)
                    polars_expr_str = str(expr)
                    struct_err = None
                    break  # first valid
                except CompileError as exc:
                    struct_err = categorize_compile_error(
                        exc, available_columns=factor_data.get("l1", {}).get("input_columns")
                    )

            if ast_node is not None and struct_err is None:
                # Success
                elapsed = time.monotonic() - t0
                result = CompileResult(
                    factor_name=factor_name,
                    code=ast_node.model_dump_json(),
                    is_valid=True,
                    error_message=None,
                    iterations=iterations,
                    elapsed_sec=elapsed,
                    source="llm",
                    polars_expr=polars_expr_str,
                )
                self._save_cache(cache_path, result)
                logger.info(
                    "[factor_compiler] %s compiled: valid=True, %d iters, %.1fs",
                    factor_name, iterations, elapsed,
                )
                return result

            # All samples failed
            last_structured_err = struct_err
            logger.info(
                "[factor_compiler] %s iter %d failed: %s",
                factor_name, iterations, struct_err.kind if struct_err else "?",
            )

        # Exhausted iterations
        elapsed = time.monotonic() - t0
        result = CompileResult(
            factor_name=factor_name,
            code="",
            is_valid=False,
            error_message=last_structured_err.to_prompt() if last_structured_err else "exhausted",
            iterations=iterations,
            elapsed_sec=elapsed,
            source="llm",
        )
        self._save_cache(cache_path, result)
        return result

    def _multi_sample(self, user_prompt: str, k: int) -> list[str]:
        """Generate K samples from LLM at given temperature."""
        # Detect message format: StreamableLLMClient uses dicts; QuantNodes uses Message objects
        is_dict_based = not hasattr(self.llm, "DEFAULT_BASE_URL")
        samples: list[str] = []
        for _ in range(k):
            try:
                if is_dict_based:
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ]
                else:
                    from QuantNodes.ai.llm.base import Message, MessageRole
                    messages = [
                        Message(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
                        Message(role=MessageRole.USER, content=user_prompt),
                    ]
                response = self.llm.chat(
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=1500,
                )
                content = response if isinstance(response, str) else (
                    response.content if hasattr(response, "content") else str(response)
                )
                samples.append(content)
            except Exception as exc:
                logger.warning("[factor_compiler] LLM call failed: %s", exc)
                samples.append("")
        return samples

    def _build_user_prompt(self, factor_data: dict) -> str:
        l1 = factor_data.get("l1", {}) or {}
        l2 = factor_data.get("l2", {}) or {}
        l3 = factor_data.get("l3", {}) or {}
        parts = [
            f"Factor: {factor_data.get('name', 'unnamed')}",
            f"Description: {l1.get('definition', factor_data.get('description', ''))}",
            f"LaTeX Formula: {l1.get('formula', '')}",
            f"Input Columns: {', '.join(l1.get('input_columns', ['close']))}",
        ]
        if l1.get("default_params"):
            parts.append(f"Default Params: {l1['default_params']}")
        if l1.get("business_constraints"):
            parts.append(f"Constraints: {l1['business_constraints']}")
        if l2.get("calculation_steps"):
            parts.append("\nCalculation Steps:")
            for step in l2["calculation_steps"]:
                parts.append(f"  Step {step.get('step', '?')}: {step.get('description', '')}")
                if step.get("formula"):
                    parts.append(f"    {step['formula']}")
            if l2.get("edge_case_handling"):
                parts.append(f"\nEdge Cases:\n  {l2['edge_case_handling']}")
            if l2.get("data_alignment"):
                parts.append(f"\nData Alignment: {l2['data_alignment']}")
        if l3.get("financial_intuition"):
            parts.append(f"\nIntuition: {l3['financial_intuition']}")
        parts.append("\nOutput the AST as a JSON object (in ```json fence):")
        return "\n".join(parts)

    def _cache_path(self, factor_data: dict, factor_name: str) -> Path:
        source = factor_data.get("source_paper", "default")
        source_slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(source))[:60]
        name_slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(factor_name))[:60]
        return self.cache_dir / source_slug / f"{name_slug}.json"

    def _save_cache(self, path: Path, result: CompileResult) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("[factor_compiler] cache save failed: %s", exc)


__all__ = ["CompileResult", "FactorCompiler", "SYSTEM_PROMPT", "compile_ast"]
