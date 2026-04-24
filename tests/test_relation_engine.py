"""Unit tests for RelationEngine class."""

import pytest

from llmwikify.core import WikiIndex
from llmwikify.core.relation_engine import RelationEngine, DEFAULT_RELATION_TYPES, CONFIDENCE_LEVELS


class TestRelationEngineInit:
    """Tests for RelationEngine initialization."""

    def test_init_with_wiki_root(self, wiki_instance):
        """Test initializing RelationEngine with explicit wiki_root."""
        engine = RelationEngine(wiki_instance.index, wiki_root=wiki_instance.root)
        assert engine.wiki_root == wiki_instance.root
        assert engine._relation_types == DEFAULT_RELATION_TYPES

    def test_init_without_wiki_root(self, wiki_instance):
        """Test initializing RelationEngine without wiki_root (infers from DB)."""
        engine = RelationEngine(wiki_instance.index)
        assert engine.wiki_root is not None
        assert engine._relation_types == DEFAULT_RELATION_TYPES

    def test_get_relation_types_returns_copy(self, wiki_instance):
        """Test get_relation_types returns a copy to prevent mutation."""
        engine = RelationEngine(wiki_instance.index)
        types = engine.get_relation_types()
        types.add("fake_type")
        assert "fake_type" not in engine.get_relation_types()

    def test_table_creation(self, wiki_instance):
        """Test that relations table is created on init."""
        engine = RelationEngine(wiki_instance.index)
        cursor = wiki_instance.index.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relations'"
        )
        assert cursor.fetchone() is not None


class TestRelationEngineAddRelation:
    """Tests for adding relations."""

    def test_add_single_relation(self, wiki_instance):
        """Test adding a single valid relation."""
        engine = RelationEngine(wiki_instance.index)
        rel_id = engine.add_relation(
            source="Attention",
            target="Softmax",
            relation="uses",
            confidence="EXTRACTED",
            source_file="paper.md",
            context="Attention mechanism uses softmax",
            wiki_pages=["attention.md"],
        )
        assert rel_id > 0

    def test_add_relation_duplicate_skip(self, wiki_instance):
        """Test that duplicate relations are skipped."""
        engine = RelationEngine(wiki_instance.index)
        rel_id1 = engine.add_relation(
            source="A", target="B", relation="related_to", source_file="test.md"
        )
        rel_id2 = engine.add_relation(
            source="A", target="B", relation="related_to", source_file="test.md"
        )
        assert rel_id1 == rel_id2

    def test_add_relation_invalid_type(self, wiki_instance):
        """Test adding relation with invalid type raises ValueError."""
        engine = RelationEngine(wiki_instance.index)
        with pytest.raises(ValueError, match="Unknown relation type"):
            engine.add_relation(source="A", target="B", relation="invalid_type")

    def test_add_relation_invalid_confidence(self, wiki_instance):
        """Test adding relation with invalid confidence raises ValueError."""
        engine = RelationEngine(wiki_instance.index)
        with pytest.raises(ValueError, match="Unknown confidence"):
            engine.add_relation(source="A", target="B", relation="uses", confidence="INVALID")

    def test_add_relations_batch(self, wiki_instance):
        """Test batch adding relations."""
        engine = RelationEngine(wiki_instance.index)
        relations = [
            {"source": "A", "target": "B", "relation": "uses"},
            {"source": "B", "target": "C", "relation": "related_to"},
            {"source": "INVALID", "relation": "bad"},  # Invalid - should be skipped
        ]
        count = engine.add_relations(relations)
        assert count == 2


