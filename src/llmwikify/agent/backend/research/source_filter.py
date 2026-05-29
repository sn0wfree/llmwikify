"""Rule-based source pre-filter and quality scoring.

Filters out low-quality sources before analysis stage. No LLM calls.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SourceFilter:
    """Rule-based source pre-filter and quality scoring.

    Filters sources based on content length, URL patterns, and domain reputation.
    Computes a quality score (0.0-1.0) for each source.
    """

    HIGH_QUALITY_DOMAINS: set[str] = {
        "arxiv.org", "github.com", "nature.com", "science.org",
        "ieee.org", "acm.org", "wikipedia.org", "docs.python.org",
        "developer.mozilla.org", "stackoverflow.com",
        "pubmed.ncbi.nlm.nih.gov", "scholar.google.com",
        "en.wikipedia.org", "docs.rs", "pypi.org",
    }

    LOW_QUALITY_PATTERNS: list[str] = [
        "pinterest.com", "quora.com", "reddit.com/r/",
        "medium.com/@", "substack.com",
    ]

    NAV_PAGE_PATTERNS: list[str] = [
        "Home |", "Menu", "Skip to", "Loading...",
        "404", "Page Not Found", "Access Denied",
    ]

    NAV_CONTENT_KEYWORDS: list[str] = [
        "home", "about us", "contact", "privacy policy",
        "terms of service", "cookie policy",
    ]

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.min_content_length = config.get("source_min_content_length", 100)
        self.min_quality_score = config.get("source_min_quality_score", 0.3)
        self.enabled = config.get("source_filter_enabled", True)

    def filter_sources(
        self, sources: list[dict[str, Any]], query: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Filter sources, returning (kept, rejected).

        Rules (by priority):
        1. Content length < min_content_length -> reject
        2. Duplicate URL (normalized) -> reject (keep first)
        3. Navigation page (title matches NAV_PAGE_PATTERNS) -> reject
        4. Low quality score (< min_quality_score) -> reject
        """
        if not self.enabled:
            return sources, []

        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for source in sources:
            # Rule 1: Content too short
            content = source.get("content") or source.get("content_preview") or ""
            if len(content) < self.min_content_length:
                rejected.append(source)
                logger.debug("Source rejected: content too short (%d chars)", len(content))
                continue

            # Rule 2: Duplicate URL
            url = source.get("url", "")
            normalized = self._normalize_url(url)
            if normalized and normalized in seen_urls:
                rejected.append(source)
                logger.debug("Source rejected: duplicate URL %s", url)
                continue

            # Rule 3: Navigation page
            title = source.get("title", "")
            if self._is_nav_page(title, content):
                rejected.append(source)
                logger.debug("Source rejected: navigation page (%s)", title)
                continue

            # Rule 4: Low quality score
            score = self.compute_quality_score(source)
            source["_quality_score"] = score
            if score < self.min_quality_score:
                rejected.append(source)
                logger.debug("Source rejected: quality score %.2f < %.2f", score, self.min_quality_score)
                continue

            if normalized:
                seen_urls.add(normalized)
            kept.append(source)

        logger.info(
            "Source filter: %d kept, %d rejected (of %d total)",
            len(kept), len(rejected), len(sources),
        )
        return kept, rejected

    def compute_quality_score(self, source: dict[str, Any]) -> float:
        """Compute quality score (0.0-1.0) based on rules.

        Dimensions:
        - Domain authority: 0.3
        - Content length: 0.2
        - Content structure: 0.2
        - URL clarity: 0.15
        - Type match: 0.15
        """
        url = source.get("url", "")
        content = source.get("content") or source.get("content_preview") or ""
        source_type = source.get("source_type", "web")

        domain_score = self._score_domain(url)
        length_score = self._score_content_length(content)
        structure_score = self._score_content_structure(content)
        url_score = self._score_url_clarity(url)
        type_score = self._score_type_match(source_type)

        total = (
            domain_score * 0.3
            + length_score * 0.2
            + structure_score * 0.2
            + url_score * 0.15
            + type_score * 0.15
        )
        return round(min(1.0, max(0.0, total)), 3)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        url = url.rstrip("/").lower()
        for prefix in ("http://", "https://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        for param in ("?utm_source", "?ref", "?source", "&utm_source", "&ref"):
            idx = url.find(param)
            if idx >= 0:
                url = url[:idx]
        return url

    def _is_nav_page(self, title: str, content: str) -> bool:
        """Detect navigation pages."""
        title_lower = title.lower()
        for pattern in self.NAV_PAGE_PATTERNS:
            if pattern.lower() in title_lower:
                return True

        if content:
            words = content.lower().split()
            if len(words) > 0:
                nav_count = sum(1 for w in words if w in self.NAV_CONTENT_KEYWORDS)
                if nav_count / len(words) > 0.5:
                    return True
        return False

    def _score_domain(self, url: str) -> float:
        """Score domain authority (0.0-1.0)."""
        if not url:
            return 0.5
        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return 0.5

        hostname = hostname.lower().replace("www.", "")

        for domain in self.HIGH_QUALITY_DOMAINS:
            if hostname == domain or hostname.endswith("." + domain):
                return 1.0

        for pattern in self.LOW_QUALITY_PATTERNS:
            if pattern in hostname:
                return 0.2

        return 0.5

    def _score_content_length(self, content: str) -> float:
        """Score content length (0.0-1.0)."""
        length = len(content)
        if length >= 2000:
            return 1.0
        elif length >= 1000:
            return 0.8
        elif length >= 500:
            return 0.6
        elif length >= 200:
            return 0.4
        elif length >= 100:
            return 0.2
        return 0.0

    def _score_content_structure(self, content: str) -> float:
        """Score content structure (0.0-1.0)."""
        if not content:
            return 0.0

        score = 0.0
        lines = content.split("\n")

        has_headings = any(line.strip().startswith("#") for line in lines)
        if has_headings:
            score += 0.3

        has_lists = any(line.strip().startswith(("-", "*", "1.")) for line in lines)
        if has_lists:
            score += 0.2

        para_count = sum(1 for line in lines if 50 < len(line.strip()) < 500)
        if para_count >= 3:
            score += 0.3
        elif para_count >= 1:
            score += 0.15

        if len(lines) > 5:
            score += 0.2

        return min(1.0, score)

    def _score_url_clarity(self, url: str) -> float:
        """Score URL clarity (0.0-1.0)."""
        if not url:
            return 0.3
        try:
            parsed = urlparse(url)
        except Exception:
            return 0.3

        score = 1.0

        if len(parsed.query) > 100:
            score -= 0.3
        elif len(parsed.query) > 50:
            score -= 0.15

        tracking_params = ("utm_", "ref=", "source=", "fbclid=", "gclid=")
        for param in tracking_params:
            if param in parsed.query:
                score -= 0.2
                break

        if len(parsed.path) > 200:
            score -= 0.2

        return max(0.0, score)

    def _score_type_match(self, source_type: str) -> float:
        """Score source type match (0.0-1.0)."""
        scores = {
            "wiki": 1.0,
            "pdf": 0.9,
            "arxiv": 0.9,
            "web": 0.6,
            "youtube": 0.5,
        }
        return scores.get(source_type, 0.5)
