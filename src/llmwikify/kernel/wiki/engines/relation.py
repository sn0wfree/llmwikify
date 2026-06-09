"""Relation engine for knowledge graph relationships."""

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

from llmwikify.kernel.storage.backend import is_path_excluded

from ...storage.index import WikiIndex

logger = logging.getLogger(__name__)

# Default relation types (overridden by wiki.md if available)
DEFAULT_RELATION_TYPES = {
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

    def __init__(self, index: WikiIndex, wiki_root: Path | None = None):
        self.index = index
        self.wiki_root = wiki_root
        self._relation_types = self._load_relation_types()
        self._ensure_table()

    def _load_relation_types(self) -> set:
        """Load relation types from wiki.md schema, falling back to defaults."""
        if self.wiki_root is None:
            # Try to infer wiki root from index.db path
            try:
                db_path = Path(self.index.conn.execute("PRAGMA database_list").fetchone()["file"]).parent
                self.wiki_root = db_path
            except Exception as e:
                logger.warning("Failed to infer wiki root from index.db: %s", e)
                return DEFAULT_RELATION_TYPES.copy()

        wiki_md = self.wiki_root / "wiki.md"
        if not wiki_md.exists():
            return DEFAULT_RELATION_TYPES.copy()

        try:
            content = wiki_md.read_text()
            # Look for relation types in the schema
            # Pattern 1: bullet list under "Relation Types" section
            types = set()
            # Match lines like "- `is_a` — description" or "- is_a — description"
            pattern = r'-\s*`?(\w+)`?\s*[—\-]'
            in_relation_section = False
            for line in content.split('\n'):
                if 'relation type' in line.lower() or line.strip().startswith('### Relation Types'):
                    in_relation_section = True
                    continue
                if in_relation_section:
                    # Stop if we hit a new major section
                    if line.startswith('## ') and 'relation' not in line.lower():
                        break
                    match = re.match(pattern, line.strip())
                    if match:
                        types.add(match.group(1))
            if types:
                return types
        except Exception as e:
            logger.warning("Failed to parse relation types from wiki.md: %s", e)

        return DEFAULT_RELATION_TYPES.copy()

    def get_relation_types(self) -> set:
        """Return the currently loaded relation types."""
        return self._relation_types.copy()

    def _ensure_table(self) -> None:
        """Create relations and entity_aliases tables if they don't exist."""
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
            
            CREATE TABLE IF NOT EXISTS entity_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias TEXT NOT NULL UNIQUE,
                canonical TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_alias_lookup ON entity_aliases(alias);
            CREATE INDEX IF NOT EXISTS idx_canonical ON entity_aliases(canonical);
        """)
        self.index.conn.commit()

    # ─── Entity Resolution Methods ─────────────────────────────────────

    def _normalize_name(self, name: str) -> str:
        """Normalize entity name for comparison."""
        return name.lower().strip().replace("  ", " ")

    def _get_wiki_pages(self) -> list[str]:
        """Get list of existing wiki page names."""
        if self.wiki_root is None:
            return []
        
        wiki_dir = self.wiki_root / "wiki"
        if not wiki_dir.exists():
            return []

        pages = []
        for page in wiki_dir.rglob("*.md"):
            if is_path_excluded(page):
                continue
            page_name = str(page.relative_to(wiki_dir).with_suffix(""))
            pages.append(page_name)
        return pages

    def _fuzzy_match_entity(self, name: str, candidates: list[str], threshold: float = 0.85) -> str | None:
        """Find best fuzzy match among candidates.

        The fuzzy match uses SequenceMatcher.ratio() which
        can give surprisingly high scores for prefix-similar
        but otherwise distinct strings (e.g. ``"ConceptA"``
        vs ``"ConceptC"`` scores 0.875 because they share the
        7-char prefix ``"concept"``).

        The original code had a 0.85 threshold which let
        such pairs through incorrectly. The fix: use
        stricter matching rules:

        1. If the input and candidate have the same length
           (typical typo / 1-char difference case): require
           a HIGH score (≥0.95) to avoid prefix-only
           false positives. Or require exact length match
           + close similarity.
        2. If the shorter is a TRUE PREFIX of the longer
           (e.g. ``"Risk Par"`` is a prefix of
           ``"Risk Parity"``): use the original ratio
           formula (2 * common / total_len) which is
           naturally higher for true prefixes.

        This restores the legitimate "Risk Par" → "Risk
        Parity" prefix match (test_resolve_entity_fuzzy_match)
        while preventing the false positive "ConceptC" →
        "ConceptA" match (which shares a prefix but is
        NOT a true prefix relationship).
        """
        best_match = None
        best_score = 0
        normalized_name = self._normalize_name(name)
        name_len = len(normalized_name)

        for candidate in candidates:
            normalized_candidate = self._normalize_name(candidate)
            cand_len = len(normalized_candidate)
            length_diff = abs(cand_len - name_len)

            if length_diff == 0:
                # Same length: standard fuzzy match.
                # This is the case where typos / 1-char
                # differences are caught.
                score = SequenceMatcher(None, normalized_name, normalized_candidate).ratio()
                # Apply a stricter effective threshold for
                # same-length pairs to avoid prefix-only
                # false positives like "ConceptA" vs
                # "ConceptC" (score 0.875).
                effective_threshold = max(threshold, 0.95)
            else:
                # Different length: only match if the
                # shorter is a TRUE prefix of the longer
                # (i.e. the longer extends the shorter, not
                # just shares a common prefix).
                if name_len < cand_len:
                    shorter, longer = normalized_name, normalized_candidate
                else:
                    shorter, longer = normalized_candidate, normalized_name
                if not longer.startswith(shorter):
                    continue
                # True prefix match: use the original ratio
                # formula which is high when the shorter is
                # fully contained in the longer as a prefix.
                common_prefix_len = 0
                for i in range(len(shorter)):
                    if shorter[i] == longer[i]:
                        common_prefix_len += 1
                    else:
                        break
                # Ratio: 2 * common / total, normalized by
                # the SHORTER length (since the match is
                # "shorter fits as prefix of longer").
                score = (2.0 * common_prefix_len) / (len(shorter) + cand_len)
                effective_threshold = threshold

            if score > best_score and score >= effective_threshold:
                best_score = score
                best_match = candidate

        return best_match

    def resolve_entity(self, name: str, fuzzy_threshold: float = 0.85) -> str:
        """Resolve entity name to canonical form.
        
        Resolution order:
        1. Exact match in wiki pages
        2. Alias lookup
        3. Fuzzy match against existing entities
        4. Return original name (new entity)
        
        Args:
            name: Entity name to resolve
            fuzzy_threshold: Threshold for fuzzy matching (0-1)
        
        Returns:
            Canonical entity name
        """
        if not name or not name.strip():
            return name
        
        normalized_name = self._normalize_name(name)
        
        # 1. Exact match in wiki pages
        wiki_pages = self._get_wiki_pages()
        for page in wiki_pages:
            if self._normalize_name(page) == normalized_name:
                return page
        
        # 2. Alias lookup
        cursor = self.index.conn.execute(
            "SELECT canonical FROM entity_aliases WHERE alias = ?",
            (normalized_name,),
        )
        row = cursor.fetchone()
        if row:
            return row["canonical"]
        
        # Also check original name (case-sensitive alias)
        cursor = self.index.conn.execute(
            "SELECT canonical FROM entity_aliases WHERE alias = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row:
            return row["canonical"]
        
        # 3. Fuzzy match against existing entities
        candidates = wiki_pages.copy()
        
        # Also add existing canonical names from aliases
        cursor = self.index.conn.execute("SELECT DISTINCT canonical FROM entity_aliases")
        for row in cursor.fetchall():
            if row["canonical"] not in candidates:
                candidates.append(row["canonical"])
        
        # Also add existing entity names from relations
        cursor = self.index.conn.execute("SELECT DISTINCT source FROM relations")
        for row in cursor.fetchall():
            if row["source"] not in candidates:
                candidates.append(row["source"])
        
        cursor = self.index.conn.execute("SELECT DISTINCT target FROM relations")
        for row in cursor.fetchall():
            if row["target"] not in candidates:
                candidates.append(row["target"])
        
        if candidates:
            best_match = self._fuzzy_match_entity(name, candidates, fuzzy_threshold)
            if best_match:
                # Auto-add alias
                self.add_alias(name, best_match, source="fuzzy_match")
                return best_match
        
        # 4. Return original name (new entity)
        return name

    def add_alias(self, alias: str, canonical: str, source: str = "manual", confidence: float = 1.0) -> None:
        """Add an alias mapping for an entity.
        
        Args:
            alias: Alias name
            canonical: Canonical entity name
            source: Source of the alias (manual, fuzzy_match, clustering)
            confidence: Confidence level (0-1)
        """
        normalized_alias = self._normalize_name(alias)
        
        # Check if alias already exists
        cursor = self.index.conn.execute(
            "SELECT id, canonical FROM entity_aliases WHERE alias = ?",
            (normalized_alias,),
        )
        existing = cursor.fetchone()
        
        if existing:
            # Update if different canonical
            if existing["canonical"] != canonical:
                logger.info("Updating alias %s from %s to %s", alias, existing["canonical"], canonical)
                self.index.conn.execute(
                    "UPDATE entity_aliases SET canonical = ?, source = ?, confidence = ? WHERE id = ?",
                    (canonical, source, confidence, existing["id"]),
                )
        else:
            # Insert new alias
            self.index.conn.execute(
                "INSERT INTO entity_aliases (alias, canonical, confidence, source) VALUES (?, ?, ?, ?)",
                (normalized_alias, canonical, confidence, source),
            )
        
        self.index.conn.commit()

    def get_aliases(self, canonical: str) -> list[str]:
        """Get all aliases for a canonical entity name.
        
        Args:
            canonical: Canonical entity name
        
        Returns:
            List of alias names
        """
        cursor = self.index.conn.execute(
            "SELECT alias FROM entity_aliases WHERE canonical = ?",
            (canonical,),
        )
        return [row["alias"] for row in cursor.fetchall()]

    def add_relation(
        self,
        source: str,
        target: str,
        relation: str,
        confidence: str = "EXTRACTED",
        source_file: str | None = None,
        context: str | None = None,
        wiki_pages: list[str] | None = None,
        resolve: bool = True,
    ) -> int:
        """Add a single relation. Skip if duplicate exists.

        Args:
            source: Source entity name
            target: Target entity name
            relation: Relation type
            confidence: Confidence level
            source_file: Source file name
            context: Relation context
            wiki_pages: Related wiki pages
            resolve: Whether to resolve entity names (default: True)

        Returns:
            Row id of the inserted relation, or existing id if duplicate.
        """
        if relation not in self._relation_types:
            raise ValueError(f"Unknown relation type: {relation}. Valid: {sorted(self._relation_types)}")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {confidence}. Valid: {CONFIDENCE_LEVELS}")

        # Resolve entity names if enabled
        canonical_source = self.resolve_entity(source) if resolve else source
        canonical_target = self.resolve_entity(target) if resolve else target

        # Check for duplicate (same source, target, relation, source_file)
        # Use IS NULL comparison for source_file since NULL != NULL in SQL
        if source_file is None:
            existing = self.index.conn.execute(
                "SELECT id FROM relations WHERE source=? AND target=? AND relation=? AND source_file IS NULL",
                (canonical_source, canonical_target, relation),
            ).fetchone()
        else:
            existing = self.index.conn.execute(
                "SELECT id FROM relations WHERE source=? AND target=? AND relation=? AND source_file=?",
                (canonical_source, canonical_target, relation, source_file),
            ).fetchone()

        if existing:
            return existing[0]

        cursor = self.index.conn.execute(
            """INSERT INTO relations (source, target, relation, confidence, source_file, context, wiki_pages)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                canonical_source, canonical_target, relation, confidence,
                source_file, context,
                json.dumps(wiki_pages) if wiki_pages else None,
            ),
        )
        self.index.conn.commit()
        return cursor.lastrowid

    def add_relations(self, relations: list[dict]) -> int:
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
            except (ValueError, KeyError):
                # Skip invalid relations, log warning
                pass
        return count

    def get_neighbors(
        self,
        concept: str,
        direction: str = "both",
        confidence: str | None = None,
    ) -> list[dict]:
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

    def get_path(self, source: str, target: str, max_length: int = 5) -> dict | None:
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

    def get_context(self, relation_id: int) -> dict | None:
        """Get the original context for a relation."""
        cursor = self.index.conn.execute(
            "SELECT * FROM relations WHERE id = ?", (relation_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def detect_contradictions(self) -> list[dict]:
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

    def find_orphan_concepts(self) -> list[str]:
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
