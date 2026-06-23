"""Phase 3: LLM 元数据提取.

从 single_factor_NNN.json 读取代码，提取 L2-L6 元数据，
写入 factor.yaml。

Usage:
    cd quant/factors/101_alphas
    python scripts/phase3_metadata.py --start 1 --end 101
    python scripts/phase3_metadata.py --start 1 --end 5 --skip-existing
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
OUTPUT_DIR = WORKSPACE_ROOT / CONFIG["paths"]["output_dir"]
FACTORS_DIR = WORKSPACE_ROOT / CONFIG["paths"]["factors_dir"]


def run_phase3(
    start: int = 1,
    end: int = 101,
    skip_existing: bool = False,
    batch_size: int = 3,
):
    """运行 Phase 3 元数据提取."""
    from llmwikify.reproduction.codegen_utils import build_llm_client
    from llmwikify.reproduction.factor_extractor import extract_batch

    print("=" * 60)
    print("  Phase 3: LLM Metadata Extraction")
    print("=" * 60)
    print(f"  Workspace: {WORKSPACE_ROOT}")
    print(f"  Range: {start}-{end}")
    print(f"  Batch size: {batch_size}")
    print()

    # 收集可用的 alpha 索引
    available = []
    for i in range(start, end + 1):
        json_path = OUTPUT_DIR / f"single_factor_{i:03d}.json"
        if json_path.exists():
            available.append(i)
        elif not skip_existing:
            print(f"  [{i:03d}] JSON not found, skipping")

    if not available:
        print("  No available alphas to process")
        return

    print(f"  Available: {len(available)} alphas")
    print()

    # 批量提取
    results = extract_batch(
        alpha_indices=available,
        output_dir=OUTPUT_DIR,
        papers_dir=WORKSPACE_ROOT / "data",
        batch_size=batch_size,
    )

    # 统计
    success = sum(1 for r in results if r.get("status") == "success")
    print()
    print(f"  Results: {success}/{len(results)} success")

    # 保存汇总
    summary_path = OUTPUT_DIR / "phase3_summary.json"
    summary_path.write_text(json.dumps({
        "start": start,
        "end": end,
        "total": len(results),
        "success": success,
        "failed": len(results) - success,
        "results": results,
    }, ensure_ascii=False, indent=2))

    print(f"  Summary: {summary_path}")
    print()
    print("=" * 60)
    print("  Phase 3 Complete!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Phase 3: LLM Metadata Extraction")
    parser.add_argument("--start", type=int, default=1, help="Start alpha index")
    parser.add_argument("--end", type=int, default=101, help="End alpha index")
    parser.add_argument("--skip-existing", action="store_true", help="Skip existing results")
    parser.add_argument("--batch-size", type=int, default=3, help="Batch size")
    args = parser.parse_args()

    run_phase3(
        start=args.start,
        end=args.end,
        skip_existing=args.skip_existing,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
