"""Tests for v0.22.0 Relation Engine."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core.index import WikiIndex
from llmwikify.core.relation_engine import RelationEngine, RELATION_TYPES, CONFIDENCE_LEVELS


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    index = WikiIndex(db_path)
    index.initialize()
    yield index
    index.close()


@pytest.fixture
def engine(temp_db):
    return RelationEngine(temp_db)


class TestRelationSchema:
    def test_relation_types(self):
        assert "is_a" in RELATION_TYPES
        assert "uses" in RELATION_TYPES
        assert "contradicts" in RELATION_TYPES
        assert len(RELATION_TYPES) == 8

    def test_confidence_levels(self):
        assert CONFIDENCE_LEVELS == {"EXTRACTED", "INFERRED", "AMBIGUOUS"}

    def test_table_created(self, engine):
        cursor = engine.index.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relations'"
        )
        assert cursor.fetchone() is not None


class TestAddRelation:
    def test_add_single_relation(self, engine):
        rel_id = engine.add_relation("Attention", "Softmax", "uses", "EXTRACTED")
        assert rel_id is not None
        assert rel_id > 0

    def test_add_with_source_file(self, engine):
        rel_id = engine.add_relation(
            "A", "B", "related_to", "INFERRED",
            source_file="paper.pdf", context="Some context"
        )
        result = engine.get_context(rel_id)
        assert result["source_file"] == "paper.pdf"
        assert result["context"] == "Some context"

    def test_invalid_relation_type(self, engine):
        with pytest.raises(ValueError, match="Unknown relation type"):
            engine.add_relation("A", "B", "invalid_type")

    def test_invalid_confidence(self, engine):
        with pytest.raises(ValueError, match="Unknown confidence"):
            engine.add_relation("A", "B", "uses", "INVALID")

    def test_batch_add(self, engine):
        relations = [
            {"source": "A", "target": "B", "relation": "uses", "confidence": "EXTRACTED"},
            {"source": "B", "target": "C", "relation": "related_to", "confidence": "INFERRED"},
            {"source": "C", "target": "D", "relation": "is_a", "confidence": "AMBIGUOUS"},
        ]
        count = engine.add_relations(relations)
        assert count == 3

    def test_batch_add_skips_invalid(self, engine):
        relations = [
            {"source": "A", "target": "B", "relation": "uses"},
            {"source": "X", "target": "Y", "relation": "invalid_type"},
        ]
        count = engine.add_relations(relations)
        assert count == 1  # Only valid one added


class TestNeighbors:
    def test_get_neighbors_both_directions(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("C", "A", "related_to")
        neighbors = engine.get_neighbors("A")
        assert len(neighbors) == 2

    def test_get_neighbors_out_only(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("C", "A", "related_to")
        neighbors = engine.get_neighbors("A", direction="out")
        assert len(neighbors) == 1
        assert neighbors[0]["target"] == "B"

    def test_get_neighbors_in_only(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("C", "A", "related_to")
        neighbors = engine.get_neighbors("A", direction="in")
        assert len(neighbors) == 1
        assert neighbors[0]["source"] == "C"

    def test_filter_by_confidence(self, engine):
        engine.add_relation("A", "B", "uses", "EXTRACTED")
        engine.add_relation("A", "C", "related_to", "AMBIGUOUS")
        neighbors = engine.get_neighbors("A", confidence="EXTRACTED")
        assert len(neighbors) == 1
        assert neighbors[0]["confidence"] == "EXTRACTED"


class TestPathQuery:
    def test_find_path(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("B", "C", "related_to")
        result = engine.get_path("A", "C")
        assert result is not None
        assert result["path"] == ["A", "B", "C"]

    def test_no_path(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("C", "D", "related_to")
        result = engine.get_path("A", "D")
        assert result is None

    def test_path_respects_max_length(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("B", "C", "uses")
        engine.add_relation("C", "D", "uses")
        engine.add_relation("D", "E", "uses")
        engine.add_relation("E", "F", "uses")
        result = engine.get_path("A", "F", max_length=2)
        assert result is None  # Path is too long


class TestStats:
    def test_empty_stats(self, engine):
        stats = engine.get_stats()
        assert stats["total_relations"] == 0
        assert stats["unique_concepts"] == 0

    def test_stats_with_data(self, engine):
        engine.add_relation("A", "B", "uses", "EXTRACTED")
        engine.add_relation("B", "C", "uses", "INFERRED")
        stats = engine.get_stats()
        assert stats["total_relations"] == 2
        assert stats["unique_concepts"] == 3
        assert stats["by_confidence"]["EXTRACTED"] == 1
        assert stats["by_confidence"]["INFERRED"] == 1
        assert stats["by_relation"]["uses"] == 2


class TestContext:
    def test_get_context(self, engine):
        rel_id = engine.add_relation(
            "A", "B", "uses", "EXTRACTED",
            source_file="paper.pdf", context="Quote from paper"
        )
        result = engine.get_context(rel_id)
        assert result["source"] == "A"
        assert result["target"] == "B"
        assert result["source_file"] == "paper.pdf"

    def test_get_context_not_found(self, engine):
        result = engine.get_context(999)
        assert result is None


class TestContradictions:
    def test_detect_contradictions(self, engine):
        engine.add_relation("A", "B", "supports", "EXTRACTED", source_file="paper1.pdf")
        engine.add_relation("A", "B", "contradicts", "EXTRACTED", source_file="paper2.pdf")
        contradictions = engine.detect_contradictions()
        assert len(contradictions) >= 1

    def test_no_contradictions(self, engine):
        engine.add_relation("A", "B", "uses")
        engine.add_relation("A", "C", "related_to")
        contradictions = engine.detect_contradictions()
        assert len(contradictions) == 0


class TestOrphanConcepts:
    def test_no_orphans(self, engine):
        orphans = engine.find_orphan_concepts()
        assert len(orphans) == 0

    def test_find_orphans(self, engine):
        engine.add_relation("A", "B", "uses")
        # pages table is empty, so A and B are orphans
        orphans = engine.find_orphan_concepts()
        assert len(orphans) >= 1


class TestIngestRelations:
    def test_write_relations_from_wiki(self, temp_db, wiki_instance):
        relations = [
            {"source": "A", "target": "B", "relation": "uses", "confidence": "EXTRACTED"},
        ]
        result = wiki_instance.write_relations(relations, source_file="test.pdf")
        assert result["status"] == "completed"
        assert result["count"] == 1

    def test_write_relations_empty(self, wiki_instance):
        result = wiki_instance.write_relations([])
        assert result["status"] == "skipped"
        assert result["count"] == 0
