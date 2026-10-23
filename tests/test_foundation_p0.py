"""Tests for foundation P0 + lint cache key (limit-independent core)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.foundation.extractors.text import _extract_text_file
from llmwikify.foundation.llm_client import clear_llm_client_memo
from llmwikify.kernel.graph.cache import cache_get, cache_put
from llmwikify.kernel.wiki.wiki import Wiki


@pytest.fixture
def wiki(tmp_path):
    w = Wiki(tmp_path)
    w.init(agent="generic")
    yield w
    try:
        w.close()
    except Exception:
        pass


class TestPromptRegistryCache:
    def test_same_instance_when_provider_stable(self, wiki):
        r1 = wiki._get_prompt_registry()
        r2 = wiki._get_prompt_registry()
        assert r1 is r2

    def test_new_instance_when_provider_changes(self, wiki):
        r1 = wiki._get_prompt_registry()
        cfg = dict(wiki.config)
        llm = dict(cfg.get("llm") or {})
        llm["provider"] = "other-provider"
        cfg["llm"] = llm
        wiki.config = cfg
        r2 = wiki._get_prompt_registry()
        assert r1 is not r2


class TestLLMClientMemo:
    def test_from_config_returns_same_object(self):
        from llmwikify.foundation.llm_client import LLMClient

        clear_llm_client_memo()
        cfg = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "model": "test-model",
                "api_key": "test-key-not-real",
                "base_url": "https://example.invalid",
            }
        }
        c1 = LLMClient.from_config(cfg)
        c2 = LLMClient.from_config(cfg)
        assert c1 is c2

    def test_clear_memo(self):
        from llmwikify.foundation.llm_client import LLMClient

        cfg = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "model": "test-model",
                "api_key": "test-key-not-real",
                "base_url": "https://example.invalid",
            }
        }
        c1 = LLMClient.from_config(cfg)
        clear_llm_client_memo()
        c2 = LLMClient.from_config(cfg)
        assert c1 is not c2


class TestTextExtractorUtf8:
    def test_reads_unicode(self, tmp_path):
        p = tmp_path / "t.md"
        p.write_text("# 标题 ↔ café\n", encoding="utf-8")
        out = _extract_text_file(p)
        assert "café" in out.text
        assert out.title == "标题 ↔ café"


class TestLintCoreCacheKey:
    def test_core_cache_shared_across_limit(self, wiki):
        """limit must not fragment core cache (gaps uses limit=20)."""
        from llmwikify.kernel.graph.cache import (
            cache_invalidate,
            combined_fingerprint,
            wiki_cache_key,
        )

        cache_invalidate()
        wkey = wiki_cache_key(wiki)
        fp = combined_fingerprint(
            getattr(getattr(wiki, "index", None), "conn", None),
            wiki.wiki_dir,
        )
        cache_put("lint", wkey, fp, {"core": True}, extra=str(wiki.config.get("mode", "check")))
        hit = cache_get("lint", wkey, fp, extra="check", ttl_s=600)
        assert hit == {"core": True}
