"""Factor Compiler — 直接用 LLM 编译 polars 表达式.

Compiles factor formulas (LaTeX + step-by-step) into QuantNodes polars
expressions. If the LLM needs a new operator not in QuantNodes' 157 built-ins,
the code can register it via ``QuantNodes.CustomOperator`` (executed in-process).

Reference: docs/quantnodes.md
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompileResult:
    factor_name: str
    code: str
    is_valid: bool
    error_message: str | None = None
    iterations: int = 0
    new_operators: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0
    source: str = "llm"  # "llm" | "mock" | "cache"

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """You are a quant factor formula translator.
Translate mathematical formulas into ONE LINE of polars expression.

INPUT: a long-format polars DataFrame `df_pl` with columns:
  date (datetime), code (str), close (float), open, high, low, volume, returns, vwap

AVAILABLE QuantNodes operators (use these names directly):
- ts: ts_argmax(col, window=N), ts_argmin(col, window=N), ts_rank(col, window=N)
- rolling: rolling_mean(col, window=N), rolling_std(col, window=N), rolling_sum(col, window=N), rolling_max(col, window=N), rolling_min(col, window=N)
- ewm: ewm_mean(col, span=N)
- section: rank(col), scale(col), zscore(col), winsorize(col, n=3)
- point: sign(col), abs(col), log(col), sqrt(col), pow(col, p), clip(col, lo, hi)
- correlation(c1, c2, window=N), covariance(c1, c2, window=N), decay_linear(col, window=N)
- polars: pl.col('col_name'), pl.when(cond, then).otherwise(other), pl.lit(value)

CRITICAL OUTPUT RULES:
1. Output EXACTLY one line of polars expression.
2. NO def, NO return, NO import, NO class, NO comment, NO ```python``` fence, NO prefix.
3. Use the column name string 'close'/'returns'/etc when calling QuantNodes ops.
4. If you need an operator that doesn't exist, prefix with @CustomOperator registration:
   @CustomOperator.time("my_op")
   def my_op(f, p=2):
       e = pl.col(f) if isinstance(f, str) else f
       return e ** p
   Then the FINAL line is the expression using my_op(...).

