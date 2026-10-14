"""Regression tests for SSRF config loading (Bug 1b, 2026-10-14).

`_load_ssrf_config` used to import a non-existent `get_config` from
`foundation.config`; the resulting ImportError was silently swallowed, so
the `ssrf_protection` section of ~/.llmwikify/llmwikify.json was never
applied and `is_safe_url` allowed every URL. These tests pin the fixed
behavior end-to-end (file → Config → is_safe_url).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.foundation import config as config_module
from llmwikify.foundation.config import Config
from llmwikify.foundation.utils import _load_ssrf_config, is_safe_url


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bind Config (module singleton) to a per-test LLMWIKIFY_HOME."""
    monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
    Config._instance = None
    monkeypatch.setattr(config_module, "config", Config())
    yield
    Config._instance = None


def _write_config(tmp_path: Path, ssrf: dict) -> None:
    home = tmp_path / ".llmwikify"
    home.mkdir(exist_ok=True)
    (home / "llmwikify.json").write_text(
        json.dumps({"ssrf_protection": ssrf}), encoding="utf-8",
    )


class TestSsrfConfigLoading:
    """Regression: the config file must actually reach _load_ssrf_config."""

    def test_config_file_is_read(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {
            "enabled": True,
            "blocked_networks": ["10.0.0.0/8"],
            "blocked_hostnames": ["localhost"],
        })
        cfg = _load_ssrf_config()
        assert cfg["enabled"] is True
        assert cfg["blocked_networks"] == ["10.0.0.0/8"]
        assert cfg["blocked_hostnames"] == ["localhost"]

    def test_missing_config_keeps_backward_compatible_default(self) -> None:
        cfg = _load_ssrf_config()
        assert cfg["enabled"] is False
        assert cfg["blocked_networks"] == []
        assert cfg["blocked_hostnames"] == []


class TestIsSafeUrlWithEnabledConfig:
    def test_allows_when_disabled(self) -> None:
        assert is_safe_url("http://127.0.0.1/") is True

    def test_blocks_private_ip_literals(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {
            "enabled": True,
            "blocked_networks": ["127.0.0.0/8", "10.0.0.0/8", "169.254.0.0/16"],
        })
        assert is_safe_url("http://127.0.0.1/") is False
        assert is_safe_url("http://10.1.2.3/service") is False
        assert is_safe_url("http://169.254.169.254/latest/meta-data/") is False
        assert is_safe_url("https://example.com/") is True

    def test_blocks_configured_hostnames(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {
            "enabled": True,
            "blocked_hostnames": ["metadata.google.internal", "localhost"],
        })
        assert is_safe_url("http://metadata.google.internal/") is False
        assert is_safe_url("http://LOCALHOST/") is False
        assert is_safe_url("https://example.com/") is True

    def test_rejects_non_http_schemes_when_enabled(self, tmp_path: Path) -> None:
        _write_config(tmp_path, {"enabled": True})
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("ftp://example.com/") is False
