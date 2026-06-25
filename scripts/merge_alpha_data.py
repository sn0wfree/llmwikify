#!/usr/bin/env python3
"""Merge standalone alpha_*.yaml L5 data into 101_alphas family members."""

import json
import shutil
from pathlib import Path

import yaml

FACTORS_ROOT = Path("quant/factors")
FAMILY_DIR = FACTORS_ROOT / "101_alphas"
ARCHIVE_DIR = FACTORS_ROOT / "_archive" / "101_alphas_standalone"


def load_standalone(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("factor", data)


def load_family_member_meta(entry: Path) -> int | None:
    mj = entry / "meta.json"
    if mj.exists():
        return json.loads(mj.read_text(encoding="utf-8")).get("alpha_index")
    return None


def make_dir_name(idx: int, code_hash: str = "merged") -> str:
    return f"stk_alpha_{idx:03d}_{code_hash}"


def main():
    # 1. Build index: alpha_index -> family member dir
    family_index: dict[int, Path] = {}
    for entry in FAMILY_DIR.iterdir():
        if not entry.is_dir():
            continue
        idx = load_family_member_meta(entry)
        if idx is not None:
            family_index[idx] = entry

    print(f"Family members: {len(family_index)}")

    # 2. Process standalone files
    standalone_files = sorted(FACTORS_ROOT.glob("alpha_*.yaml"))
    print(f"Standalone files: {len(standalone_files)}")

    merged = 0
    created = 0
    skipped = 0

    for sf in standalone_files:
        s_factor = load_standalone(sf)
        name = s_factor.get("name", sf.stem)
        try:
            idx = int(name.replace("alpha_", ""))
        except ValueError:
            print(f"  SKIP {sf.name}: cannot parse alpha_index")
            skipped += 1
            continue

        if idx in family_index:
            # Merge L5 into existing family member
            family_entry = family_index[idx]
            family_yaml = family_entry / "factor.yaml"
            f_data = yaml.safe_load(family_yaml.read_text(encoding="utf-8")) or {}

            s_l5 = s_factor.get("l5")
            if s_l5 and not f_data.get("l5"):
                f_data["l5"] = s_l5
                family_yaml.write_text(
                    yaml.dump(f_data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
                print(f"  MERGED alpha-{idx:03d}: L5 added to {family_entry.name}")
                merged += 1
            elif f_data.get("l5"):
                print(f"  SKIP alpha-{idx:03d}: family already has L5")
                skipped += 1
            else:
                print(f"  SKIP alpha-{idx:03d}: no L5 in standalone")
                skipped += 1
        else:
            # Create new family member directory
            dir_name = make_dir_name(idx)
            new_entry = FAMILY_DIR / dir_name
            new_entry.mkdir(exist_ok=True)

            # Write factor.yaml with proper structure
            new_factor = {
                "name": dir_name,
                "display_name": f"Alpha #{idx}",
                "asset_type": "stk",
                "category": "alpha",
                "status": "已验证",
                "version": 1,
                "created_at": "2026-06-25",
                "updated_at": "2026-06-25",
            }
            # Copy L1-L6 from standalone
            for layer in ["l1", "l2", "l3", "l4", "l5", "l6"]:
                if s_factor.get(layer):
                    new_factor[layer] = s_factor[layer]

            (new_entry / "factor.yaml").write_text(
                yaml.dump(new_factor, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )

            # Write meta.json
            meta = {
                "name": dir_name,
                "display_name": f"Alpha #{idx}",
                "asset_type": "stk",
                "category": "alpha",
                "source": "101_alphas",
                "alpha_index": idx,
                "code_hash": "merged",
                "created_at": "2026-06-25",
                "updated_at": "2026-06-25",
                "version": 1,
                "status": "已验证",
            }
            (new_entry / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            print(f"  CREATED alpha-{idx:03d}: {dir_name}")
            created += 1

    print(f"\nSummary: merged={merged}, created={created}, skipped={skipped}")

    # 3. Archive standalone files
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for sf in standalone_files:
        dest = ARCHIVE_DIR / sf.name
        shutil.move(str(sf), str(dest))
    print(f"Archived {len(standalone_files)} standalone files to {ARCHIVE_DIR}")

    # 4. Update _meta.yaml
    meta_path = FAMILY_DIR / "_meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    new_count = len(list(FAMILY_DIR.iterdir())) - 1  # exclude _meta.yaml itself
    # Actually count factor.yaml files
    real_count = sum(1 for e in FAMILY_DIR.iterdir() if e.is_dir() and (e / "factor.yaml").exists())
    meta["factor_count"] = real_count
    meta["updated_at"] = "2026-06-25"
    meta_path.write_text(
        yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Updated _meta.yaml: factor_count={real_count}")

    # 5. Rebuild index.yaml
    build_index(FAMILY_DIR)


def build_index(family_dir: Path):
    """Rebuild index.yaml from family member factor.yaml + meta.json."""
    members = []
    for entry in sorted(family_dir.iterdir()):
        if not entry.is_dir():
            continue
        fy = entry / "factor.yaml"
        if not fy.exists():
            continue
        data = yaml.safe_load(fy.read_text(encoding="utf-8")) or {}
        mj = entry / "meta.json"
        meta = json.loads(mj.read_text(encoding="utf-8")) if mj.exists() else {}
        idx = meta.get("alpha_index")
        definition = data.get("l1", {}).get("definition", "") if isinstance(data.get("l1"), dict) else ""
        members.append({
            "name": data.get("name", entry.name),
            "name_cn": data.get("display_name", ""),
            "asset_type": data.get("asset_type", "stk"),
            "category": data.get("category", "alpha"),
            "subcategory": data.get("subcategory", ""),
            "status": data.get("status", "草稿"),
            "definition": definition,
            "file": f"101_alphas/{entry.name}",
        })

    # Statistics
    status_counts = {}
    for m in members:
        s = m["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    index_data = {
        "updated_at": "2026-06-25",
        "statistics": {
            "total": len(members),
            "by_status": status_counts,
        },
        "factors": members,
    }

    index_path = family_dir / "index.yaml"
    index_path.write_text(
        yaml.dump(index_data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Rebuilt index.yaml: {len(members)} factors")


if __name__ == "__main__":
    main()
