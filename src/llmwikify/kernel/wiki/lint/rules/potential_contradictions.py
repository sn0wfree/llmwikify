"""Rule: detect potential contradictions (value conflicts, year conflicts, negations)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...constants import MAX_CONTRADICTIONS
from .. import Rule

if TYPE_CHECKING:
    from ...wiki import Wiki


class PotentialContradictionsRule(Rule):
    """Scan wiki pages for potential contradictions.

    Detects three flavors of contradiction:
    1. ``value_conflict`` — same key, different values across pages
    2. ``year_conflict`` — different year claims for the same entity
    3. ``negation_pattern`` — same subject has both affirmative and
       negative claims

    Extracted from ``WikiAnalyzer._detect_potential_contradictions``.
    Behavior is preserved.
    """

    name = "contradiction"  # logical name; type field uses concrete subtypes

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        contradictions: list[dict[str, Any]] = []
        seen_pairs: set = set()

        if not wiki.wiki_dir.exists():
            return contradictions

        pages_content = {}
        for page in wiki._wiki_pages():
            page_name = wiki._page_display_name(page)
            pages_content[page_name] = page.read_text()

        # 1. Value conflicts (key: value pairs with different values)
        entity_facts: dict[str, dict[str, list[tuple]]] = {}
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                line = line.strip().lstrip('- ').strip()
                if ':' in line and not line.startswith('#') and not line.startswith('http'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        if len(key) >= 2 and len(key) <= 30 and len(value) >= 2 and len(value) <= 50:
                            if key not in entity_facts:
                                entity_facts[key] = {}
                            if page_name not in entity_facts[key]:
                                entity_facts[key][page_name] = []
                            entity_facts[key][page_name].append(value)

        for attr, page_values in entity_facts.items():
            if len(page_values) < 2:
                continue
            all_values = []
            for page_name, values in page_values.items():
                for v in values:
                    all_values.append((page_name, v))

            unique_values = {str(v).lower() for _, v in all_values}
            if len(unique_values) >= 2:
                pair_key = tuple(sorted([p for p, _ in all_values]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    values_str = ", ".join(f"{p}={v}" for p, v in all_values[:3])
                    contradictions.append({
                        "type": "value_conflict",
                        "attribute": attr,
                        "pages": [{"page": p, "value": v} for p, v in all_values[:4]],
                        "observation": f"Pages reference different values for '{attr}': {values_str}",
                    })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        # 2. Year conflicts
        year_claims: dict[str, list[dict]] = {}
        year_pattern = re.compile(
            r'([^\n]{3,30}?)\s+(?:launched|founded|started|established|created|born|died|closed|shutdown|ended)\s+(?:in\s+)?(20\d{2}|19\d{2})',
            re.IGNORECASE
        )
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                for match in year_pattern.finditer(line):
                    entity = match.group(1).strip()
                    year = match.group(2)
                    if entity and len(entity) <= 30:
                        if entity not in year_claims:
                            year_claims[entity] = []
                        year_claims[entity].append({"page": page_name, "year": year})

        for entity, claims in year_claims.items():
            years = {c["year"] for c in claims}
            if len(years) >= 2:
                claims_str = ", ".join(f"{c['page']}={c['year']}" for c in claims[:3])
                contradictions.append({
                    "type": "year_conflict",
                    "entity": entity,
                    "claims": claims,
                    "observation": f"'{entity}' has conflicting year claims: {claims_str}",
                })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        # 3. Negation patterns
        negation_claims: dict[str, list[dict]] = {}
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                assertion_pattern = re.compile(
                    r'([\w\s]{3,25}?)\s+(?:is|are|was|were)\s+(?:not\s+|no\s+longer\s+)?([\w\s]{3,30}?)(?:\.|,|;|$)',
                    re.IGNORECASE
                )
                for match in assertion_pattern.finditer(line):
                    subject = match.group(1).strip()
                    predicate = match.group(2).strip()
                    full_match = match.group(0).lower()
                    is_negated = bool(re.search(r'\b(?:is|are|was|were)\s+(?:not|no longer)', full_match))

                    key = subject.lower()
                    if key not in negation_claims:
                        negation_claims[key] = []
                    negation_claims[key].append({
                        "page": page_name,
                        "predicate": predicate,
                        "negated": is_negated,
                    })

        for subject, claims in negation_claims.items():
            has_positive = any(not c["negated"] for c in claims)
            has_negative = any(c["negated"] for c in claims)
            if has_positive and has_negative:
                contradictions.append({
                    "type": "negation_pattern",
                    "subject": subject,
                    "claims": claims,
                    "observation": f"'{subject}' has both affirmative and negative claims across pages",
                })

            if len(contradictions) >= MAX_CONTRADICTIONS:
                break

        return contradictions[:MAX_CONTRADICTIONS]
