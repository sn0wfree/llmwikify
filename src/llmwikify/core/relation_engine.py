"""Relation engine for knowledge graph relationships."""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from .index import WikiIndex


# Valid relation types
RELATION_TYPES = {
    "is_a", "uses", "related_to", "contradicts",
    "supports", "replaces", "optimizes", "extends",
}

# Valid confidence levels
CONFIDENCE_LEVELS = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


class RelationEngine:
    """Manage knowledge graph relations stored in SQLite.

    Usage:
        engine = RelationEngine(wiki_index)
        engine.add_relation("Attention", "Softmax", "uses", "EXTRACTED", source_file="paper.pdf")
        relations = engine.get_neighbors("Attention")
    """

    def __init__(self, index: WikiIndex):
        self.index = index
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create relations table if it doesn't exist."""
        self.index.conn.executescript("""
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL,
                confidence TEXT NOT NULL CHECK(confidence IN ('EXTRACTED','INFERRED','AMBIGUOUS')),
                source_file TEXT,
                context TEXT,
                wiki_pages TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target);
            CREATE INDEX IF NOT EXISTS idx_relations_pair ON relations(source, target);
        """)
        self.index.conn.commit()

    def add_relation(
        self,
        source: str,
        target: str,
        relation: str,
        confidence: str = "EXTRACTED",
        source_file: Optional[str] = None,
        context: Optional[str] = None,
        wiki_pages: Optional[List[str]] = None,
    ) -> int:
        """Add a single relation.

        Returns:
            Row id of the inserted relation.
        """
        if relation not in RELATION_TYPES:
            raise ValueError(f"Unknown relation type: {relation}. Valid: {RELATION_TYPES}")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {confidence}. Valid: {CONFIDENCE_LEVELS}")

        cursor = self.index.conn.execute(
            """INSERT INTO relations (source, target, relation, confidence, source_file, context, wiki_pages)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source, target, relation, confidence,
                source_file, context,
                json.dumps(wiki_pages) if wiki_pages else None,
            ),
        )
        self.index.conn.commit()
        return cursor.lastrowid

    def add_relations(self, relations: List[dict]) -> int:
        """Batch add relations.

        Args:
            relations: List of dicts with keys: source, target, relation,
                       confidence, source_file, context, wiki_pages.

        Returns:
            Number of relations added.
        """
        count = 0
        for r in relations:
            try:
                self.add_relation(
                    source=r["source"],
                    target=r["target"],
                    relation=r["relation"],
                    confidence=r.get("confidence", "EXTRACTED"),
                    source_file=r.get("source_file"),
                    context=r.get("context"),
                    wiki_pages=r.get("wiki_pages"),
                )
                count += 1
            except (ValueError, KeyError) as e:
                # Skip invalid relations, log warning
                pass
        return count

    def get_neighbors(
        self,
        concept: str,
        direction: str = "both",
        confidence: Optional[str] = None,
    ) -> List[dict]:
        """Get all relations for a concept.

        Args:
            concept: Concept name.
            direction: 'in', 'out', or 'both'.
            confidence: Filter by confidence level.

        Returns:
            List of relation dicts.
        """
        query = "SELECT * FROM relations WHERE "
        params: list = []

        conditions = []
        if direction == "out":
            conditions.append("source = ?")
            params.append(concept)
        elif direction == "in":
            conditions.append("target = ?")
            params.append(concept)
        else:
            conditions.append("(source = ? OR target = ?)")
            params.extend([concept, concept])

        if confidence:
            conditions.append("confidence = ?")
            params.append(confidence)

        query += " AND ".join(conditions) + " ORDER BY created_at DESC"

        cursor = self.index.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_path(self, source: str, target: str, max_length: int = 5) -> Optional[dict]:
        """Find shortest path between two concepts.

        Args:
            source: Start concept.
            target: End concept.
            max_length: Maximum path length.

        Returns:
            Dict with 'path' (list of concepts) and 'edges' (relation details),
            or None if no path found.
        """
        try:
            import networkx as nx
        except ImportError:
            return None

        G = self._build_networkx_graph()

        try:
            path = nx.shortest_path(G, source, target)
            if len(path) > max_length + 1:
                return None

            edges = []
            for i in range(len(path) - 1):
                rels = self.index.conn.execute(
                    "SELECT relation, confidence FROM relations WHERE source=? AND target=?",
                    (path[i], path[i + 1]),
                ).fetchall()
                for r in rels:
                    edges.append({
                        "source": path[i],
                        "target": path[i + 1],
                        "relation": r["relation"],
                        "confidence": r["confidence"],
                    })

            return {"path": path, "edges": edges}
        except nx.NetworkXNoPath:
            return None

    def get_stats(self) -> dict:
        """Get relation statistics."""
        conn = self.index.conn

        total = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        by_confidence = {}
        for level in CONFIDENCE_LEVELS:
            count = conn.execute(
                "SELECT COUNT(*) FROM relations WHERE confidence = ?", (level,)
            ).fetchone()[0]
            by_confidence[level] = count

        by_relation = {}
        cursor = conn.execute(
            "SELECT relation, COUNT(*) as cnt FROM relations GROUP BY relation ORDER BY cnt DESC"
        )
        for row in cursor.fetchall():
            by_relation[row["relation"]] = row["cnt"]

        # Unique concepts
        unique_concepts = conn.execute(
            "SELECT COUNT(DISTINCT concept) FROM ("
            "  SELECT source AS concept FROM relations"
            "  UNION"
            "  SELECT target AS concept FROM relations"
            ")"
        ).fetchone()[0]

        return {
            "total_relations": total,
            "unique_concepts": unique_concepts,
            "by_confidence": by_confidence,
            "by_relation": by_relation,
        }

    def get_context(self, relation_id: int) -> Optional[dict]:
        """Get the original context for a relation."""
        cursor = self.index.conn.execute(
            "SELECT * FROM relations WHERE id = ?", (relation_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def detect_contradictions(self) -> List[dict]:
        """Find contradictory relations between same source/target pairs."""
        cursor = self.index.conn.execute(
            """SELECT r1.source, r1.target,
                      r1.relation as relation1, r1.confidence as conf1, r1.source_file as file1,
                      r2.relation as relation2, r2.confidence as conf2, r2.source_file as file2
               FROM relations r1
               JOIN relations r2
                 ON r1.source = r2.source AND r1.target = r2.target
               WHERE r1.id < r2.id
                 AND r1.relation != r2.relation
                 AND (
                     (r1.relation = 'supports' AND r2.relation = 'contradicts')
                     OR (r1.relation = 'contradicts' AND r2.relation = 'supports')
                     OR (r1.relation = 'uses' AND r2.relation = 'replaces')
                     OR (r1.relation = 'replaces' AND r2.relation = 'uses')
                 )"""
        )
        return [dict(row) for row in cursor.fetchall()]

    def find_orphan_concepts(self) -> List[str]:
        """Find concepts in relations that have no corresponding wiki page."""
        cursor = self.index.conn.execute(
            """SELECT DISTINCT concept FROM (
                SELECT source AS concept FROM relations
                WHERE source NOT IN (SELECT page_name FROM pages)
                UNION
                SELECT target AS concept FROM relations
                WHERE target NOT IN (SELECT page_name FROM pages)
            )"""
        )
        return [row["concept"] for row in cursor.fetchall()]

    def _build_networkx_graph(self):
        """Build a NetworkX graph from relations."""
        try:
            import networkx as nx
        except ImportError:
            raise ImportError("networkx is required for graph operations")

        G = nx.MultiDiGraph()

        cursor = self.index.conn.execute(
            "SELECT source, target, relation, confidence FROM relations"
        )
        for row in cursor.fetchall():
            G.add_edge(
                row["source"],
                row["target"],
                relation=row["relation"],
                confidence=row["confidence"],
            )

        return G
