"""Tests for foundation.io — file I/O utilities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.foundation.io import read_json, read_yaml, safe_read_text, safe_write_text, write_json


class TestReadJson:
    """Tests for read_json() function."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Returns default when file doesn't exist."""
        result = read_json(tmp_path / "missing.json")
        assert result is None

    def test_missing_file_custom_default(self, tmp_path: Path) -> None:
        """Returns custom default when file doesn't exist."""
        result = read_json(tmp_path / "missing.json", default={})
        assert result == {}

    def test_valid_json(self, tmp_path: Path) -> None:
        """Reads valid JSON file."""
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"key": "value"}))
        result = read_json(path)
        assert result == {"key": "value"}

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Returns default on invalid JSON."""
        path = tmp_path / "test.json"
        path.write_text("not valid json{{{")
        result = read_json(path, default={})
        assert result == {}

    def test_empty_file(self, tmp_path: Path) -> None:
        """Returns default on empty file."""
        path = tmp_path / "test.json"
        path.write_text("")
        result = read_json(path, default={})
        assert result == {}


class TestWriteJson:
    """Tests for write_json() function."""

    def test_creates_file(self, tmp_path: Path) -> None:
        """Creates file with JSON content."""
        path = tmp_path / "test.json"
        write_json(path, {"key": "value"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"key": "value"}

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Creates parent directories."""
        path = tmp_path / "sub" / "dir" / "test.json"
        write_json(path, {"key": "value"})
        assert path.exists()

    def test_indent(self, tmp_path: Path) -> None:
        """Respects indent parameter."""
        path = tmp_path / "test.json"
        write_json(path, {"key": "value"}, indent=4)
        content = path.read_text()
        assert "    " in content


class TestReadYaml:
    """Tests for read_yaml() function."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Returns default when file doesn't exist."""
        result = read_yaml(tmp_path / "missing.yaml")
        assert result is None

    def test_missing_file_custom_default(self, tmp_path: Path) -> None:
        """Returns custom default when file doesn't exist."""
        result = read_yaml(tmp_path / "missing.yaml", default={})
        assert result == {}

    def test_valid_yaml(self, tmp_path: Path) -> None:
        """Reads valid YAML file."""
        path = tmp_path / "test.yaml"
        path.write_text("key: value\nlist:\n  - item1\n  - item2\n")
        result = read_yaml(path)
        assert result["key"] == "value"
        assert result["list"] == ["item1", "item2"]

    def test_empty_yaml(self, tmp_path: Path) -> None:
        """Returns default on empty YAML."""
        path = tmp_path / "test.yaml"
        path.write_text("")
        result = read_yaml(path, default={})
        assert result == {}

    def test_yaml_with_nested_dict(self, tmp_path: Path) -> None:
        """Reads nested YAML dict."""
        path = tmp_path / "test.yaml"
        path.write_text("a:\n  b:\n    c: 1\n")
        result = read_yaml(path)
        assert result == {"a": {"b": {"c": 1}}}

    def test_yaml_import_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns default when yaml module not available."""
        path = tmp_path / "test.yaml"
        path.write_text("key: value")

        # Mock yaml import to fail
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("No module named 'yaml'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = read_yaml(path, default={})
        assert result == {}


class TestSafeReadText:
    """Tests for safe_read_text() function."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Returns default when file doesn't exist."""
        result = safe_read_text(tmp_path / "missing.txt")
        assert result == ""

    def test_missing_file_custom_default(self, tmp_path: Path) -> None:
        """Returns custom default when file doesn't exist."""
        result = safe_read_text(tmp_path / "missing.txt", default="N/A")
        assert result == "N/A"

    def test_valid_file(self, tmp_path: Path) -> None:
        """Reads file content."""
        path = tmp_path / "test.txt"
        path.write_text("hello world")
        result = safe_read_text(path)
        assert result == "hello world"


class TestSafeWriteText:
    """Tests for safe_write_text() function."""

    def test_creates_file(self, tmp_path: Path) -> None:
        """Creates file with content."""
        path = tmp_path / "test.txt"
        safe_write_text(path, "hello world")
        assert path.exists()
        assert path.read_text() == "hello world"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Creates parent directories."""
        path = tmp_path / "sub" / "dir" / "test.txt"
        safe_write_text(path, "hello world")
        assert path.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        """Overwrites existing file."""
        path = tmp_path / "test.txt"
        path.write_text("old content")
        safe_write_text(path, "new content")
        assert path.read_text() == "new content"
