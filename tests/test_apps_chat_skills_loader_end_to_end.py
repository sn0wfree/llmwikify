"""Phase 11-F3: end-to-end plugin loader integration tests.

These tests exercise the full pipeline:
  SKILL.md file → plugin_loader → SkillRegistry → /api/skills

Compared to F1 (which tests ``parse_skill_frontmatter`` in isolation)
and F2 (which tests ``/api/skills`` with synthetic Skill instances),
F3 patches ``PLUGIN_DIR`` to point at a tmp directory so we can drop
real SKILL.md files and watch them flow through the loader.

Covers back-compat behavior:

  - Body-only SKILL.md (no frontmatter) loads with fallback name
  - Mixed-version skills (some with version, some without) all register
  - Malformed YAML doesn't kill the load — bad skill gets a fallback,
    the other skills in the same directory still load
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# ── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def fake_plugin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``llmwikify.apps.chat.skills.plugin_loader.PLUGIN_DIR`` at tmp_path.

    Returns the tmp_path so individual tests can drop files into it.
    """
    from llmwikify.apps.chat.skills import plugin_loader

    monkeypatch.setattr(plugin_loader, "PLUGIN_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def reset_registry():
    """Each test gets a fresh default registry (skills don't leak across tests)."""
    from llmwikify.apps.chat.skills.registry import reset_default_registry

    reg = reset_default_registry()
    yield reg


# ── full pipeline: file → registry → /api/skills ─────────────────


class TestEndToEndPipeline:
    def test_body_only_skill_appears_in_api(
        self, fake_plugin_dir: Path
    ) -> None:
        """No frontmatter → fallback name from dir, all fields default."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.base import PromptBasedSkill
        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        skill_dir = fake_plugin_dir / "body_only"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Body only\n\nNo frontmatter here.\n"
        )

        loaded = load_plugins(default_registry())
        assert loaded == 1

        skill = default_registry().get("body_only")
        assert isinstance(skill, PromptBasedSkill)
        # Plugin metadata reflects default frontmatter values
        meta = skill._plugin_metadata
        assert meta["version"] == "0.1.0"
        assert meta["author"] == "unknown"
        assert meta["requires_config"] is False

        # /api/skills reflects the loaded skill
        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        assert resp.status_code == 200
        body = resp.json()
        names = [s["name"] for s in body["skills"]]
        assert "body_only" in names
        entry = next(s for s in body["skills"] if s["name"] == "body_only")
        assert entry["plugin"]["version"] == "0.1.0"

    def test_full_frontmatter_skill_exposes_all_fields(
        self, fake_plugin_dir: Path
    ) -> None:
        """All frontmatter fields surface in /api/skills."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        skill_dir = fake_plugin_dir / "full_meta"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent(
                """\
                ---
                name: full_meta
                description: meta-heavy plugin
                version: 3.1.4
                author: dave
                triggers:
                  - /meta
                  - "/meta, /m"
                allowed-tools:
                  - read_file
                  - web_search
                tags:
                  - meta
                  - heavy
                license: BSD-3-Clause
                requires-config: true
                ---
                # Full Meta Plugin

                Instructions for the LLM follow.
                """
            )
        )

        load_plugins(default_registry())

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        # Detail endpoint exposes everything
        resp = client.get("/api/skills/full_meta")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "full_meta"
        assert body["description"] == "meta-heavy plugin"
        plugin = body["plugin"]
        assert plugin["version"] == "3.1.4"
        assert plugin["author"] == "dave"
        assert plugin["tags"] == ["meta", "heavy"]
        assert plugin["license"] == "BSD-3-Clause"
        assert plugin["requires_config"] is True
        # source_path points at the SKILL.md we wrote
        assert "full_meta" in plugin["source_path"]
        assert plugin["source_path"].endswith("SKILL.md")

    def test_multiple_skills_in_one_dir(
        self, fake_plugin_dir: Path
    ) -> None:
        """Several skills load side-by-side; no cross-contamination."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        # Two plugin dirs
        for name, version in [("alpha", "1.0.0"), ("beta", "2.0.0")]:
            sd = fake_plugin_dir / name
            sd.mkdir()
            (sd / "SKILL.md").write_text(
                f"---\nname: {name}\nversion: {version}\n---\nbody\n"
            )

        loaded = load_plugins(default_registry())
        assert loaded == 2

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        body = resp.json()
        names = sorted(s["name"] for s in body["skills"])
        assert names == ["alpha", "beta"]

        # Each carries its own version
        alpha = next(s for s in body["skills"] if s["name"] == "alpha")
        beta = next(s for s in body["skills"] if s["name"] == "beta")
        assert alpha["plugin"]["version"] == "1.0.0"
        assert beta["plugin"]["version"] == "2.0.0"

    def test_malformed_skill_does_not_block_others(
        self, fake_plugin_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One bad skill → fallback load + warning; the good ones still register."""
        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry

        # Good skill
        good = fake_plugin_dir / "good"
        good.mkdir()
        (good / "SKILL.md").write_text(
            "---\nname: good\nversion: 1.0\n---\nbody\n"
        )
        # Bad skill with malformed YAML
        bad = fake_plugin_dir / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text(
            "---\nname: : bad yaml\n---\nbody\n"
        )

        with caplog.at_level("WARNING"):
            loaded = load_plugins(default_registry())

        # Both still loaded (bad → fallback "bad")
        assert loaded == 2
        assert default_registry().get("good") is not None
        # bad falls back to dir name
        bad_skill = default_registry().get("bad")
        assert bad_skill is not None
        # Warning was logged for the YAML error
        assert any(
            "YAML parse error" in rec.message for rec in caplog.records
        )

    def test_comma_separated_triggers_split_with_warning(
        self, fake_plugin_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A trigger string with commas → split into list + warning."""
        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry

        sd = fake_plugin_dir / "comma_t"
        sd.mkdir()
        (sd / "SKILL.md").write_text(
            '---\nname: comma_t\ntriggers: "/a, /b, /c"\n---\nbody\n'
        )

        with caplog.at_level("WARNING"):
            load_plugins(default_registry())

        skill = default_registry().get("comma_t")
        assert skill is not None
        actions = list(skill.actions.values())
        assert actions[0].triggers == ["/a", "/b", "/c"]
        # The split warning made it to the logger
        assert any("triggers" in rec.message for rec in caplog.records)

    def test_python_skill_does_not_get_plugin_metadata(
        self, fake_plugin_dir: Path
    ) -> None:
        """Code-based .py plugin skills skip the frontmatter path → no _plugin_metadata."""
        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry

        py_path = fake_plugin_dir / "code_skill.py"
        py_path.write_text(
            textwrap.dedent(
                """\
                from llmwikify.apps.chat.skills.base import Skill, SkillAction

                class CodeSkill(Skill):
                    name = "code_skill"
                    description = "code-based"

                    def __init__(self):
                        self.actions = {
                            "go": SkillAction(
                                handler=lambda args, ctx: None,
                                description="go",
                            )
                        }
                        super().__init__()

                skill = CodeSkill()
                """
            )
        )

        loaded = load_plugins(default_registry())
        assert loaded == 1
        skill = default_registry().get("code_skill")
        assert skill is not None
        # No _plugin_metadata for code-based skills
        assert not hasattr(skill, "_plugin_metadata") or getattr(
            skill, "_plugin_metadata", None
        ) is None


# ── load_plugins return value ────────────────────────────────────


class TestLoadPluginsReturn:
    def test_load_plugins_returns_zero_when_dir_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PLUGIN_DIR not existing → return 0, don't raise."""
        from llmwikify.apps.chat.skills import plugin_loader
        from llmwikify.apps.chat.skills.registry import default_registry

        nonexistent = Path("/tmp/does/not/exist/at/all")
        monkeypatch.setattr(plugin_loader, "PLUGIN_DIR", nonexistent)

        loaded = plugin_loader.load_plugins(default_registry())
        assert loaded == 0

    def test_load_plugins_skips_underscore_prefix_for_py_files(
        self, fake_plugin_dir: Path
    ) -> None:
        """``_*.py`` files are skipped (Python convention) but ``_*`` dirs are not.

        Documenting the current behavior: ``plugin_loader`` only filters
        ``_`` prefix for ``.py`` files; SKILL.md directories are scanned
        regardless of name. (This matches the original pre-Phase 11 code
        — changing it would be a semantic change worth a separate decision.)
        """
        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry

        # Visible dir
        ok = fake_plugin_dir / "ok"
        ok.mkdir()
        (ok / "SKILL.md").write_text("body\n")
        # Hidden .py file (skipped)
        hidden_py = fake_plugin_dir / "_hidden.py"
        hidden_py.write_text("# not a skill\n")

        loaded = load_plugins(default_registry())
        assert loaded == 1
        assert default_registry().get("ok") is not None
        assert default_registry().get("_hidden") is None


# ── /api/skills JSON shape stability ─────────────────────────────


class TestApiSkillsJsonShape:
    def test_list_response_is_json_serializable(
        self, fake_plugin_dir: Path
    ) -> None:
        """The whole /api/skills payload round-trips through json.dumps."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from llmwikify.apps.chat.skills.plugin_loader import load_plugins
        from llmwikify.apps.chat.skills.registry import default_registry
        from llmwikify.interfaces.server.http.routes import (
            _register_skills_routes,
        )

        sd = fake_plugin_dir / "jsonable"
        sd.mkdir()
        (sd / "SKILL.md").write_text(
            "---\nname: jsonable\nversion: 1.0\n---\nbody\n"
        )
        load_plugins(default_registry())

        app = FastAPI()
        _register_skills_routes(app)
        client = TestClient(app)

        resp = client.get("/api/skills")
        body = resp.json()
        # Round-trip through json to ensure no non-serializable fields
        encoded = json.dumps(body)
        decoded = json.loads(encoded)
        assert decoded == body
