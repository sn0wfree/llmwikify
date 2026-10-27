"""Parity guard: contradiction detection must match the pre-B1 reference.

The reference implementation below is the original (pre-B1) code —
regexes compiled inside the page×line loops. The optimized version in
``potential_contradictions`` must produce identical findings.

Self-contained: no git history required.
"""

from __future__ import annotations

import random
import re

from llmwikify.kernel.wiki.lint.rules.potential_contradictions import (
    PotentialContradictionsRule,
)

MAX_CONTRADICTIONS = 3


class _ReferenceRule:
    """Original implementation, kept verbatim as the parity oracle."""

    name = "contradiction"
    max_results = MAX_CONTRADICTIONS

    def detect_all(self, pages, wiki, results) -> None:
        seen_pairs: set = set()
        self._detect_value_conflicts(pages, results, seen_pairs)
        if len(results) >= self.max_results:
            return
        self._detect_year_conflicts(pages, results)
        if len(results) >= self.max_results:
            return
        self._detect_negation_patterns(pages, results)

    def _detect_value_conflicts(self, pages, results, seen_pairs) -> None:
        entity_facts: dict = {}
        for page_name, content in pages.items():
            for line in content.split("\n"):
                line = line.strip().lstrip("- ").strip()
                if ":" in line and not line.startswith("#") and not line.startswith("http"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        if (
                            len(key) >= 2
                            and len(key) <= 30
                            and len(value) >= 2
                            and len(value) <= 50
                        ):
                            entity_facts.setdefault(key, {}).setdefault(page_name, []).append(
                                value
                            )
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
                    results.append(
                        {
                            "type": "value_conflict",
                            "attribute": attr,
                            "pages": [{"page": p, "value": v} for p, v in all_values[:4]],
                            "observation": f"Pages reference different values for '{attr}': {values_str}",
                        }
                    )
            if len(results) >= self.max_results:
                break

    def _detect_year_conflicts(self, pages, results) -> None:
        year_claims: dict = {}
        year_pattern = re.compile(
            r"([^\n]{3,30}?)\s+(?:launched|founded|started|established|created|born|died|closed|shutdown|ended)\s+(?:in\s+)?(20\d{2}|19\d{2})",
            re.IGNORECASE,
        )
        for page_name, content in pages.items():
            for line in content.split("\n"):
                for match in year_pattern.finditer(line):
                    entity = match.group(1).strip()
                    year = match.group(2)
                    if entity and len(entity) <= 30:
                        year_claims.setdefault(entity, []).append(
                            {"page": page_name, "year": year}
                        )
        for entity, claims in year_claims.items():
            years = {c["year"] for c in claims}
            if len(years) >= 2:
                claims_str = ", ".join(f"{c['page']}={c['year']}" for c in claims[:3])
                results.append(
                    {
                        "type": "year_conflict",
                        "entity": entity,
                        "claims": claims,
                        "observation": f"'{entity}' has conflicting year claims: {claims_str}",
                    }
                )
            if len(results) >= self.max_results:
                break

    def _detect_negation_patterns(self, pages, results) -> None:
        negation_claims: dict = {}
        for page_name, content in pages.items():
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                assertion_pattern = re.compile(
                    r"([\w\s]{3,25}?)\s+(?:is|are|was|were)\s+(?:not\s+|no\s+longer\s+)?([\w\s]{3,30}?)(?:\.|,|;|$)",
                    re.IGNORECASE,
                )
                for match in assertion_pattern.finditer(line):
                    subject = match.group(1).strip()
                    predicate = match.group(2).strip()
                    full_match = match.group(0).lower()
                    is_negated = bool(
                        re.search(
                            r"\b(?:is|are|was|were)\s+(?:not|no longer)", full_match
                        )
                    )
                    negation_claims.setdefault(subject.lower(), []).append(
                        {
                            "page": page_name,
                            "predicate": predicate,
                            "negated": is_negated,
                        }
                    )
        for subject, claims in negation_claims.items():
            has_positive = any(not c["negated"] for c in claims)
            has_negative = any(c["negated"] for c in claims)
            if has_positive and has_negative:
                results.append(
                    {
                        "type": "negation_pattern",
                        "subject": subject,
                        "claims": claims,
                        "observation": f"'{subject}' has both affirmative and negative claims across pages",
                    }
                )
            if len(results) >= self.max_results:
                break


def _corpus() -> dict[str, str]:
    random.seed(20261023)
    pages = {
        "a.md": "sector: technology\nregion: asia\n",
        "b.md": "sector: finance\nregion: europe\n",
        "c.md": (
            "Bitcoin was launched in 2009.\n"
            "Acme was founded in 1999.\n"
            "The protocol is secure.\n"
            "The service is no longer stable.\n"
            "Nodes are online.\n"
        ),
        "d.md": (
            "Bitcoin was launched in 2011.\n"
            "Acme was founded in 2001.\n"
            "The protocol is not secure.\n"
            "The service is stable.\n"
            "Nodes were not online.\n"
        ),
        "e.md": (
            "# Heading is not a claim\n\n"
            "Mining uses heavy equipment and trucks.\n"
            "http://example.com/x:1\n"
            "x: yy\n"
            "Revenue grew in regional markets.\n"
            + ("alpha beta gamma delta epsilon zeta eta theta " * 8)
            + "\nThe system is degraded.\n"
        ),
        "f.md": (
            "The system is not degraded.\n"
            "  indented copula line is secure.  \n"
            "The protocol was robust.\n"
            "The protocol was not robust.\n"
            "Company was created in 1990.\n"
            "Company was created in 1995.\n"
        ),
    }
    for i in range(60):
        lines = []
        for _ in range(random.randint(1, 12)):
            kind = random.random()
            if kind < 0.2:
                lines.append(f"key{random.randint(0, 5)}: value{random.randint(0, 3)}")
            elif kind < 0.4:
                lines.append(
                    f"Entity{random.randint(0, 9)} was launched in {random.randint(1990, 2020)}."
                )
            elif kind < 0.6:
                lines.append(
                    f"Subject{random.randint(0, 9)} is {'not ' if random.random() < 0.5 else ''}good."
                )
            elif kind < 0.8:
                lines.append("Plain prose line without any structure at all.")
            else:
                lines.append("x" * random.randint(50, 200))
        pages[f"r{i}.md"] = "\n".join(lines)
    return pages


def _norm(results: list[dict]) -> list[str]:
    out = []
    for r in results:
        r = dict(r)
        for k, v in list(r.items()):
            if isinstance(v, list):
                r[k] = sorted(str(x) for x in v)
        out.append(f"{r['type']}|{sorted(r.keys())}|{r}")
    return sorted(out)


def test_new_matches_pre_b1_reference():
    pages = _corpus()
    ref_out: list[dict] = []
    _ReferenceRule().detect_all(pages, None, ref_out)
    new_out: list[dict] = []
    PotentialContradictionsRule().detect_all(pages, None, new_out)  # type: ignore[arg-type]
    assert _norm(new_out) == _norm(ref_out)


def test_new_matches_reference_on_minimal_inputs():
    """Each detector in isolation must agree with the reference."""
    cases = [
        ({"a.md": "sector: x\n", "b.md": "sector: y\n"}, "_detect_value_conflicts"),
        ({"a.md": "Acme was founded in 1999.\n"}, "_detect_year_conflicts"),
        ({"a.md": "The system is fine.\n"}, "_detect_negation_patterns"),
        ({}, "_detect_value_conflicts"),
    ]
    for pages, method in cases:
        ref: list[dict] = []
        new: list[dict] = []
        if method == "_detect_value_conflicts":
            _ReferenceRule()._detect_value_conflicts(pages, ref, set())
            PotentialContradictionsRule()._detect_value_conflicts(pages, new, set())
        else:
            getattr(_ReferenceRule(), method)(pages, ref)
            getattr(PotentialContradictionsRule(), method)(pages, new)
        assert _norm(new) == _norm(ref), method
