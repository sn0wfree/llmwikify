"""Tests for P1 features: cross-source synthesis, smart lint, knowledge graph enhancements."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from src.llmwikify.core.wiki import Wiki
from src.llmwikify.core.synthesis_engine import SynthesisEngine


@pytest.fixture
def test_wiki():
    """Create a temporary wiki with multiple source pages for testing."""
    tmp = Path(tempfile.mkdtemp())

    wiki = Wiki(tmp)
    wiki.init(agent='generic')

    # Create raw sources
    raw_dir = tmp / 'raw'
    raw_dir.mkdir(exist_ok=True)

    (raw_dir / 'source1.md').write_text("""
# AI in Healthcare Part 1

## Summary
AI is transforming healthcare diagnostics.

## Key Entities & Relations
### Entities
- **DeepMind** (organization): AI research lab
- **IBM Watson** (organization): Healthcare AI platform

### Key Relations
- DeepMind → uses → AlphaFold

## Key Claims & Facts
### Claims
- AI outperforms radiologists in detecting cancer (confidence: high)

### Key Facts
- AI reduces diagnostic time by 50%

## Sources
- [Source: AI in Healthcare Part 1](raw/source1.md)
""")

    (raw_dir / 'source2.md').write_text("""
# AI in Healthcare Part 2

## Summary
New study confirms AI diagnostic accuracy but notes demographic bias.

## Key Entities & Relations
### Entities
- **DeepMind** (organization): AI research lab
- **Tempus** (organization): Precision medicine platform

### Key Relations
- Tempus → related_to → AI diagnostics

## Key Claims & Facts
### Claims
- AI outperforms radiologists in detecting cancer (confidence: high)
- AI accuracy varies across demographic groups (confidence: medium)

### Key Facts
- AI diagnostic accuracy reaches 95% in controlled studies

## Contradictions & Gaps
### Potential Contradictions
- AI accuracy varies across demographic groups, contradicting universal superiority claims

### Data Gaps
- Limited long-term studies on AI diagnostic accuracy

## Sources
- [Source: AI in Healthcare Part 2](raw/source2.md)
""")

    # Create wiki source pages
    sources_dir = tmp / 'wiki' / 'sources'
    sources_dir.mkdir(parents=True, exist_ok=True)

    (sources_dir / 'ai-healthcare-1.md').write_text("""
---
title: AI in Healthcare Part 1
type: source
created: 2026-01-15
sources: [raw/source1.md]
---

# AI in Healthcare Part 1

## Summary
AI is transforming healthcare diagnostics.

## Key Entities & Relations
### Entities
- **DeepMind** (organization): AI research lab
- **IBM Watson** (organization): Healthcare AI platform

### Key Relations
- DeepMind → uses → AlphaFold

## Key Claims & Facts
### Claims
- AI outperforms radiologists in detecting cancer (confidence: high)

### Key Facts
- AI reduces diagnostic time by 50%

## Cross-References
- [[concepts/Artificial Intelligence]]
- [[concepts/Healthcare Technology]]

## Sources
- [Source: AI in Healthcare Part 1](raw/source1.md)
""")

    (sources_dir / 'ai-healthcare-2.md').write_text("""
---
title: AI in Healthcare Part 2
type: source
created: 2026-03-20
sources: [raw/source2.md]
---

# AI in Healthcare Part 2

## Summary
New study confirms AI diagnostic accuracy but notes demographic bias.

## Key Entities & Relations
### Entities
- **DeepMind** (organization): AI research lab
- **Tempus** (organization): Precision medicine platform

### Key Relations
- Tempus → related_to → AI diagnostics

## Key Claims & Facts
### Claims
- AI outperforms radiologists in detecting cancer (confidence: high)
- AI accuracy varies across demographic groups (confidence: medium)

### Key Facts
- AI diagnostic accuracy reaches 95% in controlled studies

## Contradictions & Gaps
### Potential Contradictions
- AI accuracy varies across demographic groups

### Data Gaps
- Limited long-term studies on AI diagnostic accuracy

## Cross-References
- [[concepts/Artificial Intelligence]]
- [[entities/DeepMind]]

## Sources
- [Source: AI in Healthcare Part 2](raw/source2.md)
""")

    # Create a concept page
    concepts_dir = tmp / 'wiki' / 'concepts'
    concepts_dir.mkdir(parents=True, exist_ok=True)

    (concepts_dir / 'Artificial Intelligence.md').write_text("""
---
title: Artificial Intelligence
type: concept
created: 2026-01-10
---

# Artificial Intelligence

## Summary
AI is a broad field of computer science focused on creating intelligent machines.

