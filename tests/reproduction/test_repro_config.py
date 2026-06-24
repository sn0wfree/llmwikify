"""Tests for repro config: 三层优先级 (env > file > default)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llmwikify.reproduction.common import config as c


@pytest.fixture
def tmp_config_file(tmp_path: Path) -> Path:
    """创建临时 JSON 配置文件."""
    config_file = tmp_path / "llmwikify.json"
    config_file.write_text(
        json.dumps({
            "reproduction": {
                "clickhouse.host": "test-host",
                "clickhouse.port": 9999,
            }
        }),
        encoding="utf-8",
    )
    return config_file


class TestConfigDefaults:
    """Test 默认值 (4 测试)."""

    def test_get_default_when_no_file(self, tmp_path: Path) -> None:
        """无 config 文件时, 返回 DEFAULTS."""
        cfg = c.Config(config_path=tmp_path / "nonexistent.json")
        assert cfg.get("akshare.timeout_s") == 5.0  # DEFAULTS

    def test_get_with_explicit_default(self, tmp_path: Path) -> None:
        """get(key, default) 优先用 default 而非 DEFAULTS."""
        cfg = c.Config(config_path=tmp_path / "nonexistent.json")
        assert cfg.get("unknown.key", default="fallback") == "fallback"

    def test_get_returns_none_for_missing(self, tmp_path: Path) -> None:
        """get 不存在的 key (无 default) 返回 None."""
        cfg = c.Config(config_path=tmp_path / "nonexistent.json")
        assert cfg.get("unknown.key") is None

    def test_singleton_config_exists(self) -> None:
        """模块级 config 单例存在."""
        assert hasattr(c, "config")
        assert isinstance(c.config, c.Config)


class TestConfigFileLoad:
    """Test 配置文件加载 (3 测试)."""

    def test_loads_from_file(self, tmp_config_file: Path) -> None:
        """从 JSON 文件加载."""
        cfg = c.Config(config_path=tmp_config_file)
        assert cfg.get("clickhouse.host") == "test-host"
        assert cfg.get("clickhouse.port") == 9999

    def test_file_overrides_default(self, tmp_config_file: Path) -> None:
        """文件值覆盖 DEFAULTS."""
        cfg = c.Config(config_path=tmp_config_file)
        # DEFAULTS 中 port=8123, 文件中是 9999
        assert cfg.get("clickhouse.port") == 9999

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        """无效 JSON 不抛错, 返回空配置."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(":\n  - [unclosed", encoding="utf-8")
        cfg = c.Config(config_path=bad_file)
        # 仍然能返回 DEFAULTS
        assert cfg.get("akshare.timeout_s") == 5.0


class TestConfigEnvOverride:
    """Test 环境变量覆盖 (3 测试)."""

    def test_env_overrides_file(self, tmp_config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """env var 优先级最高."""
        monkeypatch.setenv("CLICKHOUSE_HOST", "env-host")
        cfg = c.Config(config_path=tmp_config_file)
        # env 优先于 file
        assert cfg.get("clickhouse.host") == "env-host"

    def test_env_int_parsed(self, tmp_config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """env var int 值被解析."""
        monkeypatch.setenv("CLICKHOUSE_PORT", "12345")
        cfg = c.Config(config_path=tmp_config_file)
        assert cfg.get("clickhouse.port") == 12345
        assert isinstance(cfg.get("clickhouse.port"), int)

    def test_env_float_parsed(self, tmp_config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """env var float 值被解析."""
        monkeypatch.setenv("LLMWIKIFY_AKSHARE_TIMEOUT", "10.5")
        cfg = c.Config(config_path=tmp_config_file)
        assert cfg.get("akshare.timeout_s") == 10.5
        assert isinstance(cfg.get("akshare.timeout_s"), float)


class TestConfigConstants:
    """Test 模块级常量 (2 测试)."""

    def test_defaults_dict_non_empty(self) -> None:
        """DEFAULTS 字典非空."""
        assert len(c.DEFAULTS) > 10
        assert "db.path" in c.DEFAULTS
        assert "clickhouse.host" in c.DEFAULTS

    def test_env_map_keys_match_defaults(self) -> None:
        """ENV_MAP keys 是 DEFAULTS 的子集."""
        env_keys = set(c.ENV_MAP.keys())
        default_keys = set(c.DEFAULTS.keys())
        assert env_keys.issubset(default_keys), (
            f"ENV_MAP has keys not in DEFAULTS: {env_keys - default_keys}"
        )
