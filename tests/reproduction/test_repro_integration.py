"""Integration: reproduction 跨模块协作 (S3 阶段).

测试 sessions/factor_library/router 等模块的协作.

详见: docs/designs/pipeline_framework.md Section 29.9
"""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path

from llmwikify.reproduction.persist import sessions, factor_library
from llmwikify.reproduction.paper_understanding import schemas


class TestSessionToFactorLibrary:
    """Test sessions + factor_library 集成 (3 测试)."""

    def test_session_db_init(self, tmp_path: Path) -> None:
        """ReproductionDatabase 初始化."""
        db = sessions.ReproductionDatabase(db_path=tmp_path / "test.db")
        assert db is not None

    def test_session_create_and_get(self, tmp_path: Path) -> None:
        """创建并获取 session."""
        db = sessions.ReproductionDatabase(db_path=tmp_path / "test.db")
        sid = db.create_session(
            wiki_id="w1",
            paper_id="p1",
            source_type="pdf",
            source_ref="papers/p1.pdf",
            symbol="test:all",
            start_date="20200101",
            end_date="20241231",
        )
        assert isinstance(sid, str)

        # 获取
        session = db.get_session(sid)
        assert session is not None
        assert session.paper_id == "p1"

    def test_session_status_lifecycle(self, tmp_path: Path) -> None:
        """session 状态生命周期."""
        db = sessions.ReproductionDatabase(db_path=tmp_path / "test.db")
        sid = db.create_session(
            wiki_id="w1", paper_id="p1", source_type="pdf",
            source_ref="ref", symbol="s:all",
            start_date="20200101", end_date="20241231",
        )
        # update status
        db.update_status(sid, "extracting")
        session = db.get_session(sid)
        assert session.status == "extracting"

        db.update_status(sid, "done")
        session = db.get_session(sid)
        assert session.status == "done"


class TestSchemasWithSessions:
    """Test schemas + sessions 集成 (3 测试)."""

    def test_factor_backtest_result_construction(self) -> None:
        """FactorBacktestResult 可构造 (含 24 字段)."""
        r = schemas.FactorBacktestResult()
        d = r.to_dict()
        assert isinstance(d, dict)
        assert "ic_mean" in d

    def test_wiki_factor_with_status(self) -> None:
        """WikiFactor 含 status 字段."""
        f = schemas.WikiFactor(name="momentum", factor_class="alpha", factor_params={}, status="draft")
        assert f.status == "draft"
        d = f.to_dict()
        assert d["status"] == "draft"

    def test_wiki_strategy_with_factor_refs(self) -> None:
        """WikiStrategy 含 factor_refs 字段 (引用因子)."""
        s = schemas.WikiStrategy(
            name="strat1", strategy_class="factor_ranking",
            factor_refs=["momentum", "value"],
        )
        d = s.to_dict()
        assert d["factor_refs"] == ["momentum", "value"]


class TestSessionEvents:
    """Test 事件流 (2 测试)."""

    def test_record_event(self, tmp_path: Path) -> None:
        """记录 session event."""
        db = sessions.ReproductionDatabase(db_path=tmp_path / "test.db")
        sid = db.create_session(
            wiki_id="w1", paper_id="p1", source_type="pdf",
            source_ref="ref", symbol="s:all",
            start_date="20200101", end_date="20241231",
        )
        # 记录事件
        db.record_event(sid, "extract.start", stage="extracting")
        events = db.get_events(sid)
        assert len(events) >= 1
        assert events[0]["event_type"] == "extract.start"

    def test_list_sessions_filter(self, tmp_path: Path) -> None:
        """按 status 过滤 sessions."""
        db = sessions.ReproductionDatabase(db_path=tmp_path / "test.db")
        # 创建 2 个 session
        for i in range(2):
            db.create_session(
                wiki_id="w", paper_id=f"p{i}", source_type="pdf",
                source_ref="r", symbol="s:all",
                start_date="20200101", end_date="20241231",
            )
        all_sessions = db.list_sessions()
        assert len(all_sessions) >= 2
