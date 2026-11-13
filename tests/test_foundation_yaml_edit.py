"""Tests for foundation.yaml_edit — minimal-diff YAML editing (D3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from llmwikify.foundation.yaml_edit import (
    YamlEditError,
    delete_in_yaml,
    set_in_yaml,
    write_text_atomic,
)


class TestSetScalar:
    def test_update_preserves_comment_and_other_lines(self) -> None:
        text = (
            "# user header\n"
            "llm:\n"
            "  provider: openai  # keep me\n"
            "  timeout: 120  # seconds\n"
            "search:\n"
            "  backend: simple\n"
        )
        out = set_in_yaml(text, "llm.timeout", 30)
        assert "timeout: 30  # seconds" in out
        assert "# user header" in out
        assert "provider: openai  # keep me" in out
        assert "backend: simple" in out
        # Only the target value changed.
        assert out.replace("timeout: 30", "timeout: 120") == text

    def test_nested_key(self) -> None:
        text = "search:\n  qmd:\n    port: 8181\n    host: 127.0.0.1\n"
        out = set_in_yaml(text, "search.qmd.port", 9999)
        assert "port: 9999" in out
        assert "host: 127.0.0.1" in out
        assert yaml.safe_load(out)["search"]["qmd"]["port"] == 9999

    def test_insert_missing_key_into_existing_parent(self) -> None:
        text = "llm:\n  provider: openai\n"
        out = set_in_yaml(text, "llm.timeout", 42)
        data = yaml.safe_load(out)
        assert data["llm"]["provider"] == "openai"
        assert data["llm"]["timeout"] == 42

    def test_insert_missing_parent_chain(self) -> None:
        text = "version: '0.41'\n"
        out = set_in_yaml(text, "orphan_detection.exclude_frontmatter", ["draft"])
        data = yaml.safe_load(out)
        assert data["orphan_detection"]["exclude_frontmatter"] == ["draft"]
        assert data["version"] == "0.41"

    def test_bool_and_none(self) -> None:
        text = "reference_index:\n  auto_export: false\n"
        out = set_in_yaml(text, "reference_index.auto_export", True)
        assert yaml.safe_load(out)["reference_index"]["auto_export"] is True
        out2 = set_in_yaml(text, "reference_index.auto_export", None)
        assert yaml.safe_load(out2)["reference_index"]["auto_export"] is None

    def test_bootstrap_empty_document(self) -> None:
        out = set_in_yaml("", "llm.timeout", 7)
        assert yaml.safe_load(out) == {"llm": {"timeout": 7}}


class TestBlockReplace:
    def test_dict_value_replaces_block_keeps_siblings(self) -> None:
        text = (
            "# top\n"
            "llm:\n"
            "  provider: openai\n"
            "  extra: keep\n"
            "other:\n"
            "  x: 1\n"
        )
        out = set_in_yaml(text, "llm", {"provider": "anthropic", "api_key": "k"})
        data = yaml.safe_load(out)
        assert data["llm"] == {"provider": "anthropic", "api_key": "k"}
        assert data["other"] == {"x": 1}
        assert "# top" in out

    def test_list_value(self) -> None:
        text = "orphan_detection:\n  exclude_patterns: ['old']\n"
        # Existing flow list on same line — treated as scalar-ish parent walk
        # for leaf under orphan_detection.
        out = set_in_yaml(text, "orphan_detection.exclude_patterns", ["a", "b"])
        data = yaml.safe_load(out)
        assert data["orphan_detection"]["exclude_patterns"] == ["a", "b"]


class TestDelete:
    def test_delete_leaf_preserves_rest(self) -> None:
        text = "llm:\n  provider: openai  # c\n  timeout: 120\nsearch:\n  backend: s\n"
        out = delete_in_yaml(text, "llm.timeout")
        assert "timeout" not in out
        assert "provider: openai  # c" in out
        assert "backend: s" in out

    def test_delete_missing_is_noop(self) -> None:
        text = "a:\n  b: 1\n"
        assert delete_in_yaml(text, "a.zzz") == text

    def test_delete_block_children(self) -> None:
        text = "search:\n  qmd:\n    port: 1\n    host: h\n  other: 2\n"
        out = delete_in_yaml(text, "search.qmd")
        data = yaml.safe_load(out)
        assert data["search"] == {"other": 2}


class TestUnsupported:
    def test_anchor_rejected(self) -> None:
        text = "base: &x\n  a: 1\n"
        with pytest.raises(YamlEditError, match="anchor"):
            set_in_yaml(text, "base.a", 2)

    def test_alias_rejected(self) -> None:
        text = "a: &x 1\nb: *x\n"
        with pytest.raises(YamlEditError, match="anchor"):
            set_in_yaml(text, "b", 2)

    def test_multi_doc_rejected(self) -> None:
        text = "---\na: 1\n"
        with pytest.raises(YamlEditError, match="multi-document"):
            set_in_yaml(text, "a", 2)

    def test_missing_parent_on_delete(self) -> None:
        text = "llm:\n  provider: x\n"
        with pytest.raises(YamlEditError, match="parent"):
            delete_in_yaml(text, "nope.child")

    def test_set_creates_missing_parent(self) -> None:
        text = "version: '0.41'\n"
        out = set_in_yaml(text, "nope.child", 1)
        assert yaml.safe_load(out) == {
            "version": "0.41",
            "nope": {"child": 1},
        }

    def test_inline_parent_rejected(self) -> None:
        text = "llm: {provider: x}\n"
        with pytest.raises(YamlEditError, match="inline"):
            set_in_yaml(text, "llm.provider", "y")


class TestAtomicWrite:
    def test_write_and_overwrite(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / ".wiki-config.yaml"
        write_text_atomic(path, "a: 1\n")
        assert path.read_text(encoding="utf-8") == "a: 1\n"
        write_text_atomic(path, "a: 2\n")
        assert path.read_text(encoding="utf-8") == "a: 2\n"
        assert list(tmp_path.glob("*.tmp")) == []
        assert list((tmp_path / "sub").glob("*.tmp")) == []


class TestConfigSaveWiki:
    def test_save_wiki_config_minimal_diff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llmwikify.foundation.config import Config

        wiki = tmp_path / "wiki"
        wiki.mkdir()
        cfg_path = wiki / ".wiki-config.yaml"
        cfg_path.write_text(
            "# my notes\nversion: '0.41'\nllm:\n  provider: openai\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path / "home"))
        Config._instance = None
        c = Config()
        c.save_wiki_config(wiki, {"llm": {"timeout": 99}})
        text = cfg_path.read_text(encoding="utf-8")
        assert "# my notes" in text
        data = yaml.safe_load(text)
        assert data["llm"]["provider"] == "openai"
        assert data["llm"]["timeout"] == 99

    def test_save_wiki_config_delete_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llmwikify.foundation.config import Config

        wiki = tmp_path / "wiki2"
        wiki.mkdir()
        cfg_path = wiki / ".wiki-config.yaml"
        cfg_path.write_text("llm:\n  provider: openai\n  gone: 1\n", encoding="utf-8")
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path / "home2"))
        Config._instance = None
        c = Config()
        c.save_wiki_config(wiki, {}, delete_keys=["llm.gone"])
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert data["llm"] == {"provider": "openai"}


class TestConfigSaveJson:
    def test_section_deep_merge_preserves_unknown_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from llmwikify.foundation.config import Config

        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        c.save({"provider": "openai", "api_key": "secret"}, section="llm")
        c.save({"provider": "anthropic"}, section="llm")
        data = json.loads(c.path.read_text(encoding="utf-8"))
        assert data["llm"]["provider"] == "anthropic"
        assert data["llm"]["api_key"] == "secret"

    def test_save_atomic_no_tmp_left(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from llmwikify.foundation.config import Config

        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        c.save({"a": 1})
        leftovers = list((tmp_path / ".llmwikify").glob("*.tmp"))
        assert leftovers == []