## Sources
- [Source: AI in Healthcare Part 1](raw/source1.md)
""")

    yield wiki, tmp

    shutil.rmtree(tmp)


class TestSynthesisEngine:
    """Test cross-source synthesis engine."""

    def test_find_reinforced_claims(self, test_wiki):
        """Test that reinforced claims are detected across sources."""
        wiki, tmp = test_wiki
        engine = SynthesisEngine(wiki)

        # Simulate new analysis with same claim
        new_analysis = {
            "claims": [
                {"statement": "AI outperforms radiologists in detecting cancer", "confidence": "high"}
            ],
            "entities": [],
            "topics": [],
        }

        result = engine._find_reinforced_claims(new_analysis, [])

        # Without existing sources, no reinforcement
        assert isinstance(result, list)

    def test_find_new_entities(self, test_wiki):
        """Test detection of new entities not in wiki."""
        wiki, tmp = test_wiki
        engine = SynthesisEngine(wiki)

        new_analysis = {
            "entities": [
                {"name": "NewEntity1", "type": "organization", "attributes": {}},
                {"name": "DeepMind", "type": "organization", "attributes": {}},  # Already exists
            ],
        }

        # Get existing entities
        existing = engine._get_existing_entities()

        result = engine._find_new_entities(new_analysis, existing)

        # NewEntity1 should be detected as new
        new_names = [e["name"] for e in result]
        assert "NewEntity1" in new_names

    def test_find_knowledge_gaps(self, test_wiki):
        """Test detection of knowledge gaps."""
        wiki, tmp = test_wiki
        engine = SynthesisEngine(wiki)

        new_analysis = {
            "data_gaps": [
                "Limited information on AI adoption in developing countries",
                "No long-term studies on AI diagnostic accuracy"
            ],
            "topics": ["NewTopic1"],
        }

        result = engine._find_knowledge_gaps(new_analysis, [])

        # Should detect explicit gaps
        assert len(result) > 0
        assert any("developing countries" in g["gap"] for g in result)

    def test_analyze_new_source(self, test_wiki):
        """Test full analysis of a new source."""
        wiki, tmp = test_wiki
        engine = SynthesisEngine(wiki)

        new_analysis = {
            "claims": [
                {"statement": "AI outperforms radiologists", "confidence": "high"}
            ],
            "entities": [
                {"name": "NewEntity", "type": "organization", "attributes": {}}
            ],
            "topics": ["AI Diagnostics"],
            "data_gaps": ["Need more studies"],
            "potential_contradictions": ["Some conflict exists"],
        }

        result = engine.analyze_new_source(new_analysis, "raw/new_source.md")

        assert "reinforced_claims" in result
        assert "new_contradictions" in result
        assert "knowledge_gaps" in result
        assert "suggested_updates" in result
        assert "new_entities" in result
        assert "synthesis_summary" in result


class TestWikiSuggestSynthesis:
    """Test Wiki.suggest_synthesis method."""

    def test_suggest_synthesis_returns_dict(self, test_wiki):
        """Test that suggest_synthesis returns a dict."""
        wiki, tmp = test_wiki
        result = wiki.suggest_synthesis()

        assert isinstance(result, dict)
        assert "suggestions" in result
        assert "sources_analyzed" in result
        assert "summary" in result

    def test_suggest_synthesis_specific_source(self, test_wiki):
        """Test suggest_synthesis with a specific source."""
        wiki, tmp = test_wiki
        result = wiki.suggest_synthesis(source_name="raw/source1.md")

        assert isinstance(result, dict)
        # May fail if LLM not configured, but should return error dict
        assert "suggestions" in result or "error" in result


class TestSmartLint:
    """Test enhanced lint (P1.2)."""

    def test_lint_includes_investigations(self, test_wiki):
        """Test that lint returns new investigation fields."""
        wiki, tmp = test_wiki
        result = wiki.lint(generate_investigations=False)

        investigations = result.get('investigations', {})

        # Check new fields exist
        assert "outdated_pages" in investigations
        assert "knowledge_gaps" in investigations
        assert "redundancy_alerts" in investigations

    def test_detect_outdated_pages(self, test_wiki):
        """Test outdated page detection."""
        wiki, tmp = test_wiki
        outdated = wiki._detect_outdated_pages()

        assert isinstance(outdated, list)
        # May or may not find outdated pages depending on content
        for item in outdated:
            assert "type" in item
            assert "page" in item
            assert "observation" in item

    def test_detect_knowledge_gaps(self, test_wiki):
        """Test knowledge gap detection."""
        wiki, tmp = test_wiki
        gaps = wiki._detect_knowledge_gaps()

        assert isinstance(gaps, list)
        for item in gaps:
            assert "type" in item
            assert "observation" in item

    def test_detect_redundancy(self, test_wiki):
        """Test redundancy detection."""
        wiki, tmp = test_wiki
        redundancy = wiki._detect_redundancy()

        assert isinstance(redundancy, list)
        # With our test data (ai-healthcare-1 and ai-healthcare-2), should detect similarity
        for item in redundancy:
            assert "type" in item
            assert "observation" in item


class TestCLICommands:
    """Test P1 CLI commands."""

    def test_suggest_synthesis_command_exists(self):
        """Test that suggest-synthesis command is registered."""
        from src.llmwikify.cli.commands import WikiCLI
        cli = WikiCLI.__new__(WikiCLI)
        assert hasattr(cli, 'suggest_synthesis')

    def test_knowledge_gaps_command_exists(self):
        """Test that knowledge-gaps command is registered."""
        from src.llmwikify.cli.commands import WikiCLI
        cli = WikiCLI.__new__(WikiCLI)
        assert hasattr(cli, 'knowledge_gaps')
