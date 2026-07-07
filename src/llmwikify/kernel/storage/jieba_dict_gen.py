"""Auto-generate jieba user dictionary from wiki content.

Three signals combined with weighted scoring:
A. Word frequency (jieba.cut → Counter)
B. TF-IDF keywords (jieba.analyse.extract_tags)
C. PMI collocations (bigram mutual information — slow)

Fast generation (A+B) runs every build_index.
Slow generation (C) runs on timer or manual ``llmwikify dict update --pmi``.
"""

import json
import logging
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jieba
import jieba.analyse

logger = logging.getLogger(__name__)

# Minimum PMI score for a bigram to be considered a valid collocation.
_PMI_MIN_COUNT = 3
_PMI_MIN_SCORE = 4.0

# Maximum terms per generation pass.
_MAX_FAST_TERMS = 500
_MAX_SLOW_TERMS = 300

# Minimum frequency for a term to be included.
_MIN_TERM_FREQ = 5

# Stop words to filter during generation (separate from jieba's own).
_STOP_WORDS: set[str] = set()
_stop_path = Path(__file__).parent / "jieba_stopwords.txt"
if _stop_path.exists():
    _STOP_WORDS = {
        line.strip()
        for line in _stop_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

# ── helpers ─────────────────────────────────────────────────────────


def _is_cjk_char(c: str) -> bool:
    return '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f'


def _is_cjk_word(word: str) -> bool:
    """True if the word contains at least one CJK character."""
    return any(_is_cjk_char(c) for c in word)


def _load_all_pages(db_path: Path) -> list[str]:
    """Return list of raw content from all indexed pages."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT content FROM pages_fts").fetchall()
        return [r[0] for r in rows if r[0]]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _merge_candidates(
    freq: Counter, tfidf: Counter, top_n: int = _MAX_FAST_TERMS
) -> list[tuple[str, int]]:
    """Weighted merge: TF-IDF × 2, frequency × 1."""
    scores: Counter = Counter()
    for word, f in freq.items():
        if f >= _MIN_TERM_FREQ and _is_cjk_word(word) and len(word) >= 2:
            if word not in _STOP_WORDS:
                scores[word] += f * 1.0
    for word, f in tfidf.items():
        if _is_cjk_word(word) and len(word) >= 2:
            if word not in _STOP_WORDS:
                scores[word] += f * 2.0
    return scores.most_common(top_n)


def _write_dict(path: Path, candidates: list[tuple[str, int]]) -> int:
    """Write jieba-format dict ``word\\tfreq\\tn``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for word, freq in candidates:
            if freq < 1:
                continue
            f.write(f"{word}\t{freq}\tn\n")
            count += 1
    return count


def _append_dict(path: Path, candidates: list[tuple[str, int]]) -> int:
    """Append to an existing jieba dict, skipping duplicates."""
    if not path.exists():
        return _write_dict(path, candidates)
    existing = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                existing.add(line.split("\t", 1)[0])
    count = 0
    with open(path, "a", encoding="utf-8") as f:
        for word, freq in candidates:
            if word not in existing and freq >= 1:
                f.write(f"{word}\t{freq}\tn\n")
                count += 1
    return count


def _write_meta(path: Path, fast_count: int, slow_count: int, page_count: int) -> None:
    """Write generation metadata JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fast_terms": fast_count,
        "slow_terms": slow_count,
        "page_count": page_count,
    }
    path.write_text(json.dumps(meta, indent=2))


def _should_run_slow(meta_path: Path, days: int = 7) -> bool:
    """True if slow generation should run (no meta or older than *days*)."""
    if not meta_path.exists():
        return True
    try:
        meta = json.loads(meta_path.read_text())
        gen_at = datetime.fromisoformat(meta.get("generated_at", ""))
        delta = datetime.now(timezone.utc) - gen_at
        return delta.days >= days
    except (ValueError, KeyError, OSError):
        return True


# ── Fast generation (A + B) ─────────────────────────────────────────


def generate_fast_dict(db_path: Path, output_path: Path) -> int:
    """Frequency (A) + TF-IDF (B) → write jieba dict.

    Returns number of terms written.
    """
    pages = _load_all_pages(db_path)
    if not pages:
        return 0

    freq: Counter = Counter()
    tfidf: Counter = Counter()

    for content in pages:
        for word in jieba.cut(content):
            freq[word] += 1
        for kw in jieba.analyse.extract_tags(content, topK=30):
            tfidf[kw] += 1

    candidates = _merge_candidates(freq, tfidf)
    return _write_dict(output_path, candidates)


# ── Slow generation (C — PMI) ───────────────────────────────────────


def _compute_pmi(
    pages: list[str],
    min_count: int = _PMI_MIN_COUNT,
    min_pmi: float = _PMI_MIN_SCORE,
) -> list[tuple[str, int]]:
    """Extract CJK bigrams with high Pointwise Mutual Information.

    Returns sorted list of ``(word, freq)``, highest PMI first.
    """
    unigram: Counter = Counter()
    bigram: Counter = Counter()

    for content in pages:
        chars = [c for c in content if _is_cjk_char(c)]
        unigram.update(chars)
        bigram.update(zip(chars, chars[1:], strict=False))

    total = sum(unigram.values())
    if total == 0:
        return []

    scored: list[tuple[str, int, float]] = []
    for (c1, c2), count in bigram.items():
        if count < min_count:
            continue
        p_c1c2 = count / total
        p_c1 = unigram[c1] / total
        p_c2 = unigram[c2] / total
        if p_c1 == 0 or p_c2 == 0:
            continue
        pmi = math.log2(p_c1c2 / (p_c1 * p_c2))
        if pmi >= min_pmi:
            scored.append((c1 + c2, count, pmi))

    scored.sort(key=lambda x: -x[2])
    return [(word, freq) for word, freq, _ in scored[:_MAX_SLOW_TERMS]]


def generate_slow_dict(db_path: Path, output_path: Path) -> int:
    """PMI (C) → append to jieba dict.

    Returns number of new terms added.
    """
    pages = _load_all_pages(db_path)
    if not pages:
        return 0
    candidates = _compute_pmi(pages)
    if not candidates:
        return 0
    return _append_dict(output_path, candidates)


# ── Entry point ─────────────────────────────────────────────────────


def generate_user_dict(db_path: Path, wiki_root: Path) -> dict[str, Any]:
    """Auto-generate custom jieba dictionary for a wiki.

    Called automatically at the end of ``build_index``.
    """
    meta_dir = wiki_root / ".wiki"
    meta_dir.mkdir(parents=True, exist_ok=True)

    fast_path = meta_dir / "jieba.dict"
    fast_count = generate_fast_dict(db_path, fast_path)

    slow_count = 0
    meta_path = meta_dir / "jieba.meta.json"
    if _should_run_slow(meta_path):
        pmi_path = meta_dir / "jieba.pmi.dict"
        slow_count = generate_slow_dict(db_path, pmi_path)

    page_count = 0
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT COUNT(*) FROM pages").fetchone()
            page_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass

    _write_meta(meta_path, fast_count, slow_count, page_count)

    logger.info(
        "Auto-generated jieba dict: %d fast + %d slow terms for %d pages",
        fast_count, slow_count, page_count,
    )

    return {"fast": fast_count, "slow": slow_count, "page_count": page_count}
