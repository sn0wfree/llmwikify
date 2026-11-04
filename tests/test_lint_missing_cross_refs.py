"""Boundary tests for the missing_cross_ref lint rule.

Covers the layered-wiki cases the original tests missed: the existing
suite only used flat (root-level) pages, where the page name happened to
equal the title, so the rule looked healthy while it never fired on a
real ``wiki/concepts/`` layout.
"""

from __future__ import annotations

from llmwikify.kernel.wiki.lint.rules.missing_cross_refs import MissingCrossRefsRule


def _detect(pages: dict[str, str], wiki) -> list[dict]:
    """Run the rule over an explicit page map."""
    results: list[dict] = []
    MissingCrossRefsRule().detect_all(pages, wiki, results)
    return results


def test_detects_plain_title_mention_in_layered_wiki(wiki_instance):
    """Prose says "Foo" while the page is "concepts/Foo" — must be found."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")
    wiki_instance.write_page("sources/Baz", "# Baz\n\nAlso about Foo.\n")

    results = _detect(
        {
            "concepts/Foo": "# Foo\n\nContent.\n",
            "sources/Bar": "# Bar\n\nAbout Foo here.\n",
            "sources/Baz": "# Baz\n\nAlso about Foo.\n",
        },
        wiki_instance,
    )

    assert len(results) == 1
    assert results[0]["concept"] == "concepts/Foo"
    assert results[0]["concept_title"] == "Foo"
    assert set(results[0]["mentioning_pages"]) == {"sources/Bar", "sources/Baz"}


def test_detects_qualified_path_mention(wiki_instance):
    """Prose that spells out the path is a mention too."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nSee concepts/Foo.\n",
        "sources/Baz": "# Baz\n\nAlso concepts/Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert [r["concept"] for r in results] == ["concepts/Foo"]


def test_already_linked_title_form_not_flagged(wiki_instance):
    """``[[Foo]]`` counts as linked even though the page is concepts/Foo."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout [[Foo]] here.\n",
        "sources/Baz": "# Baz\n\nAlso about [[Foo]].\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_already_linked_qualified_form_not_flagged(wiki_instance):
    """``[[concepts/Foo]]`` counts as linked as well."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout [[concepts/Foo]] here.\n",
        "sources/Baz": "# Baz\n\nAlso about [[concepts/Foo]].\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_ambiguous_title_excluded(wiki_instance):
    """Two pages sharing a title: the bare title cannot identify one."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "entities/Foo": "# Foo\n\nOther content.\n",
        "sources/Bar": "# Bar\n\nAbout Foo here.\n",
        "sources/Baz": "# Baz\n\nAlso about Foo.\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_ambiguous_title_still_matches_qualified_path(wiki_instance):
    """With an ambiguous title, the qualified path still identifies a page."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "entities/Foo": "# Foo\n\nOther content.\n",
        "sources/Bar": "# Bar\n\nSee concepts/Foo.\n",
        "sources/Baz": "# Baz\n\nAlso concepts/Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert [r["concept"] for r in results] == ["concepts/Foo"]