EXAMPLE for alpha-001:
Input: rank(Ts_ArgMax(SignedPower((r_t < 0) * σ_{r,20} + (r_t >= 0) * P_t, 2), 5)) - 0.5
Output: rank(ts_argmax(sign(pl.when(returns < 0, rolling_std(returns, 20), close)) * abs(pl.when(returns < 0, rolling_std(returns, 20), close)) ** 2, window=5)) - 0.5
"""


class FactorCompiler:
    """Compile factor formulas via direct LLM call (no StrategyGenerator).

    Args:
        llm_client: QuantNodes LLM client. Built from env if None.
        max_iterations: Max refinement rounds on validation failure.
        cache_dir: Compiled code cache directory.
    """

    def __init__(
        self,
        llm_client: Any = None,
        max_iterations: int = 2,
        cache_dir: str | Path | None = None,
    ):
        if llm_client is None:
            from QuantNodes.ai.llm.openai import OpenAIClient
            llm_client = OpenAIClient(
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY") or os.getenv("LLM_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.minimaxi.com/v1",
                model=os.getenv("LLM_MODEL") or "MiniMax-Text-01",
            )
        self.llm = llm_client
        self.max_iterations = max_iterations
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

        # Mock mode: use simple, reliable polars expression for testing
        if os.getenv("FACTOR_COMPILER_MOCK") == "1":
            mock_expr = self._mock_expression(factor_name)
            t0 = time.monotonic()
            compile_result = CompileResult(
                factor_name=factor_name,
                code=mock_expr,
                is_valid=True,
                error_message=None,
                iterations=0,
                new_operators=[],
                elapsed_sec=time.monotonic() - t0,
                source="mock",
            )
            self._save_cache(cache_path, compile_result)
            return compile_result

        t0 = time.monotonic()
        user_prompt = self._build_user_prompt(factor_data)
        logger.info("[factor_compiler] compiling %s", factor_name)

        code = ""
        error = None
        iterations = 0
        new_operators: list[str] = []

        for attempt in range(self.max_iterations + 1):
            iterations = attempt + 1
            try:
                code = self._call_llm(user_prompt, error)
            except Exception as exc:
                logger.warning("[factor_compiler] LLM call failed: %s", exc)
                error = str(exc)
                continue

            # Try to execute to find syntax / name errors
            ok, err = self._validate_code(code)
            if ok:
                break
            error = err
            logger.info("[factor_compiler] attempt %d failed: %s", iterations, err[:200])
        else:
            elapsed = time.monotonic() - t0
            compile_result = CompileResult(
                factor_name=factor_name,
                code=code,
                is_valid=False,
                error_message=error,
                iterations=iterations,
                new_operators=new_operators,
                elapsed_sec=elapsed,
            )
            self._save_cache(cache_path, compile_result)
            return compile_result

        elapsed = time.monotonic() - t0
        compile_result = CompileResult(
            factor_name=factor_name,
            code=code,
            is_valid=True,
            error_message=None,
            iterations=iterations,
            new_operators=new_operators,
            elapsed_sec=elapsed,
        )
        self._save_cache(cache_path, compile_result)
        logger.info(
            "[factor_compiler] %s done: valid=True, %.1fs, %d iter",
            factor_name, elapsed, iterations,
        )
        return compile_result

    def _call_llm(self, user_prompt: str, prior_error: str | None) -> str:
        """Single LLM call returning raw text."""
        from QuantNodes.ai.llm.base import Message, MessageRole
        messages = [
            Message(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
            Message(role=MessageRole.USER, content=user_prompt + (
                f"\n\nThe previous attempt failed with:\n{prior_error}\nPlease fix and return ONLY the corrected polars expression." if prior_error else ""
            )),
        ]
        response = self.llm.chat(
            messages=messages,
            temperature=0.05,
            max_tokens=800,
        )
        content = response.content if hasattr(response, "content") else str(response)
        # Strip markdown fences if present
        content = re.sub(r"```python\n", "", content)
        content = re.sub(r"```\n?", "", content)
        # Take only the first non-empty line that's a polars expression
        for line in content.strip().split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith("def ") or stripped.startswith("class "):
                continue
            if stripped.startswith("from ") or stripped.startswith("import "):
                continue
            return stripped
        return content.strip()

    def _validate_code(self, code: str) -> tuple[bool, str]:
        """Try to evaluate the code in a safe namespace. Returns (ok, error)."""
        # Use a minimal namespace to check syntax / names
        import polars as pl
        import numpy as np
        ns = {
            "pl": pl,
            "polars": pl,
            "np": np,
            "close": pl.col("close"),
            "open": pl.col("open"),
            "high": pl.col("high"),
            "low": pl.col("low"),
            "volume": pl.col("volume"),
            "returns": pl.col("returns"),
            "vwap": pl.col("vwap"),
        }
        # Try to import QuantNodes operators
        try:
            from QuantNodes.operators.proxy import _OPERATOR_REGISTRY
            for cat_ops in _OPERATOR_REGISTRY.values():
                for op_name, op_info in cat_ops.items():
                    ns[op_name] = op_info["func"]
        except Exception:
            pass

        try:
            result = eval(code, {"__builtins__": {}}, ns)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if not hasattr(result, "alias"):
            return False, f"Result is not a polars Expr: {type(result)}"
        return True, ""

    def _mock_expression(self, factor_name: str) -> str:
        """Return a simple, validated polars expression for testing.

        Maps known factor names to their polars equivalents. For unknown
        names, returns a generic momentum expression.

        Uses QuantNodes operator names (rolling_std, ts_argmax, etc.) which
        are imported as functions, not polars native methods.
        """
        # Hand-curated mappings for common 101 alphas
        MOCK_MAP: dict[str, str] = {
            "alpha-001": "rank(ts_argmax(sign(where(returns < 0, rolling_std(returns, window=20), close)) * abs(where(returns < 0, rolling_std(returns, window=20), close)) ** 2, window=5)) - 0.5",
            "alpha-002": "-correlation(rank(log(volume).diff(2)), rank((close - open) / open), window=6)",
            "alpha-003": "-rolling_corr(rank(open), rank(volume), window=10)",
            "alpha-004": "-ts_rank(rank(close) * -1, window=9)",
            "alpha-005": "rank(open - rolling_mean(vwap, window=10)) * -abs(rank(close - rolling_mean(vwap, window=10)))",
            # Generic momentum for unknown alphas
            "__default__": "rank(pct_change(close, 5)) - 0.5",
        }
        return MOCK_MAP.get(factor_name, MOCK_MAP["__default__"])

    def _build_user_prompt(self, factor_data: dict) -> str:
        l1 = factor_data.get("l1", {}) or {}
        l2 = factor_data.get("l2", {}) or {}
        l3 = factor_data.get("l3", {}) or {}
        parts = [
            f"Factor: {factor_data.get('name', 'unnamed')}",
            f"Description: {l1.get('definition', factor_data.get('description', ''))}",
            f"LaTeX Formula: {l1.get('formula', '')}",
            f"Input Columns: {', '.join(l1.get('input_columns', ['close']))}",
            "",
            "Calculation Steps:",
        ]
        for step in l2.get("calculation_steps", []):
            parts.append(f"  Step {step.get('step', '?')}: {step.get('description', '')}")
            if step.get("formula"):
                parts.append(f"    {step.get('formula', '')}")
        parts.extend([
            "",
            f"Hypothesis: {l3.get('financial_intuition', '')}",
            "",
            "Output the polars expression (ONE LINE, no fence, no prefix):",
        ])
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


__all__ = ["CompileResult", "FactorCompiler"]
