"""Auto-generate jieba user dictionary from wiki content.

Three signals combined with weighted scoring:
A. Word frequency (jieba.cut → Counter)
B. TF-IDF keywords (jieba.analyse.extract_tags)
C. PMI collocations (bigram mutual information — slow)

Fast generation (A+B) runs on ``build_index`` — unless the page contents
are unchanged since the last run (content fingerprint in ``.wiki/jieba.meta.json``).
Slow generation (C) runs on timer or manual ``llmwikify dict update --pmi``.
"""

import hashlib
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
        for line in _stop_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

# ── helpers ─────────────────────────────────────────────────────────


def _is_cjk_char(c: str) -> bool:
    return "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f"


def _is_cjk_word(word: str) -> bool:
    """True if the word contains at least one CJK character."""
    return any(_is_cjk_char(c) for c in word)


def _has_cjk(content: str) -> bool:
    """True if the content contains any CJK character."""
    return any(_is_cjk_char(c) for c in content)


def _load_all_pages(db_path: Path) -> list[str]:
    """Return list of raw content from all indexed pages."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        rows = conn.execute("SELECT content FROM pages_fts").fetchall()
        return [r[0] for r in rows if r[0]]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _indexable_md_files(wiki_root: Path) -> list[Path]:
    """Markdown files that ``build_index_from_files`` would index."""
    from .backend import is_path_excluded

    if not wiki_root.exists():
        return []
    return sorted(p for p in wiki_root.rglob("*.md") if not is_path_excluded(p))


def _load_wiki_contents(wiki_root: Path, db_path: Path) -> list[str]:
    """Page contents feeding dictionary generation.

    Prefers the markdown files on disk — the same input
    ``build_index_from_files`` indexes — so the content fingerprint is
    independent of how far the DB lags behind disk. Reading the DB here
    would make ``build_index`` (which rebuilds the DB first) and a bare
    ``dict update`` disagree about the fingerprint and re-trigger each
    other's generation.

    Falls back to the DB when no indexable markdown exists (fixtures
    that seed only the index).
    """
    files = _indexable_md_files(wiki_root)
    if not files:
        return _load_all_pages(db_path)
    contents: list[str] = []
    for path in files:
        try:
            contents.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return contents


def _content_fingerprint(pages: list[str]) -> str:
    """Order-independent hash of the page contents.

    Both generation passes aggregate into a Counter, so the same
    multiset of contents always yields the same dictionary. Sorting
    makes the fingerprint match that invariance — ``SELECT`` order is
    not guaranteed stable across connections.
    """
    h = hashlib.sha256()
    for content in sorted(pages):
        h.update(content.encode("utf-8", "ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def _read_meta(path: Path) -> dict[str, Any]:
    """Read generation metadata, or ``{}`` when missing/corrupt."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


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
    with open(path, "w", encoding="utf-8", newline="\n") as f:
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
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for word, freq in candidates:
            if word not in existing and freq >= 1:
                f.write(f"{word}\t{freq}\tn\n")
                count += 1
    return count


def _write_meta(
    path: Path,
    fast_count: int,
    slow_count: int,
    page_count: int,
    fingerprint: str,
) -> None:
    """Write generation metadata JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fast_terms": fast_count,
        "slow_terms": slow_count,
        "page_count": page_count,
        "content_fingerprint": fingerprint,
    }
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")


def _should_run_slow(meta_path: Path, days: int = 7) -> bool:
    """True if slow generation should run (no meta or older than *days*)."""
    if not meta_path.exists():
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
    return _generate_fast_from_pages(_load_all_pages(db_path), output_path)


def _generate_fast_from_pages(pages: list[str], output_path: Path) -> int:
    if not pages:
        return 0

    freq: Counter = Counter()
    tfidf: Counter = Counter()

    for content in pages:
        # A Chinese segmentation dictionary has nothing to contribute from
        # pure-Latin content, and tokenising it is expensive: on a
        # 1400-page English wiki this pass took 19 s (jieba.analyse alone
        # triggered 42k jieba.calc calls). Chinese wikis are unaffected —
        # their pages still go through the full pass.
        if not _has_cjk(content):
            continue
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
    return _generate_slow_from_pages(_load_all_pages(db_path), output_path)


def _generate_slow_from_pages(pages: list[str], output_path: Path) -> int:
    if not pages:
        return 0
    candidates = _compute_pmi(pages)
    if not candidates:
        return 0
    return _append_dict(output_path, candidates)


# ── Entry point ─────────────────────────────────────────────────────


def generate_user_dict(db_path: Path, wiki_root: Path) -> dict[str, Any]:
    """Auto-generate custom jieba dictionary for a wiki.

    Called automatically at the end of ``build_index``. Input is the
    markdown on disk (same set ``build_index_from_files`` indexes), so
    the content fingerprint does not move when the DB is rebuilt.
    Both passes are a pure function of that content, so when it hashes
    to the same fingerprint as the last run the whole generation is
    skipped — on a 1400-page wiki the fast pass alone costs minutes.
    """
    meta_dir = wiki_root / ".wiki"
    meta_dir.mkdir(parents=True, exist_ok=True)

    fast_path = meta_dir / "jieba.dict"
    pmi_path = meta_dir / "jieba.pmi.dict"
    meta_path = meta_dir / "jieba.meta.json"

    pages = _load_wiki_contents(wiki_root, db_path)
    fingerprint = _content_fingerprint(pages)
    meta = _read_meta(meta_path)

    # Skip only when the outputs we would rewrite are still on disk.
    slow_ok = int(meta.get("slow_terms", 0) or 0) == 0 or pmi_path.exists()
    if fast_path.exists() and slow_ok and meta.get("content_fingerprint") == fingerprint:
        logger.info(
            "jieba dict up to date (fingerprint %s), skipping generation",
            fingerprint[:12],
        )
        return {
            "fast": int(meta.get("fast_terms", 0) or 0),
            "slow": int(meta.get("slow_terms", 0) or 0),
            "page_count": len(pages),
        }

    fast_count = _generate_fast_from_pages(pages, fast_path)

    slow_count = 0
    if _should_run_slow(meta_path):
        slow_count = _generate_slow_from_pages(pages, pmi_path)

    page_count = len(pages)
    _write_meta(meta_path, fast_count, slow_count, page_count, fingerprint)

    logger.info(
        "Auto-generated jieba dict: %d fast + %d slow terms for %d pages",
        fast_count,
        slow_count,
        page_count,
    )

    return {"fast": fast_count, "slow": slow_count, "page_count": page_count}
