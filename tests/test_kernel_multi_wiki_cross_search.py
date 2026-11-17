"""Unit tests for ``WikiRegistry.cross_wiki_search``.

Covers the pieces the search merge depends on: backend passthrough,
merge + score ordering, unknown-id skipping, per-wiki failure tolerance
and the remote-wiki branch. Wikis are stubbed via ``get_wiki`` so the
tests stay at the registry layer.
"""

from types import SimpleNamespace

from llmwikify.kernel.multi_wiki.instance import WikiType
from llmwikify.kernel.multi_wiki.registry import WikiRegistry


class StubWiki:
    """Local wiki double that records what search was asked for."""

    def __init__(self, hits: list[tuple[str, float]], boom: bool = False):
        self.hits = hits
        self.boom = boom
        self.calls: list[tuple[str, int, str]] = []

    def search(self, query, limit=10, backend="fts5"):
        self.calls.append((query, limit, backend))
        if self.boom:
            raise RuntimeError("wiki is broken")
        return [
            {"page_name": name, "score": score, "snippet": "x"}
            for name, score in self.hits[:limit]
        ]


def make_registry(tmp_path, ids: list[str], *, remote_ids: list[str] | None = None):
    """Build a real WikiRegistry whose local wikis are stubs."""
    registry = WikiRegistry({})
    for i in ids:
        registry.register_wiki(
            i, i.upper(), tmp_path / i, is_default=(i == ids[0])
        )
    stubs: dict[str, StubWiki] = {}
    for i in ids:
        if i in (remote_ids or []):
            registry._instances[i].wiki_type = WikiType.REMOTE
        else:
            stubs[i] = StubWiki(
                hits=[(f"{i}-high", 9.0), (f"{i}-low", 1.0), (f"{i}-mid", 5.0)]
            )
    registry.get_wiki = lambda wid: stubs[wid]  # type: ignore[method-assign]
    return registry, stubs


def test_forwards_backend_to_every_local_wiki(tmp_path):
    registry, stubs = make_registry(tmp_path, ["a", "b"])
    registry.cross_wiki_search("q", None, 5, backend="qmd")
    for stub in stubs.values():
        assert stub.calls == [("q", 5, "qmd")]


def test_defaults_to_fts5_backend(tmp_path):
    registry, stubs = make_registry(tmp_path, ["a"])
    registry.cross_wiki_search("q", ["a"], 5)
    assert stubs["a"].calls == [("q", 5, "fts5")]


def test_merges_results_and_sorts_by_score_desc(tmp_path):
    registry, _ = make_registry(tmp_path, ["a", "b"])
    results = registry.cross_wiki_search("q", None, 5)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9.0
    assert scores[-1] == 1.0


def test_each_result_is_tagged_with_its_origin_wiki(tmp_path):
    registry, _ = make_registry(tmp_path, ["a", "b"])
    for r in registry.cross_wiki_search("q", None, 5):
        assert r["wiki_id"] in {"a", "b"}
        assert r["wiki_name"] in {"A", "B"}


def test_unknown_wiki_ids_are_skipped(tmp_path):
    registry, stubs = make_registry(tmp_path, ["a"])
    results = registry.cross_wiki_search("q", ["a", "nosuch"], 5)
    assert {r["wiki_id"] for r in results} == {"a"}
    assert stubs["a"].calls  # a was still searched


def test_one_broken_wiki_does_not_abort_the_others(tmp_path):
    """Per-wiki failures are logged and skipped, not raised."""
    registry, stubs = make_registry(tmp_path, ["a", "b"])
    stubs["a"].boom = True
    results = registry.cross_wiki_search("q", None, 5)
    assert {r["wiki_id"] for r in results} == {"b"}


def test_remote_wiki_is_searched_through_its_client(tmp_path):
    registry, _ = make_registry(tmp_path, ["a", "r"], remote_ids=["r"])
    registry._remote_clients["r"] = SimpleNamespace(
        search=lambda query, limit: [{"page_name": "remote", "score": 7.0}]
    )
    results = registry.cross_wiki_search("q", ["r"], 5)
    assert results[0]["wiki_id"] == "r"
    assert results[0]["wiki_name"] == "R"


def test_remote_wiki_without_client_yields_nothing(tmp_path):
    registry, _ = make_registry(tmp_path, ["r"], remote_ids=["r"])
    assert registry.cross_wiki_search("q", ["r"], 5) == []


def test_limit_is_per_wiki_at_this_layer(tmp_path):
    """The registry layer fetches ``limit`` per wiki; the cap to a global
    budget belongs to ``kernel.multi_wiki.search.search_wikis``."""
    registry, _ = make_registry(tmp_path, ["a", "b"])
    assert len(registry.cross_wiki_search("q", None, 1)) == 2
