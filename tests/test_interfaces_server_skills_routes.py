"""Tests for Phase 11-F2 plugin_loader refactor + /api/skills endpoint.

Covers:
  - plugin_loader delegates to loader.parse_skill_frontmatter
  - plugin_metadata is attached to PromptBasedSkill instances
  - /api/skills list + detail endpoints work end-to-end
  - 404 on unknown skill name
  - Back-compat: SKILL.md without frontmatter still loads
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# ── plugin_loader refactor ────────────────────────────────────────


class TestPluginLoaderFrontmatterIntegration:
    def test_loads_full_frontmatter(self, tmp_path: Path) -> None:
        """Plugin skill with full YAML frontmatter parses + registers."""
        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.plugin_loader import _load_skill_md
        from llmwikify.apps.chat.skills.registry import SkillRegistry

        skill_dir = tmp_path / "study"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent(
                """\
                ---
                name: study
                description: study helper
                version: 1.2.0
                author: alice
                triggers:
                  - /study
                  - /learn
                allowed-tools:
                  - read_file
                tags:
                  - education
                license: MIT
                requires-config: false
                ---
                # body
                actual instructions for the LLM
                """
            )
        )

        reg = SkillRegistry()
        _load_skill_md(skill_dir, reg)

        skill = reg.get("study")
        assert isinstance(skill, PromptBasedSkill)
        assert skill.description == "study helper"
        # The extended metadata is stashed on the instance.
        meta = getattr(skill, "_plugin_metadata", None)
        assert meta is not None
        assert meta["version"] == "1.2.0"
        assert meta["author"] == "alice"
        assert meta["tags"] == ["education"]
        assert meta["license"] == "MIT"
        assert meta["requires_config"] is False
        # Triggers flowed into the SkillAction as before (back-compat).
        actions = list(skill.actions.values())
        assert len(actions) == 1
        assert actions[0].triggers == ["/study", "/learn"]

    def test_loads_body_only_skill(self, tmp_path: Path) -> None:
        """No frontmatter → fallback name from dir, plugin metadata absent version override."""
        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.plugin_loader import _load_skill_md
        from llmwikify.apps.chat.skills.registry import SkillRegistry

        skill_dir = tmp_path / "no_fm_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Just markdown\n\nNo frontmatter here."
        )

        reg = SkillRegistry()
        _load_skill_md(skill_dir, reg)

        skill = reg.get("no_fm_skill")
        assert isinstance(skill, PromptBasedSkill)
        assert skill.description == "Plugin skill: no_fm_skill"
        meta = getattr(skill, "_plugin_metadata", None)
        # version defaults to "0.1.0", author defaults to "unknown"
        assert meta["version"] == "0.1.0"
        assert meta["author"] == "unknown"

    def test_loads_malformed_frontmatter_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """YAML parse error → skill still loads with fallback + warning logged."""
        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.plugin_loader import _load_skill_md
        from llmwikify.apps.chat.skills.registry import SkillRegistry

        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: : bad yaml\n---\nbody\n"
        )

        reg = SkillRegistry()
        with caplog.at_level("WARNING"):
            _load_skill_md(skill_dir, reg)

        # Skill still registered, just with fallback name
        skill = reg.get("bad")
        assert isinstance(skill, PromptBasedSkill)
        # Warning was emitted for the YAML error
        assert any(
            "YAML parse error" in rec.message for rec in caplog.records
        )


# ── /api/skills endpoint ──────────────────────────────────────────


class TestApiSkillsList:
    def test_list_skills_returns_empty_registry(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reset_default_registry()
        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"count": 0, "skills": []}

    def test_list_skills_returns_registered_skills(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.base import Skill, SkillAction
        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reg = reset_default_registry()

        class MySkill(Skill):
            name = "my_skill"
            description = "a test skill"

            def __init__(self) -> None:
                self.actions = {
                    "do_x": SkillAction(
                        handler=lambda args, ctx: None,
                        description="do x",
                    ),
                    "do_y": SkillAction(
                        handler=lambda args, ctx: None,
                        description="do y",
                    ),
                }
                super().__init__()

        reg.register(MySkill())

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        entry = body["skills"][0]
        assert entry["name"] == "my_skill"
        assert entry["description"] == "a test skill"
        assert entry["action_count"] == 2
        assert sorted(entry["actions"]) == ["do_x", "do_y"]
        # No plugin metadata for built-in skills
        assert "plugin" not in entry

    def test_list_skills_includes_plugin_metadata(self) -> None:
        """PromptBasedSkill with _plugin_metadata exposes plugin.* fields."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reg = reset_default_registry()
        skill = PromptBasedSkill(
            name="plugin_a",
            description="plugin a desc",
            instructions="instructions",
            triggers=["/pa"],
            allowed_tools=["read_file"],
        )
        skill._plugin_metadata = {
            "version": "2.0.0",
            "author": "bob",
            "tags": ["alpha"],
            "license": "Apache-2.0",
            "requires_config": True,
            "source_path": "/home/x/.llmwikify/skills/plugin_a/SKILL.md",
        }
        reg.register(skill)

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        assert resp.status_code == 200
        body = resp.json()
        entry = body["skills"][0]
        assert entry["plugin"]["version"] == "2.0.0"
        assert entry["plugin"]["author"] == "bob"
        assert entry["plugin"]["tags"] == ["alpha"]
        assert entry["plugin"]["license"] == "Apache-2.0"
        assert entry["plugin"]["requires_config"] is True


class TestApiSkillsDetail:
    def test_get_skill_returns_full_manifest(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reg = reset_default_registry()
        skill = PromptBasedSkill(
            name="detail_test",
            description="detailed",
            instructions="instructions body",
            triggers=["/dt"],
        )
        skill._plugin_metadata = {
            "version": "0.5.0",
            "author": "carol",
            "tags": [],
            "license": "",
            "requires_config": False,
            "source_path": "/somewhere/SKILL.md",
        }
        reg.register(skill)

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills/detail_test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "detail_test"
        assert body["description"] == "detailed"
        # Manifest is the SkillManifest.to_dict() shape
        assert body["manifest"]["name"] == "detail_test"
        assert len(body["manifest"]["actions"]) == 1
        # Plugin metadata
        assert body["plugin"]["version"] == "0.5.0"
        assert body["plugin"]["author"] == "carol"

    def test_get_skill_404_for_unknown(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reset_default_registry()
        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills/does_not_exist")
        assert resp.status_code == 404
        assert "does_not_exist" in resp.json()["detail"]

    def test_get_skill_no_plugin_metadata_field_absent(self) -> None:
        """Built-in skill without _plugin_metadata omits the 'plugin' key."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.base import Skill, SkillAction
        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reg = reset_default_registry()

        class BuiltIn(Skill):
            name = "builtin_x"
            description = "builtin"

            def __init__(self) -> None:
                self.actions = {
                    "go": SkillAction(
                        handler=lambda args, ctx: None,
                        description="go",
                    ),
                }
                super().__init__()

        reg.register(BuiltIn())

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills/builtin_x")
        assert resp.status_code == 200
        body = resp.json()
        assert "plugin" not in body


# ── /api/skills survives server startup ────────────────────────────


class TestSkillsRoutesRegistration:
    def test_routes_appear_after_register_routes(self) -> None:
        """End-to-end: register_routes() registers the skills router."""
        from fastapi import FastAPI

        from llmwikify.apps.chat.skills.registry import (
            reset_default_registry,
        )
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        reset_default_registry()
        app = FastAPI()
        _register_skills_routes(app)
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/skills" in paths
        assert "/api/skills/{name}" in paths
