"""Fix l1.definition in factor.yaml: overwrite formula with NL description from pass2.json.

Updates BOTH:
  - /home/ll/llmwikify/quant/factors/101_alphas/  (source of truth)
  - /home/ll/Public/strategy/quant/factors/101_alphas/  (server reads from here)

Usage:
    python scripts/fix_definition_from_pass2.py
    python scripts/fix_definition_from_pass2.py --dry-run
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

FACTORS_ROOT = Path(__file__).resolve().parents[1] / "quant" / "factors" / "101_alphas"
STRATEGY_ROOT = Path("/home/ll/Public/strategy/quant/factors/101_alphas")
PASS2_JSON = FACTORS_ROOT / "data" / "pass2.json"


def build_mapping() -> dict[str, str]:
    """Map display_name 'Alpha #N' → factor directory name 'stk_alpha_NNN_hash'."""
    mapping: dict[str, str] = {}
    for d in FACTORS_ROOT.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        fy = d / "factor.yaml"
        if not fy.exists():
            continue
        with open(fy) as f:
            data = yaml.safe_load(f)
        display = data.get("display_name", "")
        if display.startswith("Alpha #"):
            num = display.replace("Alpha #", "").strip()
            mapping[num] = d.name
    return mapping


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    with open(PASS2_JSON) as f:
        pass2 = json.load(f)
    details = pass2["pass2_details"]

    mapping = build_mapping()
    print(f"Loaded {len(details)} pass2 entries, mapped {len(mapping)} YAML dirs")

    updated = 0
    skipped = 0
    errors = 0
    synced = 0

    for d in details:
        p2_name = d.get("name", "").replace("Alpha#", "")
        yaml_dir = mapping.get(p2_name)
        if not yaml_dir:
            print(f"  SKIP (no mapping): {d.get('name')}")
            skipped += 1
            continue

        l1 = d.get("l1") or {}
        nl_def = (l1.get("definition", "") or "").strip()
        if not nl_def:
            print(f"  SKIP (empty def): Alpha#{p2_name} → {yaml_dir}")
            skipped += 1
            continue

        fy = FACTORS_ROOT / yaml_dir / "factor.yaml"
        try:
            with open(fy) as f:
                data = yaml.safe_load(f)
            old_def = data.get("l1", {}).get("definition", "")
            if old_def == nl_def:
                skipped += 1
                continue

            if not dry_run:
                data.setdefault("l1", {})["definition"] = nl_def
                with open(fy, "w") as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

                # Sync to strategy directory (server reads from here)
                strategy_fy = STRATEGY_ROOT / yaml_dir / "factor.yaml"
                if strategy_fy.exists():
                    shutil.copy2(fy, strategy_fy)
                    synced += 1

            print(f"  {'DRY' if dry_run else 'OK'}: Alpha#{p2_name} → {yaml_dir}")
            print(f"    old: {old_def[:80]}")
            print(f"    new: {nl_def[:80]}")
            updated += 1
        except Exception as e:
            print(f"  ERROR: Alpha#{p2_name} → {yaml_dir}: {e}")
            errors += 1

    print(f"\nDone: updated={updated}, synced={synced}, skipped={skipped}, errors={errors}")


if __name__ == "__main__":
    main()
