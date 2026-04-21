"""Shared constants for llmwikify core modules."""

# Common English stop words used for keyword extraction and similarity matching.
# Used by: WikiAnalyzer._detect_query_page_overlap, WikiQueryMixin._find_similar_query_page
STOP_WORDS: frozenset[str] = frozenset({
    "what", "is", "the", "a", "an", "how", "do", "does", "why",
    "can", "could", "would", "should", "will", "did", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "of", "to",
    "in", "for", "on", "with", "at", "by", "from", "and", "or", "not",
    "but", "if", "then", "than", "so", "as", "about", "compare",
    "what's", "how's", "tell", "me", "explain",
})

# Thresholds for query similarity matching
SIMILARITY_THRESHOLD: float = 0.3
MIN_KEYWORD_LENGTH: int = 3

# Thresholds for lint detection
JACCARD_OVERLAP_THRESHOLD: float = 0.85
MIN_MISSING_REF_COUNT: int = 2
MAX_DATED_CLAIM_HINTS: int = 3
MAX_QUERY_OVERLAP_HINTS: int = 2
MAX_CROSS_REF_HINTS: int = 3
MAX_CONTRADICTIONS: int = 3
MIN_ASSERTION_LENGTH: int = 21
MIN_ASSERTIONS_FOR_GAP: int = 3
OUTDATED_YEAR_GAP: int = 2
YEAR_GAP_THRESHOLD: int = 3
MIN_YEAR_THRESHOLD: int = 2018

# Display limits
MAX_MISSING_DISPLAY: int = 5
MAX_SUMMARY_ITEMS: int = 5
MAX_KEY_TOPICS: int = 5
MAX_QUERY_TOPIC_LENGTH: int = 50
MAX_CONTENT_CHARS: int = 8000
HASH_TRUNCATE_LENGTH: int = 16
MAX_SUGGESTED_UPDATES: int = 10

# Page count thresholds for hints
SMALL_WIKI_THRESHOLD: int = 5
GROWING_WIKI_THRESHOLD: int = 20

# Claim/contradiction overlap thresholds (synthesis engine)
CLAIM_OVERLAP_THRESHOLD: float = 0.4
CONTRADICTION_OVERLAP_THRESHOLD: float = 0.5
