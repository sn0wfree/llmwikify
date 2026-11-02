"""Unit tests for the small CLI command dispatchers.

Covers: dict / read_page / search / report / status / sink_status /
log / help / fix_wikilinks / export_graph / community_detect /
build_index / write_page / synthesize / suggest_synthesis.

Each command is a thin wrapper over a Wiki method — driven with fake
wiki objects. Boundary modules (graph.export, jieba_dict_gen) are
monkeypatched where they would touch disk or heavy deps.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.build_index import (
    BuildIndexCommand,
    _detect_old_index_format,
    run_build_index,
)
from llmwikify.interfaces.cli.commands.community_detect import (
    CommunityDetectCommand,
    run_community_detect,
)
from llmwikify.interfaces.cli.commands.dict_cmd import DictCommand, run_dict
from llmwikify.interfaces.cli.commands.export_graph import (
    ExportGraphCommand,
    run_export_graph,
)
from llmwikify.interfaces.cli.commands.fix_wikilinks import (
    FixWikilinksCommand,
    run_fix_wikilinks,
)
from llmwikify.interfaces.cli.commands.help_cmd import (
    SUBCOMMAND_ALIASES,
    HelpCommand,
)
from llmwikify.interfaces.cli.commands.log_cmd import LogCommand, run_log
from llmwikify.interfaces.cli.commands.read_page import (
    ReadPageCommand,
    run_read_page,
)
from llmwikify.interfaces.cli.commands.report import ReportCommand, run_report
from llmwikify.interfaces.cli.commands.search import SearchCommand, run_search
from llmwikify.interfaces.cli.commands.sink_status import (
    SinkStatusCommand,
    run_sink_status,
)
from llmwikify.interfaces.cli.commands.status import StatusCommand, run_status
from llmwikify.interfaces.cli.commands.suggest_synthesis import (
    SuggestSynthesisCommand,
    run_suggest_synthesis,
)
from llmwikify.interfaces.cli.commands.synthesize import (
    SynthesizeCommand,
    run_synthesize,
)
from llmwikify.interfaces.cli.commands.write_page import (
    WritePageCommand,
    _get_content,
    run_write_page,
)


class FakeWiki:
    """A grab-bag fake exposing every method these commands call."""

    def __init__(self, **kw: Any):
        self.__dict__.update(kw)
        self.calls: list[tuple] = []

    def _record(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))


def _ns(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**kw)


# ══════════════════════════════════════════════════════════════════
# read_page
# ══════════════════════════════════════════════════════════════════


def test_read_page_ok(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(read_page=lambda name, page_type=None: {"content": "HELLO"})
    assert run_read_page(wiki, _ns(name="foo")) == 0
    assert "HELLO" in capsys.readouterr().out


def test_read_page_error(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(read_page=lambda name, page_type=None: {"error": "not found"})
    assert run_read_page(wiki, _ns(name="foo")) == 1
    assert "not found" in capsys.readouterr().out


def test_read_page_passes_type() -> None:
    captured: dict = {}

    def rp(name: str, page_type: str | None = None) -> dict:
        captured["name"] = name
        captured["type"] = page_type
        return {"content": "x"}

    wiki = FakeWiki(read_page=rp)
    run_read_page(wiki, _ns(name="p", type="concept"))
    assert captured == {"name": "p", "type": "concept"}


def test_read_page_no_type_attr() -> None:
    captured: dict = {}

    def rp(name: str, page_type: str | None = None) -> dict:
        captured["type"] = page_type
        return {"content": "x"}

    run_read_page(FakeWiki(read_page=rp), _ns(name="p"))
    assert captured["type"] is None


# ══════════════════════════════════════════════════════════════════
# search
# ══════════════════════════════════════════════════════════════════


def test_search_no_results(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(search=lambda q, lim, backend="": [])
    assert run_search(wiki, _ns(query="zzz")) == 0
    assert "No results found for: zzz" in capsys.readouterr().out


def test_search_with_results(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        search=lambda q, lim, backend="": [
            {"page_name": "a", "score": 0.9, "snippet": "s", "mode": "qmd"},
            {"page_name": "b", "score": 0.5, "snippet": "t"},
        ]
    )
    assert run_search(wiki, _ns(query="hello", limit=5, backend="qmd")) == 0
    out = capsys.readouterr().out
    assert "Search results for: hello" in out
    assert "Using backend: qmd" in out
    assert "1. a" in out and "2. b" in out


def test_search_defaults() -> None:
    captured: dict = {}

    def s(q, lim, backend=""):
        captured.update(q=q, lim=lim, backend=backend)
        return []

    run_search(FakeWiki(search=s), _ns(query="q"))
    assert captured == {"q": "q", "lim": 10, "backend": "fts5"}


# ══════════════════════════════════════════════════════════════════
# status
# ══════════════════════════════════════════════════════════════════


def test_status_ok(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        status=lambda: {
            "initialized": True,
            "root": "/w",
            "page_count": 10,
            "source_count": 3,
            "indexed_pages": 8,
            "total_links": 42,
        }
    )
    assert run_status(wiki, _ns()) == 0
    out = capsys.readouterr().out
    assert "Wiki Status" in out
    assert "Root: /w" in out
    assert "Pages: 10" in out
    assert "Sources: 3" in out
    assert "Indexed: 8" in out
    assert "Links: 42" in out


def test_status_not_initialized(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(status=lambda: {"initialized": False})
    assert run_status(wiki, _ns()) == 1
    assert "not initialized" in capsys.readouterr().out


def test_status_missing_optional_keys(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        status=lambda: {"initialized": True, "root": "/w", "page_count": 1, "source_count": 0}
    )
    assert run_status(wiki, _ns()) == 0
    out = capsys.readouterr().out
    assert "Indexed: N/A" in out
    assert "Links: N/A" in out


# ══════════════════════════════════════════════════════════════════
# sink_status
# ══════════════════════════════════════════════════════════════════


def test_sink_status(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(sink_status=lambda: {"buffered": 2})
    assert run_sink_status(wiki, _ns()) == 0
    assert "Sink status" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════
# log
# ══════════════════════════════════════════════════════════════════


def test_log_positional(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(append_log=lambda op, desc: f"logged {op}")
    args = _ns(operation="ingest", description="file.md", op_flag=None, details=None)
    assert run_log(wiki, args) == 0
    assert "logged ingest" in capsys.readouterr().out


def test_log_flag_wins(capsys: pytest.CaptureFixture) -> None:
    captured: dict = {}

    def al(op: str, desc: str) -> str:
        captured.update(op=op, desc=desc)
        return "ok"

    wiki = FakeWiki(append_log=al)
    args = _ns(operation=None, description=None, op_flag="flag-op", details="flag-desc")
    assert run_log(wiki, args) == 0
    assert captured == {"op": "flag-op", "desc": "flag-desc"}


def test_log_missing_both(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(append_log=lambda op, desc: "x")
    args = _ns(operation=None, description=None, op_flag=None, details=None)
    assert run_log(wiki, args) == 1
    out = capsys.readouterr().out
    assert "operation and description required" in out
    assert "Usage:" in out


def test_log_missing_description_only(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(append_log=lambda op, desc: "x")
    args = _ns(operation="op", description=None, op_flag=None, details=None)
    assert run_log(wiki, args) == 1


# ══════════════════════════════════════════════════════════════════
# help
# ══════════════════════════════════════════════════════════════════


def test_help_full(capsys: pytest.CaptureFixture) -> None:
    cmd = HelpCommand()
    assert cmd.run(_ns(aliases=False), None, {}) == 0
    out = capsys.readouterr().out
    assert "Available commands:" in out


def test_help_aliases_only_empty(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmwikify.interfaces.cli.commands import help_cmd as hc

    monkeypatch.setattr(hc, "SUBCOMMAND_ALIASES", {})
    cmd = HelpCommand()
    assert cmd.run(_ns(aliases=True), None, {}) == 0
    assert "No subcommand aliases registered" in capsys.readouterr().out


def test_help_aliases_only_with_entries(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmwikify.interfaces.cli.commands import help_cmd as hc

    monkeypatch.setattr(hc, "SUBCOMMAND_ALIASES", {"mcp": "serve"})
    cmd = HelpCommand()
    assert cmd.run(_ns(aliases=True), None, {}) == 0
    out = capsys.readouterr().out
    assert "mcp" in out and "serve" in out


def test_help_full_includes_aliases(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmwikify.interfaces.cli.commands import help_cmd as hc

    monkeypatch.setattr(hc, "SUBCOMMAND_ALIASES", {"mcp": "serve"})
    HelpCommand().run(_ns(aliases=False), None, {})
    out = capsys.readouterr().out
    assert "Subcommand aliases" in out


def test_help_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    HelpCommand().setup_parser(sub)
    ns = parser.parse_args(["help", "--aliases"])
    assert ns.aliases is True


# ══════════════════════════════════════════════════════════════════
# fix_wikilinks
# ══════════════════════════════════════════════════════════════════


def _fix_result(**kw: Any) -> dict:
    d = {"fixed": 0, "skipped": 0, "ambiguous": 0, "changes": []}
    d.update(kw)
    return d


def test_fix_wikilinks_clean(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(fix_wikilinks=lambda dry_run=False: _fix_result())
    assert run_fix_wikilinks(wiki, _ns(dry_run=False)) == 0
    out = capsys.readouterr().out
    assert "FIXED" in out
    assert "Fixed:     0" in out


def test_fix_wikilinks_dry_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(fix_wikilinks=lambda dry_run=False: _fix_result())
    run_fix_wikilinks(wiki, _ns(dry_run=True))
    assert "DRY RUN" in capsys.readouterr().out


def test_fix_wikilinks_with_changes(capsys: pytest.CaptureFixture) -> None:
    result = _fix_result(
        fixed=2,
        changes=[
            {"status": "fixed", "page": "a", "old": "[[x]]", "new": "[[c/x]]"},
            {
                "status": "ambiguous",
                "page": "b",
                "link": "y",
                "matches": ["p1", "p2"],
            },
        ],
    )
    wiki = FakeWiki(fix_wikilinks=lambda dry_run=False: result)
    assert run_fix_wikilinks(wiki, _ns(dry_run=False)) == 0
    out = capsys.readouterr().out
    assert "Changes (2 total):" in out
    assert "c/x" in out
    assert "matches 2 pages" in out


def test_fix_wikilinks_ambiguous_returns_1(capsys: pytest.CaptureFixture) -> None:
    result = _fix_result(ambiguous=1, changes=[{"status": "ambiguous", "page": "b", "link": "y", "matches": ["p"]}])
    wiki = FakeWiki(fix_wikilinks=lambda dry_run=False: result)
    assert run_fix_wikilinks(wiki, _ns()) == 1
    assert "require manual resolution" in capsys.readouterr().out


def test_fix_wikilinks_changes_over_50(capsys: pytest.CaptureFixture) -> None:
    changes = [{"status": "fixed", "page": f"p{i}", "old": "o", "new": "n"} for i in range(60)]
    wiki = FakeWiki(fix_wikilinks=lambda dry_run=False: _fix_result(fixed=60, changes=changes))
    run_fix_wikilinks(wiki, _ns())
    out = capsys.readouterr().out
    assert "Changes (60 total):" in out
    assert out.count("✅") == 50


# ══════════════════════════════════════════════════════════════════
# write_page
# ══════════════════════════════════════════════════════════════════


def test_write_page_from_content(capsys: pytest.CaptureFixture) -> None:
    captured: dict = {}

    def wp(name: str, content: str, page_type=None) -> str:
        captured.update(name=name, content=content, page_type=page_type)
        return "written"

    wiki = FakeWiki(write_page=wp)
    args = _ns(name="foo", content="BODY", file=None, type=None)
    assert run_write_page(wiki, args) == 0
    assert captured == {"name": "foo", "content": "BODY", "page_type": None}
    assert "written" in capsys.readouterr().out


def test_write_page_from_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    f = tmp_path / "in.md"
    f.write_text("FILE CONTENT", encoding="utf-8")
    captured: dict = {}

    def wp(name, content, page_type=None):
        captured["content"] = content
        return "ok"

    wiki = FakeWiki(write_page=wp)
    args = _ns(name="foo", content=None, file=str(f), type="concept")
    assert run_write_page(wiki, args) == 0
    assert captured["content"] == "FILE CONTENT"


def test_write_page_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(write_page=lambda *a, **k: "x")
    args = _ns(name="foo", content=None, file=str(tmp_path / "nope.md"))
    assert run_write_page(wiki, args) == 1
    assert "Error reading file" in capsys.readouterr().out


def test_write_page_no_content(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    wiki = FakeWiki(write_page=lambda *a, **k: "x")
    args = _ns(name="foo", content=None, file=None)
    assert run_write_page(wiki, args) == 1
    assert "No content provided" in capsys.readouterr().out


def test_get_content_priority_file_over_content(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    f.write_text("from-file", encoding="utf-8")
    args = _ns(file=str(f), content="from-arg")
    assert _get_content(args) == "from-file"


def test_get_content_no_attrs(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("from-stdin"))
    assert _get_content(_ns()) == "from-stdin"


# ══════════════════════════════════════════════════════════════════
# synthesize
# ══════════════════════════════════════════════════════════════════


def _syn_args(**kw: Any) -> argparse.Namespace:
    d = {
        "query": "q",
        "answer": "a",
        "page_name": "p",
        "sources": None,
        "raw_sources": None,
        "mode": "sink",
        "no_auto_link": False,
        "no_auto_log": False,
    }
    d.update(kw)
    return argparse.Namespace(**d)


def test_synthesize_ok(capsys: pytest.CaptureFixture) -> None:
    captured: dict = {}

    def sq(**kwargs: Any) -> dict:
        captured.update(kwargs)
        return {"page_name": "saved"}

    wiki = FakeWiki(synthesize_query=sq)
    assert run_synthesize(wiki, _syn_args(sources=["s1"], raw_sources=["r1"])) == 0
    assert captured["query"] == "q"
    assert captured["answer"] == "a"
    assert captured["source_pages"] == ["s1"]
    assert captured["raw_sources"] == ["r1"]
    assert captured["auto_link"] is True
    assert captured["auto_log"] is True
    assert captured["mode"] == "sink"
    assert "Synthesized: saved" in capsys.readouterr().out


def test_synthesize_no_auto_flags() -> None:
    captured: dict = {}

    def sq(**kwargs: Any) -> dict:
        captured.update(kwargs)
        return {}

    run_synthesize(
        FakeWiki(synthesize_query=sq),
        _syn_args(no_auto_link=True, no_auto_log=True),
    )
    assert captured["auto_link"] is False
    assert captured["auto_log"] is False


def test_synthesize_error(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(synthesize_query=lambda **k: {"error": "dup"})
    assert run_synthesize(wiki, _syn_args()) == 1
    assert "dup" in capsys.readouterr().out


def test_synthesize_empty_answer(
    capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    # answer="" falls through to stdin; make stdin empty too
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    wiki = FakeWiki(synthesize_query=lambda **k: {})
    assert run_synthesize(wiki, _syn_args(answer="")) == 1
    assert "No answer content" in capsys.readouterr().out


def test_synthesize_defaults_for_missing_attrs() -> None:
    captured: dict = {}

    def sq(**kwargs: Any) -> dict:
        captured.update(kwargs)
        return {}

    # Minimal ns: only required fields; getattr defaults for the rest
    args = _ns(query="q", answer="a", page_name=None, sources=None, mode="sink")
    # raw_sources / no_auto_link / no_auto_log missing → getattr defaults
    run_synthesize(FakeWiki(synthesize_query=sq), args)
    assert captured["raw_sources"] == []
    assert captured["auto_link"] is True
    assert captured["auto_log"] is True


# ══════════════════════════════════════════════════════════════════
# suggest_synthesis
# ══════════════════════════════════════════════════════════════════


def test_suggest_json(capsys: pytest.CaptureFixture) -> None:
    payload = {"sources_analyzed": 1, "total_suggestions": 0, "suggestions": [], "summary": "s"}
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: payload)
    assert run_suggest_synthesis(wiki, _ns(source=None, json=True)) == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_suggest_error(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: {"error": "bad"})
    assert run_suggest_synthesis(wiki, _ns(source=None, json=False)) == 1
    assert "bad" in capsys.readouterr().out


def test_suggest_text_full(capsys: pytest.CaptureFixture) -> None:
    payload = {
        "sources_analyzed": 2,
        "total_suggestions": 1,
        "summary": "done",
        "suggestions": [
            {
                "source_name": "src1",
                "reinforced_claims": [{"claim": "C" * 100, "confirmed_by_count": 2}],
                "new_contradictions": [{"contradiction": "X" * 100}],
                "knowledge_gaps": [{"gap": "G" * 100}],
                "suggested_updates": [{"page": "p", "reason": "R" * 100}],
                "new_entities": [{"name": "E", "type": "concept"}],
            }
        ],
    }
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: payload)
    assert run_suggest_synthesis(wiki, _ns(source="s", json=False)) == 0
    out = capsys.readouterr().out
    assert "Cross-Source Synthesis Suggestions" in out
    assert "Sources analyzed: 2" in out
    assert "Reinforced Claims (1)" in out
    assert "Potential Contradictions (1)" in out
    assert "Knowledge Gaps (1)" in out
    assert "Suggested Updates (1)" in out
    assert "New Entities (1)" in out
    assert "done" in out


def test_suggest_text_optional_sections_absent(capsys: pytest.CaptureFixture) -> None:
    payload = {
        "sources_analyzed": 0,
        "total_suggestions": 0,
        "summary": "none",
        "suggestions": [{"source_name": "s"}],
    }
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: payload)
    run_suggest_synthesis(wiki, _ns(source=None, json=False))
    out = capsys.readouterr().out
    assert "Reinforced Claims" not in out
    assert "Potential Contradictions" not in out


def test_suggest_contradiction_falls_back_to_new_claim(capsys: pytest.CaptureFixture) -> None:
    payload = {
        "sources_analyzed": 1,
        "total_suggestions": 1,
        "summary": "s",
        "suggestions": [
            {
                "source_name": "s",
                "new_contradictions": [{"new_claim": "NEW"}],
            }
        ],
    }
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: payload)
    run_suggest_synthesis(wiki, _ns(source=None, json=False))
    assert "NEW" in capsys.readouterr().out


def test_suggest_defaults_when_attrs_missing() -> None:
    payload = {"sources_analyzed": 0, "total_suggestions": 0, "suggestions": [], "summary": ""}
    wiki = FakeWiki(suggest_synthesis=lambda source_name=None: payload)
    assert run_suggest_synthesis(wiki, _ns()) == 0


# ══════════════════════════════════════════════════════════════════
# build_index
# ══════════════════════════════════════════════════════════════════


def test_build_index_export_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out_file = tmp_path / "idx.json"
    captured: dict = {}

    def ei(path):
        captured["path"] = path
        return {"total_pages": 5, "total_links": 9}

    wiki = FakeWiki(
        export_index=ei,
        ref_index_path=tmp_path / "default.json",
    )
    args = _ns(no_export=False, output=str(out_file), export_only=True, force=False)
    assert run_build_index(wiki, args) == 0
    assert captured["path"] == out_file
    out = capsys.readouterr().out
    assert "Export Complete" in out
    assert "Pages: 5" in out


def test_build_index_export_only_default_path(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    default = tmp_path / "default.json"
    captured: dict = {}
    wiki = FakeWiki(
        export_index=lambda p: captured.update(path=p) or {"total_pages": 1, "total_links": 1},
        ref_index_path=default,
    )
    args = _ns(output=None, export_only=True, no_export=False, force=False)
    assert run_build_index(wiki, args) == 0
    assert captured["path"] == default


def test_build_index_full(capsys: pytest.CaptureFixture) -> None:
    captured: dict = {}

    def bi(auto_export=True, output_path=None):
        captured.update(auto_export=auto_export, output_path=output_path)
        return {
            "total_pages": 10,
            "total_links": 20,
            "elapsed_seconds": 1.5,
            "files_per_second": 6.7,
        }

    wiki = FakeWiki(
        build_index=bi,
        is_initialized=lambda: False,
        wiki_dir=Path("/w/wiki"),
    )
    args = _ns(no_export=True, output=None, export_only=False, force=False)
    assert run_build_index(wiki, args) == 0
    assert captured["auto_export"] is False
    out = capsys.readouterr().out
    assert "Index Built" in out
    assert "Total pages: 10" in out
    assert "Elapsed: 1.5s" in out


def test_build_index_old_format_warning(capsys: pytest.CaptureFixture) -> None:
    # is_initialized True + index returning mismatched page_name → old format
    class Cur:
        def fetchall(self):
            return [{"page_name": "Bare", "file_path": "dir/Bare.md"}]

    class Conn:
        def execute(self, sql):
            return Cur()

    wiki = FakeWiki(
        build_index=lambda **k: {
            "total_pages": 1,
            "total_links": 0,
            "elapsed_seconds": 0,
            "files_per_second": 0,
        },
        is_initialized=lambda: True,
        index=SimpleNS(conn=Conn()),
        wiki_dir=Path("/w"),
    )
    args = _ns(no_export=False, output=None, export_only=False, force=False)
    assert run_build_index(wiki, args) == 0
    assert "Old index format detected" in capsys.readouterr().out


def test_detect_old_index_not_initialized() -> None:
    wiki = FakeWiki(is_initialized=lambda: False)
    assert _detect_old_index_format(wiki) is False


def test_detect_old_index_new_format() -> None:
    class Cur:
        def fetchall(self):
            return [{"page_name": "dir/Bare", "file_path": "dir/Bare.md"}]

    class Conn:
        def execute(self, sql):
            return Cur()

    wiki = FakeWiki(is_initialized=lambda: True, index=SimpleNS(conn=Conn()))
    assert _detect_old_index_format(wiki) is False


def test_detect_old_index_exception() -> None:
    class Conn:
        def execute(self, sql):
            raise RuntimeError("db locked")

    wiki = FakeWiki(is_initialized=lambda: True, index=SimpleNS(conn=Conn()))
    assert _detect_old_index_format(wiki) is False


class SimpleNS:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


# ══════════════════════════════════════════════════════════════════
# report / export_graph / community_detect  (graph.export boundary)
# ══════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_graph_export(monkeypatch: pytest.MonkeyPatch) -> dict:
    import llmwikify.kernel.graph.export as ge

    state: dict[str, Any] = {
        "detect": None,
        "generate": None,
        "build": None,
        "html": None,
        "svg": None,
        "graphml": None,
        "exc": None,
    }

    def fake_detect(index, algorithm="leiden", resolution=1.0):
        if state["exc"]:
            raise state["exc"]
        return state["detect"] or {}

    def fake_generate(index, communities, top_n=10):
        return state["generate"] or "REPORT TEXT"

    def fake_build(index):
        return "GRAPH"

    def fake_html(graph, communities, path, min_degree=0):
        if state["exc"]:
            raise state["exc"]
        path.write_text("<html/>", encoding="utf-8")
        return state["html"] or {"nodes": 1, "edges": 0, "output": str(path)}

    def fake_svg(graph, path):
        path.write_text("<svg/>", encoding="utf-8")
        return state["svg"] or {"nodes": 1, "edges": 0, "output": str(path)}

    def fake_graphml(graph, path):
        path.write_text("<g/>", encoding="utf-8")
        return state["graphml"] or {"nodes": 1, "edges": 0, "output": str(path)}

    monkeypatch.setattr(ge, "detect_communities", fake_detect)
    monkeypatch.setattr(ge, "generate_report", fake_generate)
    monkeypatch.setattr(ge, "build_graph", fake_build)
    monkeypatch.setattr(ge, "export_html", fake_html)
    monkeypatch.setattr(ge, "export_svg", fake_svg)
    monkeypatch.setattr(ge, "export_graphml", fake_graphml)
    return state


def test_report_stdout(fake_graph_export: dict, capsys: pytest.CaptureFixture) -> None:
    fake_graph_export["detect"] = {"communities": {"0": ["a"]}}
    wiki = FakeWiki(index="IDX")
    assert run_report(wiki, _ns(top=5, output=None)) == 0
    assert "REPORT TEXT" in capsys.readouterr().out


def test_report_to_file(
    fake_graph_export: dict, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    fake_graph_export["detect"] = {"communities": {}}
    out = tmp_path / "r.md"
    wiki = FakeWiki(index="IDX")
    assert run_report(wiki, _ns(top=3, output=str(out))) == 0
    assert out.read_text(encoding="utf-8") == "REPORT TEXT"
    assert "Report written to" in capsys.readouterr().out


def test_export_graph_html(
    fake_graph_export: dict, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    wiki = FakeWiki(index="IDX")
    out = tmp_path / "g.html"
    args = _ns(format="html", output=str(out), min_degree=1)
    assert run_export_graph(wiki, args) == 0
    assert out.exists()
    assert "Exported: 1 nodes" in capsys.readouterr().out


def test_export_graph_default_name(
    fake_graph_export: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    wiki = FakeWiki(index="IDX")
    args = _ns(format="html", output=None, min_degree=0)
    assert run_export_graph(wiki, args) == 0
    assert (tmp_path / "graph.html").exists()


def test_export_graph_svg(
    fake_graph_export: dict, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    wiki = FakeWiki(index="IDX")
    out = tmp_path / "g.svg"
    assert run_export_graph(wiki, _ns(format="svg", output=str(out), min_degree=0)) == 0
    assert out.exists()


def test_export_graph_graphml(
    fake_graph_export: dict, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    wiki = FakeWiki(index="IDX")
    out = tmp_path / "g.graphml"
    assert run_export_graph(wiki, _ns(format="graphml", output=str(out), min_degree=0)) == 0
    assert out.exists()


def test_export_graph_unsupported_format(
    fake_graph_export: dict, capsys: pytest.CaptureFixture
) -> None:
    wiki = FakeWiki(index="IDX")
    assert run_export_graph(wiki, _ns(format="pdf", output="x.pdf", min_degree=0)) == 1
    assert "Unsupported format" in capsys.readouterr().out


def test_export_graph_import_error(
    fake_graph_export: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    import llmwikify.kernel.graph.export as ge

    def boom(*a, **k):
        raise ImportError("no networkx")

    monkeypatch.setattr(ge, "export_html", boom)
    wiki = FakeWiki(index="IDX")
    assert run_export_graph(wiki, _ns(format="html", output=str(tmp_path / "x.html"), min_degree=0)) == 1
    assert "Missing dependency" in capsys.readouterr().out


def test_export_graph_runtime_error(
    fake_graph_export: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    import llmwikify.kernel.graph.export as ge

    def boom(*a, **k):
        raise RuntimeError("too big")

    monkeypatch.setattr(ge, "export_html", boom)
    wiki = FakeWiki(index="IDX")
    assert run_export_graph(wiki, _ns(format="html", output=str(tmp_path / "x.html"), min_degree=0)) == 1
    assert "Export failed" in capsys.readouterr().out


def test_community_detect_json(
    fake_graph_export: dict, capsys: pytest.CaptureFixture
) -> None:
    fake_graph_export["detect"] = {
        "communities": {0: ["a", "b"], 1: ["c"]},
        "num_communities": 2,
        "modularity": 0.4,
        "total_nodes": 3,
        "total_edges": 2,
    }
    wiki = FakeWiki(index="IDX")
    args = _ns(algorithm="leiden", resolution=1.0, json=True, dry_run=False)
    assert run_community_detect(wiki, args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["num_communities"] == 2
    assert payload["communities"]["0"] == ["a", "b"]


def test_community_detect_dry_run(
    fake_graph_export: dict, capsys: pytest.CaptureFixture
) -> None:
    fake_graph_export["detect"] = {
        "communities": {},
        "num_communities": 0,
        "modularity": 0.0,
        "total_nodes": 0,
        "total_edges": 0,
    }
    wiki = FakeWiki(index="IDX")
    args = _ns(algorithm="louvain", resolution=0.5, json=False, dry_run=True)
    assert run_community_detect(wiki, args) == 0
    out = capsys.readouterr().out
    assert "Dry Run" in out
    assert "Algorithm: louvain" in out
    assert "Resolution: 0.5" in out


def test_community_detect_full(
    fake_graph_export: dict, capsys: pytest.CaptureFixture
) -> None:
    nodes = [f"n{i}" for i in range(15)]
    fake_graph_export["detect"] = {
        "communities": {0: nodes},
        "num_communities": 1,
        "modularity": 0.3,
        "total_nodes": 15,
        "total_edges": 10,
        "warning": "fallback used",
    }
    wiki = FakeWiki(index="IDX")
    args = _ns(algorithm="leiden", resolution=1.0, json=False, dry_run=False)
    assert run_community_detect(wiki, args) == 0
    out = capsys.readouterr().out
    assert "fallback used" in out
    assert "Community 0 (15 nodes):" in out
    assert "... and 5 more" in out
    assert "Modularity: 0.3" in out


# ══════════════════════════════════════════════════════════════════
# dict  (jieba boundary)
# ══════════════════════════════════════════════════════════════════


@pytest.fixture
def wiki_isinstance_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_dict does `if not isinstance(wiki, Wiki): wiki = Wiki(wiki)` —
    make FakeWiki pass the check by pointing Wiki at FakeWiki itself."""
    monkeypatch.setattr("llmwikify.kernel.Wiki", FakeWiki)


