"""Phase 4 TDD 前置测试: 验证 prompts/ 子包在创建前的需求.

9 个测试, 定义 prompts/ 子包的公共 API 契约.
"""
from __future__ import annotations


def test_prompt_group_render_user():
    from llmwikify.reproduction.prompts.group import PromptGroup
    g = PromptGroup(name="test", version="1.0.0", source="builtin",
                    system="...", user_template="Hello {{ name }}!",
                    feedback_template=None, metadata={}, raw={})
    assert g.render_user(name="world") == "Hello world!"


def test_prompt_group_render_feedback():
    from llmwikify.reproduction.prompts.group import PromptGroup
    g = PromptGroup(name="test", version="1.0.0", source="builtin",
                    system="...", user_template="Hello",
                    feedback_template="Error: {{ error_message }}",
                    metadata={}, raw={})
    assert g.render_feedback(error_message="boom") == "Error: boom"


def test_prompt_group_feedback_template_required():
    from llmwikify.reproduction.prompts.group import PromptGroup
    g = PromptGroup(name="test", version="1.0.0", source="builtin",
                    system="...", user_template="Hello",
                    feedback_template=None, metadata={}, raw={})
    try:
        g.render_feedback(error_message="boom")
        assert False, "Should raise"
    except ValueError:
        pass


def test_prompt_version_compatibility():
    from llmwikify.reproduction.prompts.group import PromptGroup
    g = PromptGroup(name="test", version="1.2.3", source="builtin",
                    system="...", user_template="Hello",
                    feedback_template=None, metadata={}, raw={})
    assert g.is_compatible("1.0.0") is True
    assert g.is_compatible("1.2.0") is True
    assert g.is_compatible("2.0.0") is False


def test_prompt_registry_get_latest():
    from llmwikify.reproduction.prompts.registry import PromptRegistry
    from llmwikify.reproduction.prompts.group import PromptGroup
    reg = PromptRegistry()
    reg.register(PromptGroup(name="test", version="1.0.0", source="builtin",
                             system="s1", user_template="t1",
                             feedback_template=None, metadata={}, raw={}))
    reg.register(PromptGroup(name="test", version="1.1.0", source="builtin",
                             system="s2", user_template="t2",
                             feedback_template=None, metadata={}, raw={}))
    latest = reg.get("test", version="latest")
    assert latest.version == "1.1.0"


def test_prompt_registry_require_missing():
    from llmwikify.reproduction.prompts.registry import PromptRegistry
    reg = PromptRegistry()
    try:
        reg.require("nonexistent")
        assert False, "Should raise"
    except KeyError:
        pass


def test_prompt_loader_load_yaml(tmp_path):
    from llmwikify.reproduction.prompts.loader import PromptLoader
    yaml_content = """
name: test
version: "1.0.0"
source: builtin
system: "You are helpful"
user_template: "Hello {{ name }}"
feedback_template: null
metadata: {}
"""
    p = tmp_path / "test.yaml"
    p.write_text(yaml_content, encoding="utf-8")
    loader = PromptLoader(base_dir=tmp_path)
    group = loader.load("test.yaml")
    assert group.name == "test"
    assert group.version == "1.0.0"


def test_prompt_store_builtin_path():
    from llmwikify.reproduction.prompts.store import PromptStore
    store = PromptStore()
    assert store.builtin_dir.name == "builtin"
    assert store.builtin_dir.exists()
