"""Phase 2 #5 / C3 — Observer + Resume extracted from engine.py.

Tests cover the 2 methods (observe + load_resume_state)
that now live in ``autoresearch.observer.ResearchObserver``
and ``autoresearch.resume.ResearchResumeLoader``:

  1. Engine holds ``self.observer`` and ``self.resume_loader``
  2. Observer holds back-refs to engine's db
  3. ResumeLoader holds back-refs to engine's db and
     ``_max_react_rounds``
  4. ``_observe`` on engine delegates to ``observer.observe``
  5. ``_load_resume_state`` on engine delegates to
     ``resume_loader.load``
  6. ``observer.observe`` reloads sources and sub_queries
  7. ``observer.observe`` populates observations on
     analyzed sources (credibility, types, wiki vs web)
  8. ``resume_loader.load`` returns silently for missing
     session row (fresh session)
  9. ``resume_loader.load`` hydrates state.knowledge_gaps
     from the JSON column
 10. Regression guard: the ``_observe`` and
     ``_load_resume_state`` inline logic is no longer in
     ``engine.py``.
"""

import inspect


def test_engine_constructs_observer_and_resume_loader():
    """ResearchEngine.__init__ creates self.observer + self.resume_loader."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine.__init__)
    assert "self.observer = ResearchObserver(self)" in src, (
        "ResearchEngine.__init__ should construct a ResearchObserver"
    )
    assert "self.resume_loader = ResearchResumeLoader(self)" in src, (
        "ResearchEngine.__init__ should construct a ResearchResumeLoader"
    )


def test_observer_holds_back_refs_to_engine_deps():
    """ResearchObserver caches the engine's db."""
    from llmwikify.apps.chat.observer import ResearchObserver

    class FakeEngine:
        db = "fake_db"

    obs = ResearchObserver(FakeEngine())
    assert obs._db == "fake_db"


def test_resume_loader_holds_back_refs_to_engine_deps():
    """ResearchResumeLoader caches the engine's db and _max_react_rounds."""
    from llmwikify.apps.chat.resume import ResearchResumeLoader

    class FakeEngine:
        db = "fake_db"
        _max_react_rounds = 5

    rl = ResearchResumeLoader(FakeEngine())
    assert rl._db == "fake_db"
    assert rl._max_react_rounds == 5


def test_engine_observe_delegates_to_observer():
    """engine._observe → self.observer.observe."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._observe)
    assert "self.observer.observe" in src, (
        "engine._observe should delegate to self.observer.observe"
    )


def test_engine_load_resume_state_delegates_to_resume_loader():
    """engine._load_resume_state → self.resume_loader.load."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._load_resume_state)
    assert "self.resume_loader.load" in src, (
        "engine._load_resume_state should delegate to "
        "self.resume_loader.load"
    )


def test_observer_reloads_sources_and_sub_queries():
    """observer.observe reloads state.sources and state.sub_queries from DB."""
    from llmwikify.apps.chat.observer import ResearchObserver
    from llmwikify.apps.chat.state import ResearchState

    class FakeDB:
        def __init__(self):
            self.sources = [
                {"id": 1, "sub_query_id": 1, "analysis": {}},
                {"id": 2, "sub_query_id": 2, "analysis": {}},
            ]
            self.sub_queries = [
                {"id": 1, "query": "q1", "source_type": "wiki", "status": "ok"},
                {"id": 2, "query": "q2", "source_type": "web", "status": "ok"},
            ]

        def get_sources(self, session_id):
            return self.sources

        def get_sub_queries(self, session_id):
            return self.sub_queries

    class FakeEngine:
        db = FakeDB()

    obs = ResearchObserver(FakeEngine())
    state = ResearchState(session_id="s1")
    obs.observe(state)
    assert len(state.sources) == 2
    assert state.total_sources == 2
    assert len(state.sub_queries) == 2
    assert state.total_sub_queries == 2
    # sub_queries were rebuilt with the right keys
    assert state.sub_queries[0]["id"] == 1
    assert state.sub_queries[0]["query"] == "q1"
    assert state.sub_queries[0]["source_type"] == "wiki"


