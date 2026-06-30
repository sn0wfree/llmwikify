"""
05 — Paper → Factor → Backtest（无 LLM 版）

对应 TUTORIAL.md §场景 5
=======================

演示：
1. llmwikify quant-init  等价（手动建目录结构）
2. 写一份 6-layer Factor YAML
3. 读 + 列因子库
4. update_index 刷新
5. 读 DuckDB 验证 schema

不依赖 LLM / quantnodes。完整 paper→factor LLM 抽取 + 数据回测
见 TUTORIAL §5.2 Step 2-7。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from llmwikify.reproduction.persist.factor_library import (
    list_factors,
    read_factor_yaml,
    update_index,
    write_factor_yaml,
)

FACTOR_MOMENTUM = {
    "factor": {
        "name": "momentum_20d",
        "name_cn": "20日动量",
        "asset_type": "stock",
        "category": "price",
        "subcategory": "momentum",
        "status": "已注册",
        "l1": {
            "definition": "20 日动量因子：过去 20 个交易日的对数收益率。",
            "formula": "log(close / close.shift(20))",
            "tags": ["momentum", "trend-following"],
        },
        "l2_computation": {
            "code": (
                "import pandas as pd\n"
                "def compute(df: pd.DataFrame) -> pd.Series:\n"
                "    return (df['close'] / df['close'].shift(20)).apply(\n"
                "        lambda x: float('nan') if x <= 0 else __import__('math').log(x)\n"
                "    )\n"
            ),
            "input_columns": ["close"],
            "output": "float (per row)",
        },
        "l3_intuition": {
            "financial_meaning": "捕捉股票过去 20 日的趋势延续性。",
            "expected_sign": "positive (趋势跟随)",
        },
        "l4_hypothesis": {
            "hypothesis": "高 20 日动量股票未来 5 日有正收益。",
            "rationale": "动量效应是经典 Anomalies 之一。",
        },
        "l5_validation": {
            "metrics": ["IC", "RankIC", "5-quantile long-short"],
            "stability_check": "rolling 60-day IC std",
        },
        "l6_risk": {
            "drawdown_risk": "动量崩溃 (momentum crash) in 2009 / 2020-Q1",
            "mitigation": "结合 vol filter / regime detection",
        },
    }
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        quant = project_root / "quant"
        (quant / "factors" / "stock" / "price").mkdir(parents=True)
        (quant / "factorbacktest").mkdir()
        (quant / "papers").mkdir()
        (quant / "datacache").mkdir()

        print(f"📁 quant/ scaffolded at {quant}")
        print(f"   {sorted(p.name for p in quant.iterdir())}")

        # Step 1：写 6-layer Factor YAML
        path = write_factor_yaml(
            "stock/price/momentum_20d",
            FACTOR_MOMENTUM,
            project_root=project_root,
        )
        print(f"\n✍️  Wrote factor YAML: {path}")

        # Step 2：update_index（重建 quant/factors/index.yaml，list_factors 读这个）
        update_index(project_root=project_root)
        index_path = quant / "factors" / "index.yaml"
        print(f"🗂️  index.yaml updated: {index_path.exists()}")

        # Step 3：列因子
        factors = list_factors(project_root=project_root)
        print(f"\n📚 list_factors: {len(factors)} factors")
        for f in factors:
            print(f"   - {f.get('name', '?'):30s} {f.get('category', '?')}")

        # Step 4：读单个
        f = read_factor_yaml("stock/price/momentum_20d",
                             project_root=project_root)
        if f:
            inner = f.get("factor", f)
            l1 = inner.get("l1", {})
            l2 = inner.get("l2_computation", {})
            print("\n🔍 read_factor_yaml('stock/price/momentum_20d'):")
            print(f"   L1: {l1.get('definition', '?')}")
            print(f"   L2 code (前 60 字符): {l2.get('code', '')[:60]}...")

        # Step 5：DuckDB schema（不真跑数据写入，只 import + 展示）
        try:
            import duckdb
            db_path = quant / "factor.duckdb"
            con = duckdb.connect(str(db_path))
            con.execute(
                "CREATE TABLE IF NOT EXISTS factor_values ("
                "date DATE, stock VARCHAR, factor_name VARCHAR, value DOUBLE)"
            )
            print(f"\n🦆 DuckDB ready: {db_path}")
            tables = con.execute("SHOW TABLES").fetchall()
            print(f"   tables: {tables}")
            con.close()
        except Exception as e:
            print(f"\n🦆 DuckDB skipped: {e}")

        # 列出文件树
        print("\n📂 File tree:")
        for p in sorted(quant.rglob("*")):
            if p.is_file():
                depth = len(p.relative_to(quant).parts)
                print(f"   {'  ' * depth}{p.name}")

        print("\n🎉 Done. quant/ scaffold ready.")


if __name__ == "__main__":
    main()
    sys.exit(0)
