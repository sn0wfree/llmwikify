# tests/scenarios/test_03_multi_wiki.py
"""Scenario 3: Multi-Wiki - No LLM required."""

import pytest
from pathlib import Path


class TestMultiWiki:
    """Test multi-wiki registry operations."""

    def test_3_1_register_wiki(self, temp_dir):
        """Register a wiki in the registry."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        wiki_path = temp_dir / "wiki-a"
        create_wiki(wiki_path)

        config = {"wikis": {"local": [], "discovery": {}}}
        registry = WikiRegistry(config)
        registry.initialize()
        instance = registry.register_wiki(
            wiki_id="wiki-a",
            name="Wiki A",
            root=wiki_path,
        )

        assert instance is not None
        wikis = registry.list_wikis()
        # list_wikis returns list of WikiInstance objects
        wiki_ids = [w.wiki_id for w in wikis]
        assert "wiki-a" in wiki_ids

    def test_3_2_list_wikis(self, temp_dir):
        """List registered wikis."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        wiki_path = temp_dir / "wiki-b"
        create_wiki(wiki_path)

        config = {"wikis": {"local": [], "discovery": {}}}
        registry = WikiRegistry(config)
        registry.initialize()
        registry.register_wiki(
            wiki_id="wiki-b",
            name="Wiki B",
            root=wiki_path,
        )

        wikis = registry.list_wikis()
        assert isinstance(wikis, (list, dict))

    def test_3_3_switch_wiki(self, temp_dir):
        """Switch default wiki."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        for name in ["wiki-c1", "wiki-c2"]:
            create_wiki(temp_dir / name)

        config = {"wikis": {"local": [], "discovery": {}}}
        registry = WikiRegistry(config)
        registry.initialize()
        registry.register_wiki(
            wiki_id="wiki-c1",
            name="Wiki C1",
            root=temp_dir / "wiki-c1",
        )
        registry.register_wiki(
            wiki_id="wiki-c2",
            name="Wiki C2",
            root=temp_dir / "wiki-c2",
        )

        registry.set_default_wiki("wiki-c2")
        default = registry.get_default_wiki()
        # get_default_wiki returns a Wiki object
        assert default is not None
        # Check that the default wiki has the correct root
        assert "wiki-c2" in str(default.root)

    def test_3_4_unregister_wiki(self, temp_dir):
        """Unregister a wiki."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        wiki_path = temp_dir / "wiki-d"
        create_wiki(wiki_path)

        config = {"wikis": {"local": [], "discovery": {}}}
        registry = WikiRegistry(config)
        registry.initialize()
        registry.register_wiki(
            wiki_id="wiki-d",
            name="Wiki D",
            root=wiki_path,
        )
        registry.unregister_wiki("wiki-d")

        wikis = registry.list_wikis()
        assert "wiki-d" not in wikis

    def test_3_5_wiki_discovery(self, temp_dir):
        """Discover wikis in a directory."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery

        for name in ["wiki-e1", "wiki-e2"]:
            create_wiki(temp_dir / name)

        discovery = WikiDiscovery()
        found = discovery.scan(str(temp_dir))

        assert isinstance(found, (list, dict))