def test_observer_populates_observations_on_analyzed_sources():
    """observer.observe builds credibility + type + wiki/web observations."""
    from llmwikify.apps.chat.observer import ResearchObserver
    from llmwikify.apps.chat.state import ResearchState

    class FakeDB:
        def __init__(self):
            self.sources = [
                {
                    "id": 1, "sub_query_id": 1, "source_type": "wiki",
                    "analysis": {"quality_assessment": {"credibility": 8}},
                },
                {
                    "id": 2, "sub_query_id": 2, "source_type": "web",
                    "analysis": {"quality_assessment": {"credibility": 6}},
                },
            ]
            self.sub_queries = [
                {"id": 1, "query": "q1", "source_type": "wiki", "status": "ok"},
                {"id": 2, "query": "q2", "source_type": "web", "status": "ok"},
            ]

        def get_sources(self, session_id):
            return self.sources

        def get_sub_queries(self, session_id):
            return self.sub_queries

    class FakeEngine:
        db = FakeDB()

    obs = ResearchObserver(FakeEngine())
    state = ResearchState(session_id="s1")
    obs.observe(state)
    # 3 observations: avg credibility, source types, wiki vs web
    assert len(state.observations) >= 3, (
        f"Expected ≥3 observations, got {state.observations}"
    )
    # The first should be the avg credibility line
    assert "Average source credibility" in state.observations[0]
    # Source types should appear
    assert any("Source types" in o for o in state.observations)
    # Wiki vs web ratio should appear
    assert any("Local wiki" in o and "Web" in o for o in state.observations)


def test_resume_loader_returns_silently_for_missing_session():
    """resume_loader.load silently returns if session row is missing."""
    from llmwikify.apps.chat.resume import ResearchResumeLoader
    from llmwikify.apps.chat.state import ResearchState

    class FakeDB:
        def get_research_session(self, session_id):
            return None

    class FakeEngine:
        db = FakeDB()
        _max_react_rounds = 5

    rl = ResearchResumeLoader(FakeEngine())
    state = ResearchState(session_id="nonexistent")
    # Should not raise
    rl.load(state)
    # State should be unchanged from its ResearchState default
    # (round=0, max_rounds=5 by default — the loader only
    # sets max_rounds from session row, which is None here)
    assert state.round == 0
    # Knowledge gaps should still be the default empty list
    assert state.knowledge_gaps == []


def test_resume_loader_hydrates_knowledge_gaps_from_json():
    """resume_loader.load restores state.knowledge_gaps from JSON column."""
    import json
    from llmwikify.apps.chat.resume import ResearchResumeLoader
    from llmwikify.apps.chat.state import ResearchState

    session_row = {
        "max_rounds": 5,
        "quality_score": 7,
        "current_step": "planning",
        "knowledge_gaps": json.dumps(["gap1", "gap2"]),
    }

    class FakeDB:
        def get_research_session(self, session_id):
            return session_row

        def get_sub_queries(self, session_id):
            return []

        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        _max_react_rounds = 5

    rl = ResearchResumeLoader(FakeEngine())
    state = ResearchState(session_id="s1")
    rl.load(state)
    assert state.knowledge_gaps == ["gap1", "gap2"]
    assert state.quality_score == 7
    assert state.max_rounds == 5
    # phase was "planning" — not in terminal set
    assert state.phase == "planning"


def test_legacy_observe_and_resume_logic_not_in_engine():
    """Regression guard: observe + resume inline logic is not in engine.py.

    The ``_observe`` and ``_load_resume_state`` methods
    used to have rich inline logic. After C3, only the
    1-line delegators remain. This test catches
    re-introduction of the inline logic.
    """
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine)
    # The phrase ``Average source credibility`` (from
    # _observe's inline observation builder) should NOT
    # appear in the engine anymore.
    assert "Average source credibility" not in src, (
        "The observe logic should not be inlined in "
        "engine.py. Phase 2 #5 / C3 extracted it to "
        "observer.py. If you see this error, the inline "
        "logic was re-introduced."
    )
    # The phrase ``Resuming session`` (from
    # _load_resume_state's tail log) should NOT appear
    assert "Resuming session" not in src, (
        "The resume loader logic should not be inlined in "
        "engine.py. Phase 2 #5 / C3 extracted it to "
        "resume.py."
    )
