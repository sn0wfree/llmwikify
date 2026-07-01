# tests/scenarios/test_07_yaml_templates.py
"""Scenario 7: YAML Config Templates - No LLM required."""

import pytest
import yaml
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "examples" / "07_yaml_templates" / "yaml_templates"


class TestYAMLTemplates:
    """Test YAML config template parsing."""

    def test_7_1_parse_personal_kb(self):
        """Parse personal-kb.yaml template."""
        template = TEMPLATES_DIR / "personal-kb.yaml"
        if not template.exists():
            pytest.skip("Template not found")

        data = yaml.safe_load(template.read_text())
        assert "llm" in data or "orphan_detection" in data

    def test_7_2_parse_project_docs(self):
        """Parse project-docs.yaml template."""
        template = TEMPLATES_DIR / "project-docs.yaml"
        if not template.exists():
            pytest.skip("Template not found")

        data = yaml.safe_load(template.read_text())
        assert data is not None

    def test_7_3_parse_research_wiki(self):
        """Parse research-wiki.yaml template."""
        template = TEMPLATES_DIR / "research-wiki.yaml"
        if not template.exists():
            pytest.skip("Template not found")

        data = yaml.safe_load(template.read_text())
        assert data is not None

    def test_7_4_parse_mining_news(self):
        """Parse mining-news-wiki.yaml template."""
        template = TEMPLATES_DIR / "mining-news-wiki.yaml"
        if not template.exists():
            pytest.skip("Template not found")

        data = yaml.safe_load(template.read_text())
        assert data is not None

    def test_7_5_custom_config(self, temp_dir):
        """Custom config loads correctly."""
        from llmwikify import create_wiki

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "orphan_detection": {"exclude_patterns": ["^draft-.*"]},
        }
        config_path = temp_dir / ".wiki-config.yaml"
        config_path.write_text(yaml.dump(config))

        wiki = create_wiki(temp_dir / "wiki", config=config)
        assert wiki is not None
