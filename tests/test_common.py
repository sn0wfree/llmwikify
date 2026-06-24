"""Phase 1 后置测试: 验证 common/ 子包搬迁后可用.

搬迁后改为新路径 (common.X), 仅改 import, 不改测试逻辑.
"""
from __future__ import annotations


def test_config_singleton():
    from llmwikify.reproduction.common.config import config
    assert config is not None


def test_paths_has_functions():
    from llmwikify.reproduction.common import paths
    assert hasattr(paths, "page_path")
    assert hasattr(paths, "result_path")
    assert hasattr(paths, "list_pages")


def test_run_id_format():
    from llmwikify.reproduction.common.run_id import generate_run_id
    rid = generate_run_id()
    assert isinstance(rid, str) and len(rid) > 0


def test_telemetry_singleton():
    from llmwikify.reproduction.common.telemetry import get_telemetry
    assert get_telemetry() is get_telemetry()


def test_categorize_compile_error():
    from llmwikify.reproduction.common.errors import categorize_compile_error
    result = categorize_compile_error(SyntaxError("test"))
    assert result is not None


def test_parse_frontmatter():
    from llmwikify.reproduction.common.utils import parse_frontmatter
    meta = parse_frontmatter("---\ntitle: t\n---\nbody")
    assert meta["title"] == "t"


def test_generate_slug():
    from llmwikify.reproduction.common.utils import generate_slug
    assert generate_slug("Hello World") == "hello-world"


def test_build_default_client():
    from llmwikify.reproduction.common.llm_factory import build_default_client
    client = build_default_client()
    assert client is not None
