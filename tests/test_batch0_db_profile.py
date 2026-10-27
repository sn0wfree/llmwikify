"""Regression tests for the FK profile fix in ``foundation/db.py``.

``get_connection()`` used to key its singleton registry by *path only*, so
the PRAGMA policy was decided by whichever facade was constructed first.
``AutoResearchDatabase`` builds Chat first, so the research facade's
explicit ``foreign_keys=False`` was silently dropped and research tables
ran with FK enforcement ON — the opposite of what
``apps/research/db.py`` documents.

Fix: ``PRAGMA foreign_keys`` is a **connection-level** attribute, so chat
(FK=ON) and research (FK=OFF) need two connections on the same file.
``get_connection()`` now keys on ``(db_path, profile)``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from llmwikify.foundation.db import (
    PROFILE_DEFAULT,
    PROFILE_RESEARCH,
    ConnectionProfile,
    close_all,
    get_connection,
)


@pytest.fixture(autouse=True)
def _release_connections() -> Any:
    """Release SQLite handles after each test so temp dirs can be removed."""
    yield
    close_all()


class TestConnectionProfile:
    def test_default_profile_enables_fk(self, tmp_path: Path) -> None:
        """The default profile must keep foreign_keys ON."""
        mc = get_connection(tmp_path / "default.db", profile=PROFILE_DEFAULT)
        assert mc.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_research_profile_disables_fk(self, tmp_path: Path) -> None:
        """The research profile must turn foreign_keys OFF."""
        mc = get_connection(tmp_path / "research.db", profile=PROFILE_RESEARCH)
        assert mc.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0

    def test_profiles_on_same_file_get_distinct_connections(
        self, tmp_path: Path
    ) -> None:
        """Same file + different profile => different connection instances.

        ``PRAGMA foreign_keys`` is per-connection, so the two profiles
        cannot share one connection without one of them losing its policy.
        """
        db = tmp_path / "shared.db"
        default = get_connection(db, profile=PROFILE_DEFAULT)
        research = get_connection(db, profile=PROFILE_RESEARCH)
        assert default is not research
        assert default.db_path == research.db_path
        assert default.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert research.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0

    def test_same_profile_on_same_path_is_a_singleton(self, tmp_path: Path) -> None:
        db = tmp_path / "same.db"
        assert get_connection(db, profile=PROFILE_DEFAULT) is get_connection(
            db, profile=PROFILE_DEFAULT
        )

    def test_legacy_kwargs_still_supported(self, tmp_path: Path) -> None:
        """Legacy ``**kwargs`` call sites keep working (folded into a profile)."""
        mc = get_connection(tmp_path / "legacy.db", wal=False, busy_timeout=1000)
        assert mc.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1000

    def test_profile_and_kwargs_are_mutually_exclusive(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError, match="not both"):
            get_connection(tmp_path / "x.db", profile=PROFILE_DEFAULT, wal=False)

    def test_unknown_kwarg_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError, match="unknown connection option"):
            get_connection(tmp_path / "y.db", bogus=True)

    def test_profile_is_hashable_and_frozen(self) -> None:
        """The profile is part of the registry key -> must be hashable."""
        assert hash(ConnectionProfile()) == hash(ConnectionProfile())
        with pytest.raises(dataclasses.FrozenInstanceError):
            PROFILE_DEFAULT.foreign_keys = False  # type: ignore[misc]


class TestResearchDatabaseForeignKeys:
    """The research facade must get FK OFF regardless of construction order."""

    def test_research_fk_off_even_when_chat_constructed_first(
        self, tmp_path: Path
    ) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        from llmwikify.apps.research.db import ResearchDatabase

        # Chat first — this is what AutoResearchDatabase does.
        chat = ChatDatabase(tmp_path)
        research = ResearchDatabase(tmp_path)
        assert chat._mgr.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert research._mgr.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0

    def test_research_insert_with_orphan_fk_succeeds(self, tmp_path: Path) -> None:
        """The documented reason research disables FK: fixtures violate them.

        ``autoresearch_sources.sub_query_id`` references
        ``autoresearch_sub_queries(id)``; inserting a source whose
        sub_query_id was never inserted must not raise.
        """
        from llmwikify.apps.research.db import ResearchDatabase

        research = ResearchDatabase(tmp_path)
        research.save_source(
            session_id="no-such-session",
            sub_query_id="no-such-sub-query",
            source_type="web",
            url="https://example.com",
            title="Example",
            content_length=10,
        )
        sources = research.get_sources("no-such-session")
        assert isinstance(sources, list)
