"""Integration: 行为等价性测试 (S3 阶段).

为 20 阶段 refactor 提供安全网 — 旧实现 vs 新实现的输出对比.
当前所有 reproduction/ 模块都是"旧实现", 行为等价性测试在 refactor 期间使用.

详见: docs/designs/pipeline_framework.md Section 29.9
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from llmwikify.reproduction import factor_library as fl


class TestFactorLibraryFormatEquivalence:
    """Test 新/旧 YAML 格式行为等价 (4 测试)."""

    def test_read_old_yaml(self, tmp_path: Path) -> None:
        """旧格式 factors/{name}.yaml 可读."""
        import yaml
        old_yaml = tmp_path / "quant" / "factors" / "test.yaml"
        old_yaml.parent.mkdir(parents=True)
        old_yaml.write_text(yaml.dump({"factor": {"name": "test"}}), encoding="utf-8")

        result = fl.read_factor_yaml("test", project_root=tmp_path)
        assert result["factor"]["name"] == "test"

    def test_read_new_dir_format(self, tmp_path: Path) -> None:
        """新格式 factors/{name}/factor.yaml 可读."""
        import yaml
        d = tmp_path / "quant" / "factors" / "test_dir"
        d.mkdir(parents=True)
        (d / "factor.yaml").write_text(yaml.dump({"factor": {"name": "test"}}), encoding="utf-8")

        result = fl.read_factor_yaml("test_dir", project_root=tmp_path)
        assert result["factor"]["name"] == "test"

    def test_write_creates_correct_format(self, tmp_path: Path) -> None:
        """write 在不同场景下创建不同格式."""
        # 场景 1: name 是单个文件路径 (旧格式)
        result1 = fl.write_factor_yaml(
            "old_style", {"factor": {"name": "x"}}, project_root=tmp_path
        )
        assert (tmp_path / "quant" / "factors" / "old_style.yaml").exists()

        # 场景 2: name 是目录路径 (新格式, 目录预先存在)
        d = tmp_path / "quant" / "factors" / "new_style_dir"
        d.mkdir()
        result2 = fl.write_factor_yaml(
            "new_style_dir", {"factor": {"name": "y"}}, project_root=tmp_path
        )
        assert (d / "factor.yaml").exists()

    def test_list_consistent(self, tmp_path: Path) -> None:
        """list_factors 返回 list (无论格式)."""
        import yaml
        # 先写一个因子, 让 update_index 创建 index.yaml
        d = tmp_path / "quant" / "factors" / "test_factor"
        d.mkdir(parents=True)
        (d / "factor.yaml").write_text(yaml.dump({"factor": {"name": "f1"}}), encoding="utf-8")
        fl.update_index(project_root=tmp_path)

        result = fl.list_factors(project_root=tmp_path)
        assert isinstance(result, list)
        assert len(result) == 1


class TestConfigPrecedence:
    """Test 配置三层优先级 (3 测试)."""

    def test_default_when_no_source(self, tmp_path: Path) -> None:
        """无任何 source 时返回 DEFAULTS."""
        from llmwikify.reproduction.common import config as c
        cfg = c.Config(config_path=tmp_path / "nonexistent.json")
        assert cfg.get("akshare.timeout_s") == 5.0  # DEFAULTS

    def test_file_overrides_default(self, tmp_path: Path) -> None:
        """文件覆盖 DEFAULTS."""
        from llmwikify.reproduction.common import config as c
        import json
        config_file = tmp_path / "cfg.json"
        config_file.write_text(
            json.dumps({"reproduction": {"akshare.timeout_s": 99.9}}),
            encoding="utf-8",
        )
        cfg = c.Config(config_path=config_file)
        assert cfg.get("akshare.timeout_s") == 99.9

    def test_env_overrides_file(self, tmp_path: Path, monkeypatch) -> None:
        """env 覆盖 file."""
        from llmwikify.reproduction.common import config as c
        import json
        config_file = tmp_path / "cfg.json"
        config_file.write_text(
            json.dumps({"reproduction": {"akshare.timeout_s": 99.9}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("LLMWIKIFY_AKSHARE_TIMEOUT", "50.0")
        cfg = c.Config(config_path=config_file)
        assert cfg.get("akshare.timeout_s") == 50.0


class TestModuleAPIBackwardCompat:
    """Test 公共 API 兼容性 (3 测试)."""

    def test_factor_library_public_api(self) -> None:
        """factor_library 公共 API 存在."""
        for fn in ["read_factor_yaml", "write_factor_yaml", "list_factors",
                   "list_factors_by_category", "update_index"]:
            assert hasattr(fl, fn), f"Missing: {fn}"

    def test_sessions_public_api(self) -> None:
        """sessions 公共 API 存在."""
        from llmwikify.reproduction import sessions
        for name in ["ReproductionDatabase", "Session", "Artifact", "Result"]:
            assert hasattr(sessions, name)

    def test_codegen_utils_public_api(self) -> None:
        """codegen_utils 公共 API 存在."""
        from llmwikify.reproduction.codegen import llm_code as codegen_utils
        for fn in ["generate_factor_code", "extract_python", "validate_syntax",
                   "validate_safety", "execute_code", "build_llm_client"]:
            assert hasattr(codegen_utils, fn), f"Missing: {fn}"
