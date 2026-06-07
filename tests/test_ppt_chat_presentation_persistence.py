"""Regression tests for PPTChat presentation_json persistence.

Covers:
  - update_ppt_task_presentation writes full Presentation format
  - set_ppt_task_partial_presentation still works independently
  - chat turn preserves full format (end-to-end simulation)
  - partial-format corruption can be loaded defensively
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from llmwikify.apps.agent.core.db import AgentDatabase
from llmwikify.apps.ppt.schema import Presentation, SlideContent
from llmwikify.apps.ppt.themes import get_theme


def _make_presentation(title="Test Deck", slides=None):
    if slides is None:
        slides = [
            SlideContent(id="s1", layout="title", title="Cover", subtitle="Sub"),
            SlideContent(id="s2", layout="bullets", title="Points", bullets=["A", "B"]),
        ]
    return Presentation(
        title=title,
        subtitle="Sub",
        theme=get_theme("minimal-white"),
        slides=slides,
        source={"type": "topic"},
    )


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        yield AgentDatabase(Path(tmp) / "test.db")


def _create_task(db, pres):
    """Helper: create a ppt_task with presentation_json already set."""
    task_id = db.create_ppt_task(
        title=pres.title,
        theme=pres.theme.id,
        source_type="topic",
        source_id=None,
        outline_json="{}",
    )
    db.update_ppt_task_presentation(task_id, pres.model_dump())
    return task_id


def _get_presentation_json(db, task_id):
    """Read raw presentation_json via sqlite3."""
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            "SELECT presentation_json FROM ppt_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    return json.loads(row[0]) if row else None


class TestUpdatePptTaskPresentation:
    def test_writes_full_format(self, db):
        pres = _make_presentation()
        task_id = _create_task(db, pres)

        new_pres = _make_presentation(title="Updated Deck")
        db.update_ppt_task_presentation(task_id, new_pres.model_dump())

        loaded = _get_presentation_json(db, task_id)
        for field in ("title", "theme", "source", "slides"):
            assert field in loaded, f"Missing {field} after update"
        assert loaded["title"] == "Updated Deck"
        assert len(loaded["slides"]) == 2

    def test_preserves_non_slides_fields(self, db):
        pres = _make_presentation(title="Original")
        task_id = _create_task(db, pres)

        new_pres = _make_presentation(title="Original")
        db.update_ppt_task_presentation(task_id, new_pres.model_dump())

        loaded = _get_presentation_json(db, task_id)
        assert loaded["title"] == "Original"
        assert loaded["source"]["type"] == "topic"


class TestSetPartialStillWorks:
    """set_ppt_task_partial_presentation should still work for its original
    purpose (incremental slide_done during async generation)."""

    def test_partial_writes_partial_format(self, db):
        pres = _make_presentation()
        task_id = _create_task(db, pres)

        slides = [s.model_dump() for s in pres.slides]
        db.set_ppt_task_partial_presentation(task_id, slides)

        loaded = _get_presentation_json(db, task_id)
        assert "partial" in loaded
        assert loaded["partial"] is True
        assert "slides" in loaded


class TestChatTurnPreservesFullFormat:
    """After a chat turn, presentation_json must remain in full format
    so subsequent loads can re-parse it as Presentation."""

    def test_full_format_after_update(self, db):
        pres = _make_presentation(title="Chat Deck")
        task_id = _create_task(db, pres)

        new_slides = [
            SlideContent(id="s1", layout="title", title="New Cover", subtitle="Updated"),
            SlideContent(id="s2", layout="bullets", title="Points", bullets=["X", "Y", "Z"]),
        ]
        updated_pres = _make_presentation(title="Chat Deck", slides=new_slides)
        db.update_ppt_task_presentation(task_id, updated_pres.model_dump())

        loaded = _get_presentation_json(db, task_id)
        assert "partial" not in loaded, "partial flag must not be present"
        for field in ("title", "theme", "source", "slides"):
            assert field in loaded, f"Missing {field} after chat turn"

        reparsed = Presentation(**loaded)
        assert reparsed.title == "Chat Deck"
        assert len(reparsed.slides) == 2
        assert reparsed.slides[1].bullets == ["X", "Y", "Z"]


class TestPartialFormatDefensiveLoader:
    """If presentation_json is a partial format, the loader should still
    be able to reconstruct a loadable dict using task row fields."""

    def test_partial_format_reconstructable(self, db):
        pres = _make_presentation(title="Old Deck")
        task_id = _create_task(db, pres)

        # Corrupt: overwrite with partial format
        slides = [s.model_dump() for s in pres.slides]
        db.set_ppt_task_partial_presentation(task_id, slides)

        # Simulate chat_routes loader logic
        task_row = db.get_ppt_task(task_id)
        raw = json.loads(task_row["presentation_json"])
        if "presentation" in raw:
            raw = raw["presentation"]

        # Defensive merge (same as chat_routes.py)
        raw.setdefault("title", task_row.get("title") or "Untitled")
        raw.setdefault("subtitle", task_row.get("subtitle") or "")
        raw.setdefault("source", {"type": "topic"})
        if "theme" not in raw or not raw["theme"]:
            theme_id = task_row.get("theme", "minimal-white")
            try:
                full_theme = get_theme(theme_id).model_dump()
            except Exception:
                full_theme = {"id": theme_id, "name": theme_id, "colors": {"primary": "#3b82f6", "secondary": "#64748b", "background": "#ffffff", "text": "#1e293b", "accent": "#3b82f6"}}
            raw["theme"] = full_theme
        raw.setdefault("slides", [])

        # Must be loadable as Presentation
        loaded = Presentation(**raw)
        assert loaded.title == "Old Deck"
        assert len(loaded.slides) == 2