def test_single_mention_below_threshold(wiki_instance):
    """One mentioning page is below MIN_MISSING_REF_COUNT."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nAbout Foo here.\n",
    }
    assert _detect(pages, wiki_instance) == []


def test_flat_pages_keep_legacy_behaviour(wiki_instance):
    """Root-level pages: page name == title, unchanged from before."""
    pages = {
        "Machine Learning": "# ML\n\nContent.\n",
        "AI Overview": "# AI\n\nMachine learning is a subset of AI.\n",
        "Data Science": "# DS\n\nMachine learning is used here.\n",
    }
    results = _detect(pages, wiki_instance)

    assert len(results) == 1
    assert results[0]["concept"] == "Machine Learning"
    assert results[0]["concept_title"] == "Machine Learning"


def test_self_page_not_reported(wiki_instance):
    """A page mentioning its own title is not a missing cross-ref."""
    pages = {
        "concepts/Foo": "# Foo\n\nFoo is a concept.\n",
        "sources/Bar": "# Bar\n\nAbout Foo.\n",
    }
    results = _detect(pages, wiki_instance)

    assert all(r["concept"] != "concepts/Foo" for r in results)


def test_title_inside_a_path_is_not_a_bare_mention(wiki_instance):
    """``concepts/Foo`` written as a path is a mention of the page, but
    must not be split into a bare title match."""
    pages = {
        "concepts/Foo": "# Foo\n\nContent.\n",
        "sources/Bar": "# Bar\n\nSee the concepts/Foo page.\n",
        "sources/Baz": "# Baz\n\nAlso the concepts/Foo page.\n",
    }
    results = _detect(pages, wiki_instance)

    # both pages write the path, so it IS a mention — but of the page,
    # not of a stray bare title.
    assert [r["concept"] for r in results] == ["concepts/Foo"]


def test_output_is_deterministic_under_hash_seed(tmp_path):
    """Same wiki must report the same gaps whatever the hash seed is.

    The title→page map used to be built from a set, so the winner for an
    ambiguous title varied with PYTHONHASHSEED and the rule reported a gap
    only on some runs.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[1] / "src"
    script = tmp_path / "determinism.py"
    script.write_text(
        "\n".join(
            [
                "import json, sys",
                f"sys.path.insert(0, {str(src_root)!r})",
                "from llmwikify.kernel.wiki.lint.rules.missing_cross_refs import (",
                "    MissingCrossRefsRule,",
                ")",
                "",
                "class W:",
                "    _index_page_name = 'index'",
                "    _log_page_name = 'log'",
                "",
                "    @staticmethod",
                "    def _parse_wikilink_target(link):",
                "        return link.split('|')[0].split('#')[0].strip()",
                "",
                "pages = {",
                "    'concepts/Risk Parity': '# Risk Parity\\n\\ncontent',",
                "    'sources/A': '# A\\n\\nRisk Parity here.',",
                "    'sources/B': '# B\\n\\nRisk Parity there.',",
                "    'concepts/Foo': '# Foo\\n\\nx',",
                "    'entities/Foo': '# Foo\\n\\ny',",
                "    'sources/C': '# C\\n\\nFoo here.',",
                "    'sources/D': '# D\\n\\nFoo there.',",
                "}",
                "res = []",
                "MissingCrossRefsRule().detect_all(pages, W(), res)",
                "print(json.dumps(sorted(r['concept'] for r in res)))",
            ]
        ),
        encoding="utf-8",
    )

    outcomes = set()
    for seed in ("0", "1", "2", "3", "4", "5", "6", "7"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            env=env,
        )
        lines = r.stdout.strip().splitlines()
        assert r.returncode == 0, r.stderr[-500:]
        outcomes.add(lines[-1])

    assert len(outcomes) == 1, outcomes
    assert outcomes == {'["concepts/Risk Parity"]'}


def test_large_wiki_scan_stays_fast(wiki_instance):
    """Guard the inverted index: a 1400-page wiki must scan in seconds.

    A per-page-per-candidate regex scan took minutes and hid the cost
    behind a substring precheck.
    """
    import time

    pages = {}
    for i in range(1400):
        pages[f"concepts/Page {i}"] = "x" * 20000 + f"\n\nPage {i} mentions Foo.\n"
    pages["concepts/Foo"] = "# Foo\n\n" + "y" * 20000

    t0 = time.monotonic()
    results = _detect(pages, wiki_instance)
    elapsed = time.monotonic() - t0

    # Wall-clock guard against an O(N²) scan regressing. Budget is
    # deliberately generous: the scan takes ~1.3s on 1400 pages here,
    # while a quadratic scan would take minutes — 30s still catches the
    # regression without failing on a slow or loaded CI machine.
    assert elapsed < 30.0, f"scan took {elapsed:.2f}s"
    assert [r["concept"] for r in results] == ["concepts/Foo"]