def test_dict_status_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture, wiki_isinstance_ok: None
) -> None:
    wiki = FakeWiki(root=tmp_path)
    assert run_dict(wiki, _ns(action="status")) == 0
    assert "No jieba dict generated" in capsys.readouterr().out


def test_dict_status_present(
    tmp_path: Path, capsys: pytest.CaptureFixture, wiki_isinstance_ok: None
) -> None:
    meta = tmp_path / ".wiki" / "jieba.meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"pages": 3}), encoding="utf-8")
    wiki = FakeWiki(root=tmp_path)
    assert run_dict(wiki, _ns(action="status")) == 0
    assert '"pages": 3' in capsys.readouterr().out


def test_dict_update(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    wiki_isinstance_ok: None,
) -> None:
    import llmwikify.kernel.storage.jieba_dict_gen as jdg

    monkeypatch.setattr(
        jdg,
        "generate_user_dict",
        lambda db, root: {"fast": 10, "slow": 2, "page_count": 5},
    )
    wiki = FakeWiki(root=tmp_path, db_path=tmp_path / "w.db")
    assert run_dict(wiki, _ns(action="update")) == 0
    out = capsys.readouterr().out
    assert "Fast terms: 10" in out
    assert "Slow terms: 2" in out
    assert "Pages: 5" in out


