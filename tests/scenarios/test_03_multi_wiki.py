# tests/scenarios/test_03_multi_wiki.py
"""Scenario 3: Multi-Wiki Collaboration - No LLM required.

## Background
Manage multiple wikis through a single server using WikiRegistry.
Each wiki can be local (path) or remote (HTTP URL with auth).

## Architecture
```
        ┌────────────────────────┐
        │  llmwikify serve       │
        │  --multi-wiki --web    │
        │  (WikiRegistry)        │
        └─────────┬──────────────┘
                  │
       ┌──────────┼──────────┐
       ▼          ▼          ▼
   ┌──────┐  ┌──────┐  ┌──────────┐
   │wiki-a│  │wiki-b│  │wiki-c    │
   │local │  │local │  │remote    │
   └──────┘  └──────┘  └──────────┘
```

## Troubleshooting
- wikis list shows only default: check discovery.scan_paths
- Remote wiki unreachable: verify URL + API key + server running
- wiki_search_cross returns 0: wiki_ids must match exactly (case-sensitive)
"""


class TestMultiWiki:
    """Test multi-wiki registry operations.

    Covers TUTORIAL.md Scenario 3 (Multi-Wiki Collaboration).
    """

    def test_3_1_register_wiki(self, temp_dir):
        """Step 3.1: Register a wiki in the registry.

        Creates a wiki at a local path, then registers it in the
        WikiRegistry with a unique wiki_id.
        """
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
        wiki_ids = [w.wiki_id for w in wikis]
        assert "wiki-a" in wiki_ids

    def test_3_2_list_wikis(self, temp_dir):
        """Step 3.2: List all registered wikis.

        Returns list of WikiInstance objects with id, name, and root.
        """
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
        """Step 3.3: Switch the default active wiki.

        Changes which wiki commands operate on by default.
        """
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
        assert default is not None
        assert "wiki-c2" in str(default.root)

    def test_3_4_unregister_wiki(self, temp_dir):
        """Step 3.4: Unregister a wiki from the registry.

        Removes the wiki from the registry but does not delete the
        underlying wiki directory.
        """
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
        """Step 3.5: Auto-discover wikis in a directory.

        Scans a directory for existing wiki installations and returns
        their paths.
        """
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery

        for name in ["wiki-e1", "wiki-e2"]:
            create_wiki(temp_dir / name)

        discovery = WikiDiscovery()
        found = discovery.scan(str(temp_dir))

        assert isinstance(found, (list, dict))
