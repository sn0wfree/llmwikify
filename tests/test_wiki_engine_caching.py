"""Phase 2 #4 — Wiki class caches WikiAnalyzer at __init__.

The 16 redundant ``WikiAnalyzer(self)`` instantiations across
3 mixins (WikiLintMixin, WikiStatusMixin, WikiLLMMixin) are
consolidated into a single cached ``self._analyzer``
attribute. This commit formalizes the contract via tests.

Tests cover:
  1. The cache attribute is set in __init__.
  2. The cached analyzer is the single instance shared by all
     call sites.
  3. lint() / _detect_X() / recommend() / hint() /
     _llm_detect_gaps() / _build_lint_context() all use
     ``self._analyzer`` (not a fresh ``WikiAnalyzer(self)``).
  4. The protocol declares the new attribute.
  5. A regression guard: mixing the legacy pattern
     ``WikiAnalyzer(self)`` into a mixin would be caught.
"""

import inspect

import pytest


def test_wiki_caches_analyzer_in_init():
    """Wiki.__init__ sets self._analyzer = WikiAnalyzer(self)."""
    from llmwikify.core import Wiki
    from llmwikify.core.wiki_analyzer import WikiAnalyzer

    # We use a tmp path with the standard wiki root structure
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "test_wiki"
        root.mkdir()
        (root / "raw").mkdir()
        (root / "wiki").mkdir()

        wiki = Wiki(root)

        # The cache attribute is set
        assert hasattr(wiki, "_analyzer"), (
            "Wiki.__init__ should set self._analyzer for Phase 2 #4"
        )
        # It's a WikiAnalyzer
        assert isinstance(wiki._analyzer, WikiAnalyzer), (
            f"Wiki._analyzer should be WikiAnalyzer, got {type(wiki._analyzer)}"
        )
        # It holds a back-reference to the wiki
        assert wiki._analyzer.wiki is wiki


def test_lint_mixin_uses_cached_analyzer():
    """WikiLintMixin methods reference self._analyzer (not WikiAnalyzer(self))."""
    from llmwikify.core.wiki_mixin_lint import WikiLintMixin

    delegate_methods = [
        "_detect_dated_claims",
        "_detect_query_page_overlap",
        "_detect_missing_cross_refs",
        "_detect_potential_contradictions",
        "_detect_data_gaps",
        "_detect_outdated_pages",
        "_detect_knowledge_gaps",
        "_detect_redundancy",
        "lint",
        "_generate_hints",
    ]

    for name in delegate_methods:
        method = getattr(WikiLintMixin, name)
        src = inspect.getsource(method)
        # The body must reference the cached analyzer, not re-instantiate
        assert "self._analyzer" in src, (
            f"WikiLintMixin.{name} should use self._analyzer (cached). "
            f"Source:\n{src}"
        )
        # And should NOT re-import WikiAnalyzer per call
        assert "from .wiki_analyzer import WikiAnalyzer" not in src, (
            f"WikiLintMixin.{name} should not re-import WikiAnalyzer per call. "
            f"Phase 2 #4 caches it on Wiki.__init__. Source:\n{src}"
        )


def test_status_mixin_uses_cached_analyzer():
    """WikiStatusMixin.recommend and .hint reference self._analyzer."""
    from llmwikify.core.wiki_mixin_status import WikiStatusMixin

    for name in ("recommend", "hint"):
        method = getattr(WikiStatusMixin, name)
        src = inspect.getsource(method)
        assert "self._analyzer" in src, (
            f"WikiStatusMixin.{name} should use self._analyzer (cached). "
            f"Source:\n{src}"
        )
        assert "from .wiki_analyzer import WikiAnalyzer" not in src, (
            f"WikiStatusMixin.{name} should not re-import WikiAnalyzer. "
            f"Source:\n{src}"
        )


def test_llm_mixin_uses_cached_analyzer():
    """WikiLLMMixin lint helpers reference self._analyzer (not WikiAnalyzer(self))."""
    from llmwikify.core.wiki_mixin_llm import WikiLLMMixin

    delegate_methods = [
        "_llm_generate_investigations",
        "_llm_detect_gaps",
        "_fallback_detect_gaps",
        "_build_lint_context",
    ]

    for name in delegate_methods:
        method = getattr(WikiLLMMixin, name)
        src = inspect.getsource(method)
        assert "self._analyzer" in src, (
            f"WikiLLMMixin.{name} should use self._analyzer (cached). "
            f"Source:\n{src}"
        )
        assert "from .wiki_analyzer import WikiAnalyzer" not in src, (
            f"WikiLLMMixin.{name} should not re-import WikiAnalyzer. "
            f"Source:\n{src}"
        )


def test_wiki_protocol_declares_analyzer_attribute():
    """WikiProtocol declares the _analyzer attribute for type resolution."""
    from llmwikify.core.protocols import WikiProtocol

    # WikiProtocol uses annotation-style declarations (not
    # class attributes) — they live in __annotations__.
    assert "_analyzer" in WikiProtocol.__annotations__, (
        "WikiProtocol should declare _analyzer for cross-mixin "
        "type resolution. Phase 2 #4 requires the cache to be a "
        "WikiProtocol annotation."
    )


def test_no_redundant_WikiAnalyzer_self_in_mixins():
    """Regression guard: no mixin method body creates ``WikiAnalyzer(self)``.

    Phase 2 #4 consolidates ALL analyzer instantiations to
    ``Wiki.__init__``. If a future commit adds a new mixin
    method that re-instantiates, this test fails.
    """
    from llmwikify.core.wiki_mixin_lint import WikiLintMixin
    from llmwikify.core.wiki_mixin_status import WikiStatusMixin
    from llmwikify.core.wiki_mixin_llm import WikiLLMMixin

    for mixin_cls in (WikiLintMixin, WikiStatusMixin, WikiLLMMixin):
        for name in dir(mixin_cls):
            if name.startswith("__"):
                continue
            attr = getattr(mixin_cls, name)
            if not callable(attr):
                continue
            try:
                src = inspect.getsource(attr)
            except (OSError, TypeError):
                continue
            # The pattern ``WikiAnalyzer(self)`` should not
            # appear in any mixin method body anymore.
            assert "WikiAnalyzer(self)" not in src, (
                f"{mixin_cls.__name__}.{name} contains "
                f"``WikiAnalyzer(self)`` — should use self._analyzer "
                f"instead. Phase 2 #4 caches the analyzer in Wiki.__init__."
            )
