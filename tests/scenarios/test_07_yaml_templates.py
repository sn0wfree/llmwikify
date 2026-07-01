# tests/scenarios/test_07_yaml_templates.py
"""Scenario 7: YAML Config Templates - Feature playbook.

## Background
4 ready-to-use `.wiki-config.yaml` templates: personal notes (offline),
project docs, academic research (long timeout), industry news
(date archiving). Demonstrates copy + customize + load workflow.

## Templates
- personal-kb.yaml: offline personal notes (no LLM)
- project-docs.yaml: team project documentation
- research-wiki.yaml: academic with long LLM timeout
- mining-news-wiki.yaml: industry news with date archiving

## Troubleshooting
- Template not found: check examples/07_yaml_templates/yaml_templates/
- Config ignored: verify file is at wiki root as .wiki-config.yaml
"""


import pytest
from pathlib import Path


class TestYAMLTemplates:
    """Test YAML config templates (feature playbook 07).

    Covers examples/07_yaml_templates/.
    """

    def test_7_1_parse_personal_kb(self):
        """Step 7.1: Parse personal-kb.yaml template.

        Offline personal notes configuration. No LLM required.
        """
        import yaml

        template_path = (
            Path(__file__).parent.parent.parent
            / "examples" / "07_yaml_templates" / "yaml_templates" / "personal-kb.yaml"
        )
        if not template_path.exists():
            pytest.skip("Template file not found")

        template = yaml.safe_load(template_path.read_text())
        assert template is not None
        assert "llm" in template or "wiki" in template

    def test_7_2_parse_project_docs(self):
        """Step 7.2: Parse project-docs.yaml template.

        Team project documentation with shared wikis.
        """
        import yaml

        template_path = (
            Path(__file__).parent.parent.parent
            / "examples" / "07_yaml_templates" / "yaml_templates" / "project-docs.yaml"
        )
        if not template_path.exists():
            pytest.skip("Template file not found")

        template = yaml.safe_load(template_path.read_text())
        assert template is not None

    def test_7_3_parse_research_wiki(self):
        """Step 7.3: Parse research-wiki.yaml template.

        Academic research with long LLM timeout for deep analysis.
        """
        import yaml

        template_path = (
            Path(__file__).parent.parent.parent
            / "examples" / "07_yaml_templates" / "yaml_templates" / "research-wiki.yaml"
        )
        if not template_path.exists():
            pytest.skip("Template file not found")

        template = yaml.safe_load(template_path.read_text())
        assert template is not None

    def test_7_4_parse_mining_news(self):
        """Step 7.4: Parse mining-news-wiki.yaml template.

        Industry news with date-based archiving.
        """
        import yaml

        template_path = (
            Path(__file__).parent.parent.parent
            / "examples" / "07_yaml_templates" / "yaml_templates" / "mining-news-wiki.yaml"
        )
        if not template_path.exists():
            pytest.skip("Template file not found")

        template = yaml.safe_load(template_path.read_text())
        assert template is not None

    def test_7_5_custom_config(self, temp_dir):
        """Step 7.5: Create wiki with custom config.

        Demonstrates create_wiki(path, config={...}) for programmatic
        configuration without YAML files.
        """
        from llmwikify import create_wiki

        config = {
            "llm": {"provider": "test", "model": "test-model"},
            "orphan_detection": {"exclude_patterns": ["^draft-.*"]},
        }
        wiki = create_wiki(temp_dir / "custom-wiki", config=config)
        assert wiki is not None
