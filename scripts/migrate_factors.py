"""迁移因子到新目录结构.

将 quant/factors/alpha_*.yaml 迁移到 quant/factors/101_alphas/stk_alpha_{num}_{hash}/
"""
from __future__ import annotations

import hashlib
import json
import yaml
from pathlib import Path

# 路径配置
SOURCE_DIR = Path("/home/ll/llmwikify/quant/factors")
TARGET_DIR = SOURCE_DIR / "101_alphas"


def compute_code_hash(code: str) -> str:
    """计算代码的 MD5 哈希 (前 6 位)."""
    return hashlib.md5(code.encode()).hexdigest()[:6]


def migrate_factor(yaml_file: Path) -> dict | None:
    """迁移单个因子文件."""
    try:
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        factor = data.get("factor", {})
        
        # 提取 alpha 编号
        alpha_num = yaml_file.stem.split("_")[1]  # "001", "002", etc.
        
        # 获取代码
        l5 = factor.get("l5", {})
        code = l5.get("code", "")
        if not code:
            print(f"  [skip] {yaml_file.name}: no code")
            return None
        
        # 计算代码哈希
        code_hash = compute_code_hash(code)
        
        # 创建新目录名
        new_name = f"stk_alpha_{alpha_num}_{code_hash}"
        new_dir = TARGET_DIR / new_name
        
        # 创建目录结构
        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "backtest").mkdir(exist_ok=True)
        
        # 1. 创建 factor.yaml (L1-L4, L6)
        factor_yaml = {
            "name": new_name,
            "display_name": f"Alpha #{int(alpha_num)}",
            "asset_type": "stk",
            "category": "alpha",
            "status": factor.get("status", "verified"),
            "version": 1,
            "created_at": factor.get("updated_at", "2026-06-23"),
            "updated_at": factor.get("updated_at", "2026-06-23"),
            "l1": factor.get("l1", {}),
            "l2": factor.get("l2", {}),
            "l3": factor.get("l3", {}),
            "l4": factor.get("l4", {}),
            "l6": factor.get("l6", {}),
        }
        (new_dir / "factor.yaml").write_text(
            yaml.dump(factor_yaml, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8"
        )
        
        # 2. 创建 code.py
        (new_dir / "code.py").write_text(code, encoding="utf-8")
        
        # 3. 创建 meta.json
        meta = {
            "name": new_name,
            "display_name": f"Alpha #{int(alpha_num)}",
            "asset_type": "stk",
            "category": "alpha",
            "source": "101_alphas",
            "alpha_index": int(alpha_num),
            "code_hash": code_hash,
            "created_at": factor.get("updated_at", "2026-06-23"),
            "updated_at": factor.get("updated_at", "2026-06-23"),
            "version": 1,
            "status": factor.get("status", "verified"),
        }
        (new_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # 4. 创建 backtest/latest.json
        assessment = l5.get("overall_assessment", {})
        latest = {
            "run_id": f"pipeline_a_{alpha_num}",
            "created_at": "2026-06-23T10:06:09+08:00",
            "status": "success",
            "metrics": {
                "ic_mean": assessment.get("ic_mean"),
                "icir": assessment.get("icir"),
                "win_rate": assessment.get("winrate"),
                "annual_return": assessment.get("annual_return"),
                "longshort_max_dd": assessment.get("longshort_max_dd"),
            },
        }
        (new_dir / "backtest" / "latest.json").write_text(
            json.dumps(latest, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {
            "name": new_name,
            "alpha_num": alpha_num,
            "code_hash": code_hash,
        }
        
    except Exception as exc:
        print(f"  [error] {yaml_file.name}: {exc}")
        return None


def create_index_yaml(factors: list[dict]) -> None:
    """创建 index.yaml 索引文件."""
    index = {
        "updated_at": "2026-06-23",
        "workspaces": [
            {
                "name": "101_alphas",
                "display_name": "101 Formulaic Alphas",
                "factor_count": len(factors),
                "asset_class": "stk",
                "category": "alpha",
            }
        ],
        "factors": [
            {
                "name": f["name"],
                "workspace": "101_alphas",
                "display_name": f"Alpha #{int(f['alpha_num'])}",
                "status": "verified",
                "updated_at": "2026-06-23",
            }
            for f in factors
        ],
    }
    (TARGET_DIR / "index.yaml").write_text(
        yaml.dump(index, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8"
    )


def main():
    """主函数."""
    print("=" * 60)
    print("  因子迁移脚本")
    print("=" * 60)
    print(f"  源目录: {SOURCE_DIR}")
    print(f"  目标目录: {TARGET_DIR}")
    print()
    
    # 获取所有因子文件
    yaml_files = sorted(SOURCE_DIR.glob("alpha_*.yaml"))
    print(f"  找到 {len(yaml_files)} 个因子文件")
    print()
    
    # 迁移因子
    factors = []
    for i, yaml_file in enumerate(yaml_files, 1):
        print(f"  [{i:3d}/{len(yaml_files)}] {yaml_file.name}", end=" ")
        result = migrate_factor(yaml_file)
        if result:
            factors.append(result)
            print(f"-> {result['name']}")
        else:
            print("-> skipped")
    
    print()
    print(f"  成功迁移: {len(factors)}/{len(yaml_files)}")
    
    # 创建索引
    print("  创建 index.yaml...")
    create_index_yaml(factors)
    
    print()
    print("=" * 60)
    print("  迁移完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
