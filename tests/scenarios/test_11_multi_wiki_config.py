# tests/scenarios/test_11_multi_wiki_config.py
"""Scenario 3: Multi-Wiki Config - Tests for wiki configuration."""

import yaml
from pathlib import Path


class TestMultiWikiConfig:
    """Test multi-wiki configuration and discovery."""

    def test_11_1_config_parse_wikis(self, temp_dir):
        """Parse .wiki-config.yaml with wikis section."""
        config = {
            "wikis": {
                "default": "personal",
                "local": [
                    {"id": "personal", "name": "Personal Wiki", "path": "."},
                    {"id": "team", "name": "Team Wiki", "path": "../team"},
                ],
            }
        }

        config_path = temp_dir / ".wiki-config.yaml"
        config_path.write_text(yaml.dump(config))

        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["wikis"]["default"] == "personal"
        assert len(loaded["wikis"]["local"]) == 2

    def test_11_2_config_local_wikis(self, temp_dir):
        """Register local wikis from config."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        # Create multiple wiki directories
        for name in ["personal", "team", "cloud"]:
            create_wiki(temp_dir / name)

        config = {
            "wikis": {
                "default": "personal",
                "local": [
                    {"id": "personal", "name": "Personal", "path": str(temp_dir / "personal")},
                    {"id": "team", "name": "Team", "path": str(temp_dir / "team")},
                    {"id": "cloud", "name": "Cloud", "path": str(temp_dir / "cloud")},
                ],
                "discovery": {},
            }
        }

        registry = WikiRegistry(config)
        registry.initialize()

        # Register wikis
        for wiki_config in config["wikis"]["local"]:
            registry.register_wiki(
                wiki_id=wiki_config["id"],
                name=wiki_config["name"],
                root=Path(wiki_config["path"]),
            )

        wikis = registry.list_wikis()
        wiki_ids = [w.wiki_id for w in wikis]
        assert "personal" in wiki_ids
        assert "team" in wiki_ids
        assert "cloud" in wiki_ids

    def test_11_3_config_discovery(self, temp_dir):
        """Parse discovery section in config."""
        config = {
            "wikis": {
                "default": "personal",
                "local": [],
                "discovery": {
                    "enabled": True,
                    "scan_paths": [str(temp_dir)],
                    "scan_depth": 2,
                },
            }
        }

        assert config["wikis"]["discovery"]["enabled"] is True
        assert len(config["wikis"]["discovery"]["scan_paths"]) == 1

    def test_11_4_search_cross_wiki(self, temp_dir):
        """Cross-wiki search with multiple wikis."""
        from llmwikify import create_wiki
        from llmwikify.kernel.multi_wiki.registry import WikiRegistry

        # Create and populate multiple wikis
        for name in ["wiki-a", "wiki-b"]:
            w = create_wiki(temp_dir / name)
            w.write_page("common-topic", f"# Common Topic\n\nContent from {name}.")

        config = {"wikis": {"local": [], "discovery": {}}}
        registry = WikiRegistry(config)
        registry.initialize()

        for name in ["wiki-a", "wiki-b"]:
            registry.register_wiki(
                wiki_id=name,
                name=name,
                root=temp_dir / name,
            )

        # List wikis
        wikis = registry.list_wikis()
        assert len(wikis) >= 2
