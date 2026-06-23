"""Phase 1: LLM 代码生成 + 回测.

从 track_b_checkpoint.json 读取公式，生成 Python 代码，
运行 QuantNodes PipelineRunner 回测，输出 single_factor_NNN.json。

Usage:
    cd quant/factors/101_alphas
    python scripts/phase1_code_gen.py --start 1 --end 101
    python scripts/phase1_code_gen.py --start 1 --end 5 --skip-existing
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

# 加载配置
CONFIG_PATH = Path(__file__).parent / "config.yaml"
CONFIG = yaml.safe_load(CONFIG_PATH.read_text())

# 路径配置
WORKSPACE_ROOT = Path(__file__).parent.parent
DATA_DIR = WORKSPACE_ROOT / CONFIG["paths"]["data_dir"]
OUTPUT_DIR = WORKSPACE_ROOT / CONFIG["paths"]["output_dir"]
TRACK_B = WORKSPACE_ROOT / CONFIG["paths"]["track_b"]
H5_DIR = WORKSPACE_ROOT / CONFIG["paths"]["h5_dir"]
FACTORS_DIR = WORKSPACE_ROOT / CONFIG["paths"]["factors_dir"]

# 日期配置
DATE_START = CONFIG["date_range"]["start"]
DATE_END = CONFIG["date_range"]["end"]

# 数据列配置
DATA_COLUMNS = CONFIG["data_columns"]


def load_formulas() -> list[dict]:
    """加载公式列表."""
    if not TRACK_B.exists():
        raise FileNotFoundError(f"Track B file not found: {TRACK_B}")
    data = json.loads(TRACK_B.read_text(encoding="utf-8"))
    return data["pass1_signals"]


def load_data():
    """加载 H5 数据."""
    import pandas as pd
    import polars as pl

    h5_path = H5_DIR / "stk_daily.h5"
    if not h5_path.exists():
        raise FileNotFoundError(f"H5 file not found: {h5_path}")

    # 读取数据
    with pd.HDFStore(str(h5_path), "r") as store:
        close_key = "close" if "/close" in store.keys() else "cp"
        cp_wide = pd.read_hdf(str(h5_path), close_key)
        open_wide = pd.read_hdf(str(h5_path), "open")
        high_wide = pd.read_hdf(str(h5_path), "high")
        low_wide = pd.read_hdf(str(h5_path), "low")
        volume_wide = pd.read_hdf(str(h5_path), "volume")
        returns_wide = pd.read_hdf(str(h5_path), "returns")
        vwap_wide = pd.read_hdf(str(h5_path), "vwap")
        industry_wide = pd.read_hdf(str(h5_path), "id_citic1")

    # 转换为 long 格式
    dfs = []
    for name, wide in [
        ("close", cp_wide),
        ("open", open_wide),
        ("high", high_wide),
        ("low", low_wide),
        ("volume", volume_wide),
        ("returns", returns_wide),
        ("vwap", vwap_wide),
        ("industry", industry_wide),
    ]:
        long = wide.stack().reset_index()
        long.columns = ["date", "code", name]
        long["date"] = long["date"].astype(int)
        dfs.append(long)

    # 合并
    df = dfs[0]
    for d in dfs[1:]:
        df = df.merge(d, on=["date", "code"])

    # 转换为 Polars
    df_pl = pl.from_pandas(df)

    # 过滤日期
    df_pl = df_pl.filter(
        (pl.col("date") >= DATE_START) & (pl.col("date") <= DATE_END)
    )

    return df_pl


def run_one_alpha(
    alpha_index: int,
    formula_brief: str,
    df,
    llm_client,
    use_react: bool = True,
    max_repair_rounds: int = 3,
) -> dict:
    """运行单个 alpha 的 Phase 1."""
    from llmwikify.reproduction.codegen_utils import (
        execute_code,
        extract_python,
        generate_factor_code,
        validate_safety,
        validate_syntax,
    )

    t0 = time.monotonic()

    # 生成代码
    if use_react:
        code, series, error, meta = generate_factor_code(
            factor_name=f"alpha_{alpha_index:03d}",
            formula_brief=formula_brief,
            df=df,
            llm=llm_client,
            max_repair_rounds=max_repair_rounds,
        )
    else:
        # 1-shot 模式
        from llmwikify.reproduction.codegen_utils import SYSTEM_PROMPT_CODE, build_llm_client

        if llm_client is None:
            llm_client = build_llm_client()

        response = llm_client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_CODE},
                {"role": "user", "content": f"Formula: {formula_brief}\n\nWrite Python code."},
            ],
            temperature=0.3,
        )

        code = extract_python(response)
        if code is None:
            return {
                "status": "failed",
                "stage": "extract",
                "error": "No code extracted",
                "elapsed_sec": time.monotonic() - t0,
            }

        # 验证语法
        syntax_ok, syntax_err = validate_syntax(code)
        if not syntax_ok:
            return {
                "status": "failed",
                "stage": "syntax",
                "error": syntax_err,
                "elapsed_sec": time.monotonic() - t0,
            }

        # 验证安全
        safe_ok, safe_err = validate_safety(code)
        if not safe_ok:
            return {
                "status": "failed",
                "stage": "safety",
                "error": safe_err,
                "elapsed_sec": time.monotonic() - t0,
            }

        # 执行代码
        try:
            series = execute_code(code, df)
        except Exception as exc:
            return {
                "status": "failed",
                "stage": "execute",
                "error": str(exc),
                "elapsed_sec": time.monotonic() - t0,
            }

        meta = {}

    elapsed = time.monotonic() - t0

    if code is None or series is None:
        return {
            "status": "failed",
            "stage": "generate",
            "error": error or "Unknown error",
            "elapsed_sec": elapsed,
            "meta": meta,
        }

    # 保存结果
    result = {
        "alpha_index": alpha_index,
        "status": "success",
        "formula_brief": formula_brief,
        "code": code,
        "code_chars": len(code),
        "elapsed_sec": round(elapsed, 2),
        "meta": meta,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Phase 1: LLM Code Generation + Backtest")
    parser.add_argument("--start", type=int, default=1, help="Start alpha index")
    parser.add_argument("--end", type=int, default=101, help="End alpha index")
    parser.add_argument("--skip-existing", action="store_true", help="Skip existing results")
    parser.add_argument("--no-react", action="store_true", help="Use 1-shot instead of ReAct")
    parser.add_argument("--rounds", type=int, default=3, help="Max repair rounds")
    args = parser.parse_args()

    print("=" * 60)
    print("  Phase 1: LLM Code Generation + Backtest")
    print("=" * 60)
    print(f"  Workspace: {WORKSPACE_ROOT}")
    print(f"  Range: {args.start}-{args.end}")
    print(f"  Mode: {'1-shot' if args.no_react else 'ReAct'}")
    print()

    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载公式
    formulas = load_formulas()
    print(f"  Loaded {len(formulas)} formulas")

    # 加载数据
    print("  Loading data...")
    df = load_data()
    print(f"  Data shape: {df.shape}")

    # 创建 LLM 客户端
    from llmwikify.reproduction.codegen_utils import build_llm_client

    llm_client = build_llm_client()
    print(f"  LLM client: {type(llm_client).__name__}")

    print()

    # 运行
    results = []
    for i in range(args.start, args.end + 1):
        # 检查是否已存在
        output_path = OUTPUT_DIR / f"single_factor_{i:03d}.json"
        if args.skip_existing and output_path.exists():
            print(f"  [{i:03d}] skipping (exists)")
            continue

        # 获取公式
        if i - 1 >= len(formulas):
            print(f"  [{i:03d}] formula not found")
            continue

        formula = formulas[i - 1]
        formula_brief = formula.get("formula_brief", "")

        print(f"  [{i:03d}] running...", end=" ", flush=True)

        # 运行
        result = run_one_alpha(
            alpha_index=i,
            formula_brief=formula_brief,
            df=df,
            llm_client=llm_client,
            use_react=not args.no_react,
            max_repair_rounds=args.rounds,
        )

        # 保存结果
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        results.append(result)

        status = result.get("status", "?")
        elapsed = result.get("elapsed_sec", 0)
        print(f"{status} ({elapsed:.1f}s)")

    # 统计
    success = sum(1 for r in results if r.get("status") == "success")
    print()
    print(f"  Results: {success}/{len(results)} success")

    # 保存汇总
    summary_path = OUTPUT_DIR / "phase1_summary.json"
    summary_path.write_text(json.dumps({
        "start": args.start,
        "end": args.end,
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "results": results,
    }, ensure_ascii=False, indent=2))

    print(f"  Summary: {summary_path}")
    print()
    print("=" * 60)
    print("  Phase 1 Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