def test_dict_default_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wiki_isinstance_ok: None
) -> None:
    # action attr missing → defaults to "update"
    import llmwikify.kernel.storage.jieba_dict_gen as jdg

    hit = {"n": 0}

    def spy(db, root):
        hit["n"] += 1
        return {"fast": 0, "slow": 0, "page_count": 0}

    monkeypatch.setattr(jdg, "generate_user_dict", spy)
    wiki = FakeWiki(root=tmp_path, db_path=tmp_path / "w.db")
    run_dict(wiki, _ns())  # no action attr
    assert hit["n"] == 1


# ══════════════════════════════════════════════════════════════════
# setup_parser smoke (all commands)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "cls,name,extra",
    [
        (ReadPageCommand, "read_page", ["page"]),
        (SearchCommand, "search", ["query"]),
        (StatusCommand, "status", []),
        (SinkStatusCommand, "sink-status", []),
        (LogCommand, "log", []),
        (HelpCommand, "help", []),
        (FixWikilinksCommand, "fix-wikilinks", []),
        (WritePageCommand, "write_page", ["page"]),
        (SynthesizeCommand, "synthesize", ["query"]),
        (SuggestSynthesisCommand, "suggest-synthesis", []),
        (BuildIndexCommand, "build-index", []),
        (ReportCommand, "report", []),
        (ExportGraphCommand, "export-graph", []),
        (CommunityDetectCommand, "community-detect", []),
        (DictCommand, "dict", []),
    ],
)
def test_setup_parser_registers(cls: type, name: str, extra: list[str]) -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cls().setup_parser(sub)
    ns = parser.parse_args([name, *extra])
    assert ns is not None


def test_search_command_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(search=lambda q, lim, backend="": [])
    assert SearchCommand().run(_ns(query="q"), wiki, {}) == 0


def test_status_command_run() -> None:
    wiki = FakeWiki(status=lambda: {"initialized": False})
    assert StatusCommand().run(_ns(), wiki, {}) == 1


def test_read_page_command_run(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(read_page=lambda name, page_type=None: {"content": "x"})
    assert ReadPageCommand().run(_ns(name="p"), wiki, {}) == 0
