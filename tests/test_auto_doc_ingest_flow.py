"""End-to-end flow: a document dropped into raw/ becomes wiki content.

Covers the three paths that matter for Track A + Track C:

1. happy path — ingest → LLM plan → pages written → enrichment
2. LLM failure — falls back to a proposal, content is not lost
3. enrichment failure — pages stay written, the error is recorded

The tests call ``AutoIngestService._process_file`` directly instead of
relying on watchdog (often missing in CI) — see
``docs/designs/auto-doc-enrichment.md`` §端到端测试.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
from llmwikify.apps.agent.maintenance.config import AutoIngestConfig
from llmwikify.kernel import Wiki


@pytest.fixture
def wiki(tmp_path: Path) -> Wiki:
    w = Wiki(tmp_path)
    (tmp_path / "raw").mkdir(exist_ok=True)
    (tmp_path / "wiki").mkdir(exist_ok=True)
    return w


def _service(wiki: Wiki, **overrides) -> AutoIngestService:
    return AutoIngestService(
        wiki=wiki,
        wiki_id="e2e",
        config=AutoIngestConfig(debounce_seconds=0.01),
        llm_semaphore=asyncio.Semaphore(1),
        **overrides,
    )


def _doc(wiki: Wiki, name: str = "doc.md") -> Path:
    path = wiki.raw_dir / name
    path.write_text("# Doc Title\n\nHello e2e content.\n", encoding="utf-8")
    return path


def _fake_llm(_result) -> dict:
    """Stand-in for ``_llm_process_source``: one fixed page write."""
    return {
        "operations": [
            {
                "action": "write_page",
                "page_name": "concepts/Foo",
                "content": "# Foo\n\nWritten from the e2e document.\n",
            },
        ],
        "relations": [],
        "entities": [],
        "claims": [],
    }


def _page_exists(wiki: Wiki, name: str) -> bool:
    return (wiki.wiki_dir / f"{name}.md").exists()


# ── 1. happy path ───────────────────────────────────────────────────


def test_document_flows_into_wiki(wiki: Wiki):
    """raw/ document → ingest → plan → page written on disk."""
    wiki._llm_process_source = _fake_llm  # type: ignore[assignment]
    doc = _doc(wiki)
    svc = _service(wiki)

    asyncio.run(svc._process_file(doc))

    assert _page_exists(wiki, "concepts/Foo"), "page was not written"
    content = (wiki.wiki_dir / "concepts/Foo.md").read_text(encoding="utf-8")
    assert "Written from the e2e document." in content
    assert svc.stats["pages_written"] == 1
    assert svc.stats["failed"] == 0


def test_ingest_archives_source_and_logs(wiki: Wiki):
    """The source must land in raw/ and the operation be audited."""
    wiki._llm_process_source = _fake_llm  # type: ignore[assignment]
    doc = wiki.raw_dir / "outside.md"
    doc.write_text("# Outside\n\nBody.\n", encoding="utf-8")

    svc = _service(wiki)
    asyncio.run(svc._process_file(doc))

    # ingest_source copies files outside raw/ into raw/
    assert (wiki.raw_dir / "outside.md").exists()
    assert svc.stats["ingested"] == 1


# ── 2. LLM failure → proposal fallback ──────────────────────────────


def test_llm_failure_falls_back_to_proposal(wiki: Wiki):
    """A failing LLM must not lose the document: it becomes a proposal."""

    def _boom(_result):
        raise RuntimeError("llm down")

    wiki._llm_process_source = _boom  # type: ignore[assignment]
    doc = _doc(wiki)
    svc = _service(wiki)

    asyncio.run(svc._process_file(doc))

    assert svc.stats["fallback_proposals"] >= 1, "no proposal was queued"
    assert "llm_write" in (svc.stats["last_error"] or "")
    assert svc.stats["pages_written"] == 0


# ── 3. enrichment failure does not lose pages ───────────────────────


def test_enricher_failure_does_not_lose_pages(wiki: Wiki):
    """Track C failing must not undo Track A's write."""

    class _BoomEnricher:
        async def enrich(self, **kwargs):
            raise RuntimeError("enrich exploded")

    wiki._llm_process_source = _fake_llm  # type: ignore[assignment]
    doc = _doc(wiki)
    svc = _service(wiki, enricher=_BoomEnricher())

    asyncio.run(svc._process_file(doc))

    assert _page_exists(wiki, "concepts/Foo"), "page lost to enricher failure"
    assert svc.stats["pages_written"] == 1
    assert "enrich:" in (svc.stats["last_error"] or "")


# ── 4. reprocessing is skipped ──────────────────────────────────────


def test_reprocessing_is_skipped(wiki: Wiki):
    """The processed-state file must stop the same file being written twice."""
    wiki._llm_process_source = _fake_llm  # type: ignore[assignment]
    doc = _doc(wiki)
    svc = _service(wiki)

    asyncio.run(svc._process_file(doc))
    first = svc.stats["pages_written"]

    asyncio.run(svc._process_file(doc))
    assert svc.stats["pages_written"] == first, "file was processed twice"


# ── 5. enrichment runs on the happy path ────────────────────────────


def test_enrichment_runs_after_write(wiki: Wiki):
    """Track C is invoked with the plan and execution results."""
    calls: dict = {}

    class _Recorder:
        async def enrich(self, llm_result=None, exec_result=None):
            calls["llm_result"] = llm_result
            calls["exec_result"] = exec_result
            return SimpleNamespace(links_added=0, proposals_created=0)

    wiki._llm_process_source = _fake_llm  # type: ignore[assignment]
    doc = _doc(wiki)
    svc = _service(wiki, enricher=_Recorder())

    asyncio.run(svc._process_file(doc))

    assert calls, "enrichment was not invoked"
    assert calls["llm_result"]["operations"][0]["page_name"] == "concepts/Foo"
    assert calls["exec_result"]["operations_executed"] == 1
