"""Demo: ReAct self-repair fixes LLM typos via error feedback.

Strategy:
  1. Call real LLM to get a real (probably correct) factor code.
  2. Deliberately corrupt it (e.g., ``.over('date')`` -> ``.out('date')``).
  3. Run ``compile_to_code_react`` with the real LLM as the engine.
  4. Show that the ReAct loop:
       - First REASON produces the corrupt code (pre-seeded as assistant msg).
       - ACT fails with ``AttributeError: 'Expr' object has no attribute 'out'``.
       - OBSERVE injects the error back to LLM.
       - Second REASON emits corrected code.
       - ACT succeeds.

Run with: ``python3 scripts/demo_react_self_repair.py [alpha_index]``
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import polars as pl

PROJECT_ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DATA_PATH = Path("/home/ll/.llmwikify/akshare_cache/quantnodes_h5_long")
TRACK_B = PROJECT_ROOT / "quant" / "papers" / "101_alphas_minimal" / "track_b_checkpoint.json"

# Apply SamplePoolFilter patch (same as test_one_factor_llm_code.py)
from test_one_factor_llm_code import _patch_sample_pool_filter  # noqa: E402

from llmwikify.reproduction.codegen_utils import (  # noqa: E402
    SYSTEM_PROMPT_CODE,
    build_llm_client,
)

_patch_sample_pool_filter()


def _load_long_df() -> pl.DataFrame:
    """Load long-format polars DataFrame from H5 (same as e2e test)."""
    with pd.HDFStore(DATA_PATH / "stk_daily.h5", "r") as s:
        _close_key = "close" if "/close" in s.keys() else "cp"
    cp_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", _close_key)
    open_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "open")
    high_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "high")
    low_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "low")
    volume_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "volume")
    returns_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "returns")
    vwap_wide = pd.read_hdf(DATA_PATH / "stk_daily.h5", "vwap")

    def wide_to_long(wide, name):
        long = wide.stack().reset_index()
        long.columns = ["date", "code", name]
        return pl.from_pandas(long)

    return (
        wide_to_long(cp_wide, "close")
        .join(wide_to_long(open_wide, "open"), on=["date", "code"])
        .join(wide_to_long(high_wide, "high"), on=["date", "code"])
        .join(wide_to_long(low_wide, "low"), on=["date", "code"])
        .join(wide_to_long(volume_wide, "volume"), on=["date", "code"])
        .join(wide_to_long(returns_wide, "returns"), on=["date", "code"])
        .join(wide_to_long(vwap_wide, "vwap"), on=["date", "code"])
        .sort(["date", "code"])
    )


def _corrupt_code(code: str) -> str:
    """Introduce a known typo that breaks execution.

    ``.over('date')`` -> ``.out('date')``  (mimics observed LLM typo)
    """
    return code.replace(".over('date')", ".out('date')")


class _PreSeededLLM:
    """LLM wrapper that returns a pre-seeded first response, then delegates
    to the real LLM for subsequent calls.

    Used to demonstrate the self-repair path deterministically.
    """

    def __init__(self, real_llm, first_response: str) -> None:
        self._real = real_llm
        self._first = first_response
        self._calls = 0

    def chat(self, *, messages, temperature=0.3, **kwargs):
        self._calls += 1
        if self._calls == 1:
            return self._first
        return self._real.chat(messages=messages, temperature=temperature, **kwargs)


def run_demo(alpha_index: int = 1) -> dict:
    t0 = time.monotonic()
    print(f"\n{'='*70}")
    print(f"  ReAct Self-Repair Demo: alpha-{alpha_index:03d}")
    print(f"{'='*70}")

    # Load formula
    track_b = json.loads(TRACK_B.read_text(encoding="utf-8"))
    alpha = next(s for s in track_b["pass1_signals"] if s["index"] == alpha_index)
    factor_name = f"alpha-{alpha_index:03d}"
    formula_brief = alpha["formula_brief"]
    print(f"\n[formula] {formula_brief}")

    # Load data
    df_pl = _load_long_df()
    print(f"[data] shape: {df_pl.shape}, dates: {df_pl['date'].min()} - {df_pl['date'].max()}")

    # First, get a real (correct) LLM response to corrupt
    real_llm = build_llm_client()
    user_prompt = f"""Factor: {alpha['name']}