class TestRelationEngineNeighbors:
    """Tests for get_neighbors method."""

    @pytest.fixture
    def populated_engine(self, wiki_instance):
        """Create a RelationEngine with test data."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("A", "B", "uses", "EXTRACTED")
        engine.add_relation("B", "C", "related_to", "INFERRED")
        engine.add_relation("C", "A", "supports", "AMBIGUOUS")
        engine.add_relation("A", "D", "extends", "EXTRACTED")
        return engine

    def test_get_neighbors_both(self, populated_engine):
        """Test getting neighbors in both directions."""
        neighbors = populated_engine.get_neighbors("A", direction="both")
        assert len(neighbors) == 3  # A->B, C->A, A->D

    def test_get_neighbors_out(self, populated_engine):
        """Test getting outgoing neighbors."""
        neighbors = populated_engine.get_neighbors("A", direction="out")
        assert len(neighbors) == 2  # A->B, A->D

    def test_get_neighbors_in(self, populated_engine):
        """Test getting incoming neighbors."""
        neighbors = populated_engine.get_neighbors("A", direction="in")
        assert len(neighbors) == 1  # C->A

    def test_get_neighbors_with_confidence(self, populated_engine):
        """Test getting neighbors filtered by confidence."""
        neighbors = populated_engine.get_neighbors("A", direction="both", confidence="EXTRACTED")
        assert len(neighbors) == 2  # A->B, A->D (both EXTRACTED)

    def test_get_neighbors_empty(self, populated_engine):
        """Test getting neighbors for non-existent concept."""
        neighbors = populated_engine.get_neighbors("NONEXISTENT")
        assert neighbors == []


class TestRelationEnginePath:
    """Tests for get_path method."""

    @pytest.fixture
    def path_engine(self, wiki_instance):
        """Create a RelationEngine with a path."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("A", "B", "uses")
        engine.add_relation("B", "C", "uses")
        engine.add_relation("C", "D", "uses")
        engine.add_relation("X", "Y", "uses")
        return engine

    def test_get_path_direct(self, path_engine):
        """Test finding direct path."""
        result = path_engine.get_path("A", "B")
        assert result is not None
        assert result["path"] == ["A", "B"]
        assert len(result["edges"]) == 1

    def test_get_path_indirect(self, path_engine):
        """Test finding indirect path."""
        result = path_engine.get_path("A", "C")
        assert result is not None
        assert result["path"] == ["A", "B", "C"]
        assert len(result["edges"]) == 2

    def test_get_path_no_path(self, path_engine):
        """Test finding path between disconnected nodes returns None."""
        result = path_engine.get_path("A", "X")
        assert result is None

    def test_get_path_max_length_exceeded(self, path_engine):
        """Test path exceeding max_length returns None."""
        result = path_engine.get_path("A", "D", max_length=2)
        assert result is None  # A->B->C->D is length 3, exceeds max_length=2

    def test_get_path_same_node(self, path_engine):
        """Test path from node to itself."""
        result = path_engine.get_path("A", "A")
        assert result is not None
        assert result["path"] == ["A"]
        assert len(result["edges"]) == 0


class TestRelationEngineStats:
    """Tests for get_stats method."""

    def test_get_stats_empty(self, wiki_instance):
        """Test stats on empty engine."""
        engine = RelationEngine(wiki_instance.index)
        stats = engine.get_stats()
        assert stats["total_relations"] == 0
        assert stats["unique_concepts"] == 0

    def test_get_stats_with_data(self, wiki_instance):
        """Test stats with relations present."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("A", "B", "uses", "EXTRACTED")
        engine.add_relation("B", "C", "related_to", "INFERRED")
        engine.add_relation("C", "A", "supports", "AMBIGUOUS")

        stats = engine.get_stats()
        assert stats["total_relations"] == 3
        assert stats["by_confidence"]["EXTRACTED"] == 1
        assert stats["by_confidence"]["INFERRED"] == 1
        assert stats["by_confidence"]["AMBIGUOUS"] == 1
        assert stats["unique_concepts"] == 3  # A, B, C
        assert "uses" in stats["by_relation"]
        assert "related_to" in stats["by_relation"]


class TestRelationEngineOrphans:
    """Tests for find_orphan_concepts method."""

    def test_find_orphan_concepts_empty(self, wiki_instance):
        """Test orphan detection on empty database."""
        engine = RelationEngine(wiki_instance.index)
        orphans = engine.find_orphan_concepts()
        assert orphans == []

    def test_find_orphan_concepts_with_pages(self, wiki_instance):
        """Test orphan detection when concepts have wiki pages."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("ConceptA", "ConceptB", "related_to")
        engine.add_relation("ConceptC", "ConceptD", "uses")

        # Create pages for some concepts
        wiki_instance.write_page("ConceptA", "# Concept A\n")
        wiki_instance.write_page("ConceptB", "# Concept B\n")

        orphans = engine.find_orphan_concepts()
        # ConceptC and ConceptD have relations but no pages = orphans
        assert "ConceptC" in orphans
        assert "ConceptD" in orphans
        assert "ConceptA" not in orphans
        assert "ConceptB" not in orphans


class TestRelationEngineContradictions:
    """Tests for detect_contradictions method."""

    def test_detect_contradictions_empty(self, wiki_instance):
        """Test contradiction detection on empty database."""
        engine = RelationEngine(wiki_instance.index)
        contradictions = engine.detect_contradictions()
        assert contradictions == []

    def test_detect_contradictions_found(self, wiki_instance):
        """Test contradiction detection finds contradicting relations."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("A", "B", "supports", source_file="source1.md")
        engine.add_relation("A", "B", "contradicts", source_file="source2.md")

        contradictions = engine.detect_contradictions()
        assert len(contradictions) == 1
        assert contradictions[0]["source"] == "A"
        assert contradictions[0]["target"] == "B"
        assert contradictions[0]["relation1"] in ("supports", "contradicts")
        assert contradictions[0]["relation2"] in ("supports", "contradicts")
        assert contradictions[0]["relation1"] != contradictions[0]["relation2"]

    def test_detect_contradictions_none(self, wiki_instance):
        """Test no contradictions when no conflicting relations exist."""
        engine = RelationEngine(wiki_instance.index)
        engine.add_relation("A", "B", "supports", source_file="source1.md")
        engine.add_relation("A", "C", "uses", source_file="source2.md")

        contradictions = engine.detect_contradictions()
        assert contradictions == []
