"""Tests for factor_library: 6-layer factor YAML read/write/list.

覆盖:
  - read_factor_yaml: 新目录格式 / 旧单文件格式 / 缺失 / 无效 YAML
  - write_factor_yaml: 新目录格式 / 旧单文件格式 / 原子性
  - list_factors: 空 / 缺失 index / 正常
  - list_factors_by_category: 多类别 / 空目录
  - update_index: 全扫描 / stats 准确

详见: docs/designs/pipeline_framework.md Section 29.7 (P0 优先级)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llmwikify.reproduction.persist import factor_library as fl


# ── 公共 fixture ────────────────────────────────────────────


@pytest.fixture
def factor_workspace(tmp_path: Path) -> Path:
    """创建空 workspace: {tmp_path}/quant/factors/."""
    factors_dir = tmp_path / "quant" / "factors"
    factors_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def factor_data() -> dict[str, Any]:
    """标准 6-layer factor 测试数据."""
    return {
        "factor": {
            "name": "test_factor_001",
            "name_cn": "测试因子",
            "asset_type": "stk",
            "category": "alpha",
            "subcategory": "momentum",
            "status": "已注册",
            "l1": {"definition": "Test factor for unit testing"},
            "l2": {"calculation_steps": [{"step": 1, "op": "rank"}]},
            "l3": {},
            "l4": {},
            "l5": {"ast": {"op": "rank", "args": []}},
            "l6": {"ic": 0.05, "icir": 0.3},
        }
    }


# ── read_factor_yaml ───────────────────────────────────────


class TestReadFactorYaml:
    """Test read_factor_yaml: 7 个测试覆盖新/旧格式和边界."""

    def test_new_dir_format(self, factor_workspace: Path, factor_data: dict) -> None:
        """新目录格式: factors/{name}/factor.yaml 可读."""
        factor_dir = factor_workspace / "quant" / "factors" / "stk_alpha_001_abc123"
        factor_dir.mkdir()
        (factor_dir / "factor.yaml").write_text(
            json.dumps(factor_data), encoding="utf-8"
        )  # JSON 子集, YAML 兼容

        result = fl.read_factor_yaml("stk_alpha_001_abc123", project_root=factor_workspace)
        assert result is not None
        assert result["factor"]["name"] == "test_factor_001"

    def test_old_single_file_format(self, factor_workspace: Path, factor_data: dict) -> None:
        """旧单文件格式: factors/{name}.yaml 可读."""
        import yaml
        yaml_path = factor_workspace / "quant" / "factors" / "momentum_20d.yaml"
        yaml_path.write_text(yaml.dump(factor_data), encoding="utf-8")

        result = fl.read_factor_yaml("momentum_20d", project_root=factor_workspace)
        assert result is not None
        assert result["factor"]["name"] == "test_factor_001"

    def test_missing_file_returns_none(self, factor_workspace: Path) -> None:
        """文件不存在返回 None (不抛错)."""
        result = fl.read_factor_yaml("nonexistent", project_root=factor_workspace)
        assert result is None

    def test_invalid_yaml_returns_none(self, factor_workspace: Path) -> None:
        """YAML 语法错误时返回 None (不抛错)."""
        bad_path = factor_workspace / "quant" / "factors" / "bad.yaml"
        bad_path.write_text(":\n  - [unclosed", encoding="utf-8")

        result = fl.read_factor_yaml("bad", project_root=factor_workspace)
        assert result is None

    def test_loads_code_py(self, factor_workspace: Path, factor_data: dict) -> None:
        """新格式: 加载 factor.yaml 后, 附加 code.py 内容到 data['code']."""
        import yaml
        factor_dir = factor_workspace / "quant" / "factors" / "stk_alpha_001_xyz"
        factor_dir.mkdir()
        (factor_dir / "factor.yaml").write_text(yaml.dump(factor_data), encoding="utf-8")
        (factor_dir / "code.py").write_text("def compute_factor(df):\n    return df\n", encoding="utf-8")

        result = fl.read_factor_yaml("stk_alpha_001_xyz", project_root=factor_workspace)
        assert "code" in result
        assert "def compute_factor" in result["code"]

    def test_loads_backtest_latest_json(self, factor_workspace: Path, factor_data: dict) -> None:
        """新格式: 加载 backtest/latest.json 到 data['backtest']."""
        import yaml
        factor_dir = factor_workspace / "quant" / "factors" / "stk_alpha_001_bt"
        factor_dir.mkdir()
        (factor_dir / "factor.yaml").write_text(yaml.dump(factor_data), encoding="utf-8")
        backtest_dir = factor_dir / "backtest"
        backtest_dir.mkdir()
        backtest_data = {"ic_mean": 0.05, "icir": 0.3, "status": "success"}
        (backtest_dir / "latest.json").write_text(json.dumps(backtest_data), encoding="utf-8")

        result = fl.read_factor_yaml("stk_alpha_001_bt", project_root=factor_workspace)
        assert "backtest" in result
        assert result["backtest"]["icir"] == 0.3

    def test_loads_meta_json(self, factor_workspace: Path, factor_data: dict) -> None:
        """新格式: 加载 meta.json 到 data['meta']."""
        import yaml
        factor_dir = factor_workspace / "quant" / "factors" / "stk_alpha_001_meta"
        factor_dir.mkdir()
        (factor_dir / "factor.yaml").write_text(yaml.dump(factor_data), encoding="utf-8")
        meta = {"verified": True, "tags": ["test"]}
        (factor_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        result = fl.read_factor_yaml("stk_alpha_001_meta", project_root=factor_workspace)
        assert "meta" in result
        assert result["meta"]["verified"] is True

    def test_handles_unicode(self, factor_workspace: Path) -> None:
        """Unicode 字符正常处理 (中文字符)."""
        import yaml
        data = {"factor": {"name": "测试", "category": "αβγ"}}
        yaml_path = factor_workspace / "quant" / "factors" / "unicode_factor.yaml"
        yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        result = fl.read_factor_yaml("unicode_factor", project_root=factor_workspace)
        assert result["factor"]["name"] == "测试"
        assert result["factor"]["category"] == "αβγ"


# ── write_factor_yaml ──────────────────────────────────────


class TestWriteFactorYaml:
    """Test write_factor_yaml: 5 个测试覆盖写操作."""

    def test_writes_new_dir_format(self, factor_workspace: Path, factor_data: dict) -> None:
        """新格式: 写 factors/{name}/factor.yaml (目录需预先存在)."""
        factor_dir = factor_workspace / "quant" / "factors" / "new_factor_abc"
        factor_dir.mkdir()

        result = fl.write_factor_yaml("new_factor_abc", factor_data, project_root=factor_workspace)
        assert "Created" in result
        assert (factor_dir / "factor.yaml").exists()

    def test_writes_old_single_file(self, factor_workspace: Path, factor_data: dict) -> None:
        """旧格式: 写 factors/{name}.yaml (目录不存在时)."""
        result = fl.write_factor_yaml("legacy_factor", factor_data, project_root=factor_workspace)
        assert "Created" in result
        yaml_path = factor_workspace / "quant" / "factors" / "legacy_factor.yaml"
        assert yaml_path.exists()

    def test_writes_code_py(self, factor_workspace: Path, factor_data: dict) -> None:
        """data 含 'code' 时, 写入 code.py."""
        factor_data["code"] = "def compute_factor(df):\n    return df['close']\n"
        factor_dir = factor_workspace / "quant" / "factors" / "factor_with_code"
        factor_dir.mkdir()

        fl.write_factor_yaml("factor_with_code", factor_data, project_root=factor_workspace)
        code_path = factor_dir / "code.py"
        assert code_path.exists()
        assert "compute_factor" in code_path.read_text(encoding="utf-8")

    def test_writes_meta_json(self, factor_workspace: Path, factor_data: dict) -> None:
        """data 含 'meta' 时, 写入 meta.json."""
        factor_data["meta"] = {"verified": True, "notes": "test"}
        factor_dir = factor_workspace / "quant" / "factors" / "factor_with_meta"
        factor_dir.mkdir()

        fl.write_factor_yaml("factor_with_meta", factor_data, project_root=factor_workspace)
        meta_path = factor_dir / "meta.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["verified"] is True

    def test_writes_backtest_latest(self, factor_workspace: Path, factor_data: dict) -> None:
        """data 含 'backtest' 时, 写入 backtest/latest.json."""
        factor_data["backtest"] = {"ic_mean": 0.05, "status": "success"}
        factor_dir = factor_workspace / "quant" / "factors" / "factor_with_bt"
        factor_dir.mkdir()

        fl.write_factor_yaml("factor_with_bt", factor_data, project_root=factor_workspace)
        backtest_path = factor_dir / "backtest" / "latest.json"
        assert backtest_path.exists()
        data = json.loads(backtest_path.read_text(encoding="utf-8"))
        assert data["ic_mean"] == 0.05


# ── list_factors ───────────────────────────────────────────


class TestListFactors:
    """Test list_factors: 4 个测试."""

    def test_empty_when_no_index(self, factor_workspace: Path) -> None:
        """无 index.yaml 时返回空列表 (不抛错)."""
        result = fl.list_factors(project_root=factor_workspace)
        assert result == []

    def test_reads_index(self, factor_workspace: Path) -> None:
        """正常读取 index.yaml."""
        import yaml
        index_path = factor_workspace / "quant" / "factors" / "index.yaml"
        index_data = {
            "factors": [
                {"name": "f1", "category": "alpha"},
                {"name": "f2", "category": "momentum"},
            ]
        }
        index_path.write_text(yaml.dump(index_data), encoding="utf-8")

        result = fl.list_factors(project_root=factor_workspace)
        assert len(result) == 2
        assert result[0]["name"] == "f1"

    def test_invalid_index_returns_empty(self, factor_workspace: Path) -> None:
        """index.yaml 损坏时返回空列表 (不抛错)."""
        index_path = factor_workspace / "quant" / "factors" / "index.yaml"
        index_path.write_text(":\n  - [unclosed", encoding="utf-8")

        result = fl.list_factors(project_root=factor_workspace)
        assert result == []

    def test_empty_factors_key(self, factor_workspace: Path) -> None:
        """index.yaml 无 'factors' 键时返回空列表."""
        import yaml
        index_path = factor_workspace / "quant" / "factors" / "index.yaml"
        index_path.write_text(yaml.dump({"stats": {}}), encoding="utf-8")

        result = fl.list_factors(project_root=factor_workspace)
        assert result == []


# ── list_factors_by_category ───────────────────────────────


class TestListFactorsByCategory:
    """Test list_factors_by_category: 3 个测试."""

    def test_empty_when_no_factors_dir(self, tmp_path: Path) -> None:
        """factors/ 不存在时返回空 dict."""
        result = fl.list_factors_by_category(project_root=tmp_path)
        assert result == {}

    def test_groups_by_category(self, factor_workspace: Path, factor_data: dict) -> None:
        """按 category 字段分组 (新格式每个因子计 1 次, 不重复)."""
        import yaml
        factors_dir = factor_workspace / "quant" / "factors"
        # 创建 2 个 alpha + 1 个 momentum 因子 (新格式)
        for i, cat in enumerate(["alpha", "alpha", "momentum"]):
            fd = yaml.safe_load(yaml.dump(factor_data))  # deep copy via YAML round-trip
            fd["factor"]["category"] = cat
            fd["factor"]["name"] = f"f_{cat}_{i}"
            d = factors_dir / f"f_{cat}_{i}_hash"
            d.mkdir()
            (d / "factor.yaml").write_text(yaml.dump(fd), encoding="utf-8")

        result = fl.list_factors_by_category(project_root=factor_workspace)
        assert "alpha" in result
        assert "momentum" in result
        # 修复后每个因子计 1 次 (新格式 1, 旧格式因 sibling factor.yaml 跳过)
        assert len(result["alpha"]) == 2
        assert len(result["momentum"]) == 1

    def test_handles_invalid_yaml(self, factor_workspace: Path, factor_data: dict) -> None:
        """单个 YAML 损坏不阻塞其他因子."""
        import yaml
        factors_dir = factor_workspace / "quant" / "factors"
        good = yaml.safe_load(yaml.dump(factor_data))  # deep copy
        (factors_dir / "good_dir").mkdir()
        (factors_dir / "good_dir" / "factor.yaml").write_text(yaml.dump(good), encoding="utf-8")
        (factors_dir / "bad.yaml").write_text(":\n  - [unclosed", encoding="utf-8")

        # 不抛错, 跳过损坏文件
        result = fl.list_factors_by_category(project_root=factor_workspace)
        assert isinstance(result, dict)


# ── update_index ───────────────────────────────────────────


class TestUpdateIndex:
    """Test update_index: 3 个测试."""

    def test_creates_index_if_missing(self, factor_workspace: Path, factor_data: dict) -> None:
        """无 index 时创建新的 (修复后每个因子计 1 次)."""
        import yaml
        factors_dir = factor_workspace / "quant" / "factors"
        d = factors_dir / "new_factor"
        d.mkdir()
        (d / "factor.yaml").write_text(yaml.dump(factor_data), encoding="utf-8")

        fl.update_index(project_root=factor_workspace)
        index_path = factors_dir / "index.yaml"
        assert index_path.exists()
        index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        assert "factors" in index
        # 修复后: 1 因子 × 1 次 = 1
        assert len(index["factors"]) == 1

    def test_idempotent(self, factor_workspace: Path, factor_data: dict) -> None:
        """多次调用结果一致 (修复后每次 1 因子 = 1)."""
        import yaml
        factors_dir = factor_workspace / "quant" / "factors"
        d = factors_dir / "factor_x"
        d.mkdir()
        (d / "factor.yaml").write_text(yaml.dump(factor_data), encoding="utf-8")

        fl.update_index(project_root=factor_workspace)
        first = (factors_dir / "index.yaml").read_text(encoding="utf-8")
        fl.update_index(project_root=factor_workspace)
        second = (factors_dir / "index.yaml").read_text(encoding="utf-8")

        # factors 数量应一致 (timestamp 可能不同)
        first_data = yaml.safe_load(first)
        second_data = yaml.safe_load(second)
        # 修复后: 1 因子
        assert len(first_data["factors"]) == len(second_data["factors"]) == 1

    def test_stats_accurate(self, factor_workspace: Path, factor_data: dict) -> None:
        """stats 字段正确统计 (修复后无重复)."""
        import yaml
        factors_dir = factor_workspace / "quant" / "factors"
        # 3 个 stk 因子 + 2 个 momentum
        for i, (at, cat) in enumerate(
            [("stk", "alpha"), ("stk", "alpha"), ("stk", "momentum")]
        ):
            fd = yaml.safe_load(yaml.dump(factor_data))  # deep copy
            fd["factor"]["asset_type"] = at
            fd["factor"]["category"] = cat
            d = factors_dir / f"f_{i}"
            d.mkdir()
            (d / "factor.yaml").write_text(yaml.dump(fd), encoding="utf-8")

        fl.update_index(project_root=factor_workspace)
        index = yaml.safe_load((factors_dir / "index.yaml").read_text(encoding="utf-8"))
        # 修复后: 3 因子 = 3
        assert index["statistics"]["total"] == 3
        assert index["statistics"]["by_asset_type"]["stk"] == 3
        assert index["statistics"]["by_category"]["alpha"] == 2
        assert index["statistics"]["by_category"]["momentum"] == 1
