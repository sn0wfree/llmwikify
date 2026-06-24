"""Phase 8 TDD 前置测试: 验证 persist/ 目标模块在搬迁后可用.

5 个测试, 定义 persist/ 子包的公共 API 契约.
"""
from __future__ import annotations


def test_factor_library_read():
    from llmwikify.reproduction.persist.factor_library import read_factor_yaml
    assert callable(read_factor_yaml)


def test_factor_library_list():
    from llmwikify.reproduction.persist.factor_library import list_factors
    factors = list_factors()
    assert isinstance(factors, list)


def test_sessions_db_init():
    from llmwikify.reproduction.persist.sessions import ReproductionDatabase
    db = ReproductionDatabase()
    assert db is not None


def test_sessions_create_session():
    from llmwikify.reproduction.persist.sessions import ReproductionDatabase
    db = ReproductionDatabase()
    sid = db.create_session(
        wiki_id="test", paper_id="test", source_type="test",
        source_ref="ref", symbol="test:all",
        start_date="20200101", end_date="20241231"
    )
    assert isinstance(sid, str) and len(sid) > 0


def test_run_reproduction_callable():
    from llmwikify.reproduction.persist.run import run_reproduction
    assert callable(run_reproduction)
