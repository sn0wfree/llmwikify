"""``quant-init`` command — initialize quant research directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, print_success, print_warning


def run_quant_init(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Initialize quant research directory at {wiki_root}/quant/.

    Creates:
        quant/
        ├── papers/
        ├── factors/
        │   ├── index.yaml
        │   ├── stock/price/
        │   └── stock/fundamental/
        ├── factorbacktest/
        ├── strategies/
        ├── datacache/
        └── index.md

    Also creates an empty factor.duckdb with the factor_values table.
    Idempotent: skips existing directories/files.
    """
    root = Path(wiki_root)
    quant_root = root / "quant"
    created = []
    skipped = []

    # Directory structure
    dirs = [
        (quant_root, "quant/"),
        (quant_root / "papers", "quant/papers/"),
        (quant_root / "factors", "quant/factors/"),
        (quant_root / "factors" / "stock" / "price", "quant/factors/stock/price/"),
        (quant_root / "factors" / "stock" / "fundamental", "quant/factors/stock/fundamental/"),
        (quant_root / "factorbacktest", "quant/factorbacktest/"),
        (quant_root / "strategies", "quant/strategies/"),
        (quant_root / "datacache", "quant/datacache/"),
    ]

    for dir_path, name in dirs:
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            created.append(name)
        else:
            skipped.append(name)

    # index.yaml
    index_yaml = quant_root / "factors" / "index.yaml"
    if not index_yaml.exists():
        index_yaml.write_text(
            "# 因子库索引\n"
            "# 由 llmwikify quant-init 自动生成\n\n"
            "factors: []\n\n"
            "statistics:\n"
            "  total: 0\n"
            "  by_asset_type:\n"
            "    stock: 0\n"
            "    futures: 0\n"
            "    options: 0\n"
            "  by_category:\n"
            "    price: 0\n"
            "    fundamental: 0\n"
            "    composite: 0\n"
            "  by_status:\n"
            "    已注册: 0\n"
            "    待验证: 0\n"
            "    已通过: 0\n"
            "    失败: 0\n",
            encoding="utf-8",
        )
        created.append("quant/factors/index.yaml")
    else:
        skipped.append("quant/factors/index.yaml")

    # index.md
    index_md = quant_root / "index.md"
    if not index_md.exists():
        index_md.write_text(
            "# Quant Research Index\n\n"
            "> 量化研究索引，由 llmwikify quant-init 自动生成\n\n"
            "## 目录\n\n"
            "- `papers/` — 论文理解结果\n"
            "- `factors/` — 因子库（6 层 YAML）\n"
            "- `factorbacktest/` — 回测结果\n"
            "- `strategies/` — 策略定义\n"
            "- `datacache/` — OHLCV 数据缓存\n"
            "- `factor.duckdb` — 因子值矩阵\n",
            encoding="utf-8",
        )
        created.append("quant/index.md")
    else:
        skipped.append("quant/index.md")

    # factor.duckdb with empty table
    duckdb_path = quant_root / "factor.duckdb"
    if not duckdb_path.exists():
        try:
            import duckdb
            con = duckdb.connect(str(duckdb_path))
            con.execute("""
                CREATE TABLE factor_values (
                    date DATE,
                    stock VARCHAR,
                    factor_name VARCHAR,
                    value DOUBLE
                )
            """)
            con.close()
            created.append("quant/factor.duckdb")
        except ImportError:
            skipped.append("quant/factor.duckdb (duckdb not installed)")
    else:
        skipped.append("quant/factor.duckdb")

    # Report
    if not created:
        print_warning(f"Quant research already initialized at {quant_root}")
        print(f"   Existing: {', '.join(skipped)}")
        print("   Use --overwrite to reinitialize.")
        return 0

    print_success(f"Quant research initialized at {quant_root}")
    print()
    if created:
        print(f"  Created: {', '.join(created)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    print()
    print("  Next steps:")
    print("    1. Add factor YAMLs to quant/factors/")
    print("    2. Run: llmwikify serve --web")
    print("    3. Visit /agent/factor to run backtests")

    return 0


class QuantInitCommand(Command):
    """``quant-init`` command — initialize quant research directory."""

    name = "quant-init"
    help = "Initialize quant research directory"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--overwrite", action="store_true",
            help="Recreate quant directory structure",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_quant_init(wiki, wiki.root, args)