Formula (pseudo-code): {formula_brief}

Write a Python function `compute_factor(df: pl.DataFrame) -> pl.Series` that computes
this factor. Use QuantNodes operators (rank, ts_argmax, rolling_std, etc.) which are
in the namespace, and use polars expressions otherwise.

Output ONLY the code block."""

    print("\n[step 1] Asking real LLM for a baseline (correct) factor code...")
    baseline_response = real_llm.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_CODE},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    print(f"[baseline] LLM response ({len(baseline_response)} chars)")
    m = re.search(r"```python\s*\n(.+?)\n```", baseline_response, re.DOTALL)
    if not m:
        print("[baseline] No python fence in response; cannot demo. Exiting.")
        return {"status": "skipped", "reason": "no baseline code"}
    baseline_code = m.group(1)
    print(f"[baseline] code extracted ({len(baseline_code)} chars)")

    # Corrupt the code
    corrupted_code = _corrupt_code(baseline_code)
    if corrupted_code == baseline_code:
        print("[corrupt] Could not find `.over('date')` in baseline; cannot demo.")
        return {"status": "skipped", "reason": "no .over() to corrupt"}
    print("[corrupt] replaced `.over('date')` -> `.out('date')`")
    corrupted_response = f"```python\n{corrupted_code}\n```"

    # Wrap LLM to first emit corrupted, then delegate to real
    seeded_llm = _PreSeededLLM(real_llm, corrupted_response)

    # Run ReAct
    print("\n[step 2] Running ReAct with corrupted seed...")
    print("  → expecting: REASON (corrupt) → ACT (AttributeError) → OBSERVE (inject)")
    print("  →            → REASON (real LLM fix) → ACT (success) → DECIDE")

    from llmwikify.reproduction.factor_compiler_react import (
        ReactStep,
        compile_to_code_react,
    )

    def _progress(step: ReactStep) -> None:
        marker = "  " if step.error_kind.value == "none" else "❌"
        print(
            f"  {marker} [ReAct/{step.state.value}] "
            f"{step.error_kind.value if step.error_kind.value != 'none' else 'OK'}: "
            f"{step.error_message[:200]}"
        )

    result = compile_to_code_react(
        factor_name=factor_name,
        formula_brief=formula_brief,
        system_prompt=SYSTEM_PROMPT_CODE,
        df=df_pl,
        llm=seeded_llm,
        max_repair_rounds=3,
        temperature=0.3,
        progress_callback=_progress,
    )

    elapsed = time.monotonic() - t0
    print(f"\n[result] is_valid={result.is_valid}, iterations={result.iterations}, "
          f"error_kind={result.error_kind.value}")
    print(f"[result] elapsed: {elapsed:.1f}s, real LLM calls: {seeded_llm._calls - 1}")

    if result.is_valid and "over('date')" in result.code:
        print("\n[SUCCESS] ReAct self-repair RECOVERED from the typo!")
        print(f"  Final code snippet:\n  {result.code[-200:]}")
        success = True
    else:
        print("\n[FAIL] ReAct did NOT recover from the typo")
        success = False

    return {
        "status": "success" if success else "failed",
        "alpha_index": alpha_index,
        "baseline_code_chars": len(baseline_code),
        "corrupted_code_chars": len(corrupted_code),
        "is_valid": result.is_valid,
        "iterations": result.iterations,
        "real_llm_calls": seeded_llm._calls - 1,
        "elapsed_sec": elapsed,
    }


if __name__ == "__main__":
    alpha_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    out = run_demo(alpha_idx)
    out_path = PROJECT_ROOT / "scripts" / "output" / f"react_self_repair_demo_{alpha_idx:03d}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[output] {out_path}")
