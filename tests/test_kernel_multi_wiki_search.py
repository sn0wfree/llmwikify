"""Unit tests for the shared multi-wiki search implementation.

Pure unit level: a fake registry, no server, no real Wiki objects.
Covers scope resolution and the single / multi / remote search branches.
"""

from types import SimpleNamespace

import pytest

from llmwikify.kernel.multi_wiki.instance import WikiType
from llmwikify.kernel.multi_wiki.search import resolve_scope, search_wikis


class FakeWiki:
    """Records the calls search_wikis makes against a local wiki."""

    def __init__(self, wiki_id: str, hits: int = 3):
        self.wiki_id = wiki_id
        self.hits = hits
        self.calls: list[tuple[str, int, str]] = []

    def search(self, query: str, limit: int = 10, backend: str = "fts5") -> list[dict]:
        self.calls.append((query, limit, backend))
        return [
            {"page_name": f"{self.wiki_id}-{i}", "score": 1.0, "snippet": "x"}
            for i in range(self.hits)
        ]


class FakeRegistry:
    """Minimal WikiRegistry stand-in for the search paths."""

    def __init__(self, ids: list[str], remote_ids: list[str] | None = None):
        self._instances = {
            i: SimpleNamespace(
                wiki_id=i,
                name=i.upper(),
                wiki_type=(
                    WikiType.REMOTE if i in (remote_ids or []) else WikiType.LOCAL
                ),
            )
            for i in ids
        }
        self._wikis = {i: FakeWiki(i) for i in ids}
        self._remote_clients: dict[str, object] = {}
        self.cross_calls: list[tuple[str, list[str], int, str]] = []

    def list_wikis(self):
        return list(self._instances.values())

    def get_wiki_instance(self, wiki_id: str):
        return self._instances[wiki_id]

    def get_wiki(self, wiki_id: str):
        return self._wikis[wiki_id]

    def cross_wiki_search(self, query, wiki_ids=None, limit=10, backend="fts5"):
        self.cross_calls.append((query, list(wiki_ids or []), limit, backend))
        return [
            {"page_name": f"{wid}-{i}", "score": 1.0, "snippet": "x"}
            for wid in (wiki_ids or [])
            for i in range(2)
        ]


# ── resolve_scope ────────────────────────────────────────────────


def test_resolve_scope_wiki_id_wins_over_wiki_ids():
    """The deprecated single-wiki argument takes precedence."""
    reg = FakeRegistry(["a", "b"])
    assert resolve_scope(reg, wiki_ids="b", wiki_id="a") == ["a"]


@pytest.mark.parametrize("value", [None, "", "*", "  *  "])
def test_resolve_scope_empty_means_all_wikis(value):
    """Omitted / empty / star scope covers every registered wiki."""
    reg = FakeRegistry(["a", "b", "c"])
    assert resolve_scope(reg, wiki_ids=value) == ["a", "b", "c"]


def test_resolve_scope_parses_comma_list_and_trims():
    reg = FakeRegistry(["a", "b", "c"])
    assert resolve_scope(reg, wiki_ids="a, c ") == ["a", "c"]


def test_resolve_scope_skips_unknown_ids():
    """Partially unknown scope keeps the known wikis."""
    reg = FakeRegistry(["a", "b"])
    assert resolve_scope(reg, wiki_ids="a,nosuch") == ["a"]


def test_resolve_scope_all_unknown_raises():
    reg = FakeRegistry(["a"])
    with pytest.raises(ValueError, match="Wiki not found"):
        resolve_scope(reg, wiki_ids="nosuch")


def test_resolve_scope_empty_registry_raises():
    with pytest.raises(ValueError, match="Wiki not found"):
        resolve_scope(FakeRegistry([]))


# ── search_wikis: single wiki ────────────────────────────────────


def test_single_wiki_branch_uses_backend_and_tags_origin():
    """One wiki in scope -> wiki.search with the requested backend."""
    reg = FakeRegistry(["a"])
    results, searched = search_wikis(reg, "q", 5, wiki_ids="a", backend="qmd")
    assert searched == ["a"]
    assert reg.get_wiki("a").calls == [("q", 5, "qmd")]
    # every result carries its origin wiki
    assert all(r["wiki_id"] == "a" and r["wiki_name"] == "A" for r in results)


def test_single_wiki_branch_respects_limit():
    reg = FakeRegistry(["a"])
    results, _ = search_wikis(reg, "q", 2, wiki_ids="a")
    assert len(results) == 2


def test_remote_wiki_branch_uses_the_remote_client():
    reg = FakeRegistry(["r"], remote_ids=["r"])
    reg._remote_clients["r"] = SimpleNamespace(
        search=lambda query, limit: [{"page_name": "remote-0", "score": 1.0}]
    )
    results, searched = search_wikis(reg, "q", 5, wiki_ids="r")
    assert searched == ["r"]
    assert results[0]["wiki_id"] == "r"


def test_remote_wiki_without_client_raises():
    reg = FakeRegistry(["r"], remote_ids=["r"])
    with pytest.raises(ValueError, match="Remote wiki client not available"):
        search_wikis(reg, "q", 5, wiki_ids="r")


# ── search_wikis: multiple wikis ─────────────────────────────────


def test_multi_wiki_branch_delegates_to_cross_search():
    """Several wikis in scope -> one cross-wiki call with the backend."""
    reg = FakeRegistry(["a", "b"])
    results, searched = search_wikis(reg, "q", 7, wiki_ids="a,b", backend="qmd")
    assert searched == ["a", "b"]
    assert reg.cross_calls == [("q", ["a", "b"], 7, "qmd")]
    assert len(results) == 4


def test_multi_wiki_branch_truncates_to_global_limit():
    """limit caps the merged set, not each wiki."""
    reg = FakeRegistry(["a", "b", "c"])
    results, _ = search_wikis(reg, "q", 3, wiki_ids="a,b,c")
    assert len(results) == 3


def test_multi_wiki_branch_passes_only_valid_ids():
    reg = FakeRegistry(["a", "b"])
    search_wikis(reg, "q", 5, wiki_ids="a,b,nosuch")
    assert reg.cross_calls[0][1] == ["a", "b"]


def test_one_valid_id_falls_back_to_the_single_wiki_branch():
    """A scope of one known wiki never goes through the cross-wiki path."""
    reg = FakeRegistry(["a", "b"])
    results, searched = search_wikis(reg, "q", 5, wiki_ids="a,nosuch")
    assert searched == ["a"]
    assert reg.cross_calls == []
    assert reg.get_wiki("a").calls == [("q", 5, "fts5")]
