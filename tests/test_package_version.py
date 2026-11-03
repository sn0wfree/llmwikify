"""The package version must have exactly one value, in two places.

``pyproject.toml`` carries the version for the build backend;
``llmwikify/foundation/version.py`` carries it for the runtime
(``llmwikify.__version__``). The release workflow has to update both —
it used to update only ``pyproject.toml``, so a release shipped a
stale ``__version__``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

import llmwikify
from llmwikify.foundation import version as version_module

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")


def _pyproject_version() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_the_two_versions_agree() -> None:
    """The build version and the runtime version must not drift."""
    assert _pyproject_version() == version_module.__version__


def test_the_package_reexports_the_same_version() -> None:
    """``llmwikify.__version__`` is the leaf module's value."""
    assert llmwikify.__version__ == version_module.__version__


def test_the_version_looks_like_a_version() -> None:
    """A malformed version would break the release tag comparison."""
    assert _VERSION_RE.match(version_module.__version__)


def test_the_release_workflow_updates_both_files() -> None:
    """The bump workflow must sed both version sources.

    It used to patch ``pyproject.toml`` only, which left the runtime
    version behind.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "version-bump.yml").read_text(
        encoding="utf-8"
    )
    assert 's/^version = ' in workflow, "pyproject.toml is not patched"
    assert 's/^__version__ = ' in workflow, "foundation/version.py is not patched"
    assert "src/llmwikify/foundation/version.py" in workflow


def test_the_release_workflow_has_no_stale_paths() -> None:
    """``add-paths`` must not name files that do not exist."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "version-bump.yml").read_text(
        encoding="utf-8"
    )
    for path in ("src/llmwikify/_version.py", "src/llmwikify/__init__.py"):
        assert path not in workflow, f"{path} is named in the workflow but does not exist"


@pytest.mark.parametrize(
    "path",
    [
        "src/llmwikify/foundation/version.py",
        "pyproject.toml",
    ],
)
def test_the_version_sources_exist(path: str) -> None:
    """Both sources are real files."""
    assert (REPO_ROOT / path).exists()
