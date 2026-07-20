"""Auto-migration of .wiki-config.yaml to the new v0.41+ layout.

v0.41: LLM / Research / MCP / Chat mutable config moves from per-wiki
``.wiki-config.yaml`` to the global ``~/.llmwikify/llmwikify.json``.

This module detects old configs (those without a ``version`` field or with
``version < "0.41"``) and automatically migrates the deprecated sections
(``llm``, ``research_mutable``, ``chat_mutable``, ``mcp``, ``prompts``)
to the global config file. The original wiki config is backed up as
``.wiki-config.yaml.bak.<timestamp>`` (permanently retained).

Behaviour:
- Default: auto-migrate on every ``llmwikify serve``/``chat`` startup.
- Conflict policy (TTY-detected):
    - Interactive TTY → ask user: ``[g]lobal / [w]iki / [s]kip`` (default ``g``).
    - Non-TTY / batch → use ``auto_resolve`` arg (default ``"global"``).
- ``--dry-run`` (via ``auto_resolve="dry_run"``) → return plan without writes.
- ``--strict`` (via ``auto_resolve="strict"``) → conflict → raise ``RuntimeError``.

Public API:
- :func:`needs_migration` — quick check whether migration is needed.
- :func:`auto_migrate_wiki_config` — main migration entry point.
- :func:`detect_config_version` — read ``version`` field with safe default.
- :class:`MigrationResult` / :class:`MigrationChange` / :class:`MigrationConflict` — result types.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ─── Constants ───────────────────────────────────────────────────────

CURRENT_VERSION = "0.41"

# Per-wiki sections that move to the global config in v0.41+.
# Map: wiki-section name → global-section name.
MIGRATABLE_SECTIONS: dict[str, str] = {
    "llm": "llm",
    "research_mutable": "research_mutable",
    "chat_mutable": "chat_mutable",
    "mcp": "mcp",
    "prompts": "prompts",
}

# Sections that stay in .wiki-config.yaml (no migration).
PRESERVED_SECTIONS: frozenset[str] = frozenset({
    "directories",
    "database",
    "files",
    "wikis",
    "orphan_detection",
    "performance",
    "reference_index",
    "version",
})


# ─── Data classes ────────────────────────────────────────────────────


@dataclass
class MigrationChange:
    """A single key migrated from wiki to global config."""

    section: str
    key: str
    old_value: Any
    new_value: Any
    conflict: bool = False


@dataclass
class MigrationConflict:
    """A conflict between wiki config and existing global config."""

    section: str
    key: str
    global_value: Any
    wiki_value: Any


@dataclass
class MigrationResult:
    """Outcome of an auto-migration attempt."""

    migrated: bool = False
    backup_path: Path | None = None
    changes: list[MigrationChange] = field(default_factory=list)
    conflicts: list[MigrationConflict] = field(default_factory=list)
    resolutions: dict[tuple[str, str], str] = field(default_factory=dict)
    reason: str = ""
    wiki_root: Path | None = None
    dry_run: bool = False

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


# ─── Version detection ──────────────────────────────────────────────


def detect_config_version(config: dict[str, Any]) -> str:
    """Read the ``version`` field from a config dict.

    Returns ``"0.0"`` when the field is missing (pre-v0.41 configs).
    """
    return str(config.get("version", "0.0"))


def _version_tuple(v: str) -> tuple[int, ...]:
    """Convert a version string like ``"0.41"`` to ``(0, 41)`` for comparison."""
    try:
        return tuple(int(p) for p in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def needs_migration(wiki_root: Path) -> bool:
    """Quick check whether ``.wiki-config.yaml`` needs migration."""
    config_path = wiki_root / ".wiki-config.yaml"
    if not config_path.exists():
        return False

    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        # Can't parse — assume needs migration so user gets a chance to fix.
        return True

    if not isinstance(config, dict):
        return True

    current = _version_tuple(detect_config_version(config))
    target = _version_tuple(CURRENT_VERSION)
    return current < target


# ─── Internal helpers ───────────────────────────────────────────────


def _load_yaml(path: Path) -> dict[str, Any] | None:
    """Load a YAML file, returning ``None`` on parse error."""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("[migrate] failed to parse %s: %s", path, exc)
        return None


def _load_global_config() -> dict[str, Any]:
    """Load ``~/.llmwikify/llmwikify.json``. Returns empty dict if missing."""
    # Compute path at call time so monkeypatching HOME works in tests.
    global_path = Path.home() / ".llmwikify" / "llmwikify.json"

    if not global_path.exists():
        return {}
    try:
        return json.loads(global_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[migrate] failed to parse global config: %s", exc)
        return {}


def _save_global_config(config: dict[str, Any]) -> None:
    """Save ``~/.llmwikify/llmwikify.json``."""
    global_path = Path.home() / ".llmwikify" / "llmwikify.json"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _extract_migratable_sections(config: dict[str, Any]) -> dict[str, Any]:
    """Extract sections that should move to global config."""
    return {
        wiki_section: copy.deepcopy(config[wiki_section])
        for wiki_section in MIGRATABLE_SECTIONS
        if wiki_section in config
    }


def _detect_conflicts(
    wiki_sections: dict[str, Any],
    global_cfg: dict[str, Any],
) -> list[MigrationConflict]:
    """Detect per-key conflicts between wiki and global config."""
    conflicts: list[MigrationConflict] = []
    for wiki_section, global_section in MIGRATABLE_SECTIONS.items():
        wiki_section_data = wiki_sections.get(wiki_section, {})
        global_section_data = global_cfg.get(global_section, {})
        if not isinstance(wiki_section_data, dict):
            continue
        for key, wiki_value in wiki_section_data.items():
            if key in global_section_data and global_section_data[key] != wiki_value:
                conflicts.append(
                    MigrationConflict(
                        section=global_section,
                        key=key,
                        global_value=global_section_data[key],
                        wiki_value=wiki_value,
                    )
                )
    return conflicts


def _ask_conflict_resolution(conflict: MigrationConflict, auto_resolve: str) -> str:
    """Resolve a single conflict. Returns ``"global"``, ``"wiki"``, or ``"skip"``.

    Args:
        conflict: The conflict to resolve.
        auto_resolve: One of:
            - ``"interactive"``: prompt the user (default for TTY).
            - ``"global"``: always prefer the existing global value.
            - ``"wiki"``: always prefer the wiki value.
            - ``"skip"``: skip the conflicting key.
            - ``"dry_run"``: return ``"skip"`` (don't write anything).
    """
    if auto_resolve != "interactive":
        return auto_resolve

    if not sys.stdin.isatty():
        # Non-interactive: fall back to default (global priority).
        return "global"

    prompt = (
        f"\n⚠️  Config conflict on {conflict.section}.{conflict.key}\n"
        f"   Global value:    {conflict.global_value!r}\n"
        f"   Wiki value:      {conflict.wiki_value!r}\n"
        f"   Choose [g]lobal / [w]iki / [s]kip (default g): "
    )
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "global"

    if answer == "w":
        return "wiki"
    if answer == "s":
        return "skip"
    return "global"


def _apply_resolutions(
    wiki_sections: dict[str, Any],
    global_cfg: dict[str, Any],
    conflicts: list[MigrationConflict],
    auto_resolve: str,
    dry_run: bool,
) -> tuple[dict[str, Any], list[MigrationChange]]:
    """Apply conflict resolutions and merge wiki into global.

    Returns the merged global config and the list of changes.
    """
    changes: list[MigrationChange] = []
    merged = copy.deepcopy(global_cfg)

    # Resolve conflicts first.
    resolutions: dict[tuple[str, str], str] = {}
    for conflict in conflicts:
        if dry_run:
            resolutions[(conflict.section, conflict.key)] = "skip"
            continue
        choice = _ask_conflict_resolution(conflict, auto_resolve)
        resolutions[(conflict.section, conflict.key)] = choice

    # Apply sections.
    for wiki_section, global_section in MIGRATABLE_SECTIONS.items():
        wiki_data = wiki_sections.get(wiki_section)
        if not isinstance(wiki_data, dict):
            continue
        merged.setdefault(global_section, {})
        for key, wiki_value in wiki_data.items():
            existing = merged[global_section].get(key, _SENTINEL)
            if existing is _SENTINEL:
                # New key — no conflict.
                merged[global_section][key] = copy.deepcopy(wiki_value)
                changes.append(
                    MigrationChange(
                        section=global_section,
                        key=key,
                        old_value=_SENTINEL,
                        new_value=wiki_value,
                        conflict=False,
                    )
                )
            else:
                # Conflict — use resolution.
                choice = resolutions.get((global_section, key), "global")
                if choice == "wiki":
                    merged[global_section][key] = copy.deepcopy(wiki_value)
                    changes.append(
                        MigrationChange(
                            section=global_section,
                            key=key,
                            old_value=existing,
                            new_value=wiki_value,
                            conflict=True,
                        )
                    )
                elif choice == "global":
                    # Keep existing global value; record as no-change.
                    changes.append(
                        MigrationChange(
                            section=global_section,
                            key=key,
                            old_value=existing,
                            new_value=existing,
                            conflict=True,
                        )
                    )
                # else "skip" — do nothing, don't record.

    return merged, changes


_SENTINEL = object()


def _backup_wiki_config(config_path: Path) -> Path:
    """Create a timestamped backup of the wiki config file."""
    timestamp = int(time.time())
    backup_path = config_path.with_suffix(f".yaml.bak.{timestamp}")
    backup_path.write_bytes(config_path.read_bytes())
    return backup_path


def _write_migrated_config(
    config_path: Path,
    config: dict[str, Any],
    migrated_sections: set[str],
) -> None:
    """Write the migrated config back to disk.

    Removes the migrated sections and adds the version field.
    """
    import yaml

    new_config = copy.deepcopy(config)
    for section in migrated_sections:
        new_config.pop(section, None)
    new_config["version"] = CURRENT_VERSION

    config_path.write_text(
        yaml.safe_dump(new_config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


# ─── Public API ─────────────────────────────────────────────────────


def auto_migrate_wiki_config(
    wiki_root: Path,
    *,
    auto_resolve: str = "interactive",
) -> MigrationResult:
    """Auto-migrate ``.wiki-config.yaml`` to the v0.41+ layout.

    Args:
        wiki_root: Root directory of the wiki (where ``.wiki-config.yaml`` lives).
        auto_resolve: Conflict-resolution policy:
            - ``"interactive"`` (default): prompt user if TTY, else ``"global"``.
            - ``"global"`` / ``"wiki"`` / ``"skip"``: non-interactive policy.
            - ``"dry_run"``: do not write anything, return plan only.

    Returns:
        :class:`MigrationResult` describing what happened (or would happen).
    """
    config_path = wiki_root / ".wiki-config.yaml"
    dry_run = auto_resolve == "dry_run"

    result = MigrationResult(wiki_root=wiki_root, dry_run=dry_run)

    if not config_path.exists():
        result.reason = "no_config"
        return result

    config = _load_yaml(config_path)
    if config is None:
        result.reason = "parse_error"
        return result

    current_version = detect_config_version(config)
    if _version_tuple(current_version) >= _version_tuple(CURRENT_VERSION):
        result.reason = "already_migrated"
        return result

    # Extract sections to migrate.
    wiki_sections = _extract_migratable_sections(config)
    if not wiki_sections and current_version != "0.0":
        # Has a version but no migratable sections — just bump version.
        if not dry_run:
            _backup_wiki_config(config_path)
            result.backup_path = config_path.with_suffix(
                f".yaml.bak.{int(time.time())}"
            )
            new_config = copy.deepcopy(config)
            new_config["version"] = CURRENT_VERSION
            import yaml
            config_path.write_text(
                yaml.safe_dump(new_config, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        result.migrated = True
        result.reason = "version_bump_only"
        return result

    if not wiki_sections:
        result.reason = "no_migratable_sections"
        return result

    # Load global config and detect conflicts.
    global_cfg = _load_global_config() if not dry_run else {}
    conflicts = _detect_conflicts(wiki_sections, global_cfg)

    if auto_resolve == "strict" and conflicts:
        raise RuntimeError(
            f"[migrate] {len(conflicts)} conflicts detected in {wiki_root}. "
            "Resolve manually or run without --strict."
        )

    # Apply resolutions and merge.
    merged, changes = _apply_resolutions(
        wiki_sections, global_cfg, conflicts, auto_resolve, dry_run
    )

    result.conflicts = conflicts
    result.changes = changes
    result.resolutions = {
        (c.section, c.key): _ask_conflict_resolution(c, auto_resolve)
        for c in conflicts
    }

    if dry_run:
        result.reason = "dry_run"
        return result

    # Backup before write.
    backup_path = _backup_wiki_config(config_path)
    result.backup_path = backup_path

    # Write merged global config.
    _save_global_config(merged)

    # Update wiki config: remove migrated sections + add version.
    _write_migrated_config(
        config_path,
        config,
        set(wiki_sections.keys()),
    )

    result.migrated = True
    result.reason = "migrated"
    return result


@runtime_checkable
class WikiDiscoveryProvider(Protocol):
    """Protocol for wiki root discovery.

    Implementations scan directories or query registries to find
    wiki roots (directories containing .wiki-config.yaml).
    """

    def discover_wiki_roots(
        self,
        scan_paths: list[str],
        depth: int = 2,
    ) -> list[Path]:
        """Discover wiki roots by scanning directories.

        Args:
            scan_paths: Directories to scan
            depth: Maximum recursion depth

        Returns:
            List of wiki root paths (each containing .wiki-config.yaml).
        """
        ...


def discover_wikis(
    root: Path | None = None,
    provider: WikiDiscoveryProvider | None = None,
    scan_paths: list[str] | None = None,
    depth: int = 2,
) -> list[Path]:
    """Discover wiki roots that may have ``.wiki-config.yaml``.

    Args:
        root: Starting directory for discovery (default: CWD)
        provider: Optional wiki discovery provider (e.g., WikiRegistry).
            Injected by higher layers to avoid foundation→kernel dependency.
        scan_paths: Directories to scan via provider (default: [root])
        depth: Maximum recursion depth for provider scan (default: 2)

    Returns:
        List of wiki_root paths (each containing ``.wiki-config.yaml``).
    """
    root = root or Path.cwd()
    candidates: list[Path] = []

    # 1. CWD
    if (root / ".wiki-config.yaml").exists():
        candidates.append(root)

    # 2. Wiki registry (if provider given)
    if provider is not None:
        try:
            effective_paths = scan_paths or [str(root)]
            for path in provider.discover_wiki_roots(effective_paths, depth):
                if path not in candidates:
                    candidates.append(path)
        except Exception:
            pass  # Registry is optional

    # 3. WIKI_ROOT env var
    env_root = os.environ.get("WIKI_ROOT")
    if env_root:
        p = Path(env_root).expanduser()
        if (p / ".wiki-config.yaml").exists() and p not in candidates:
            candidates.append(p)

    return candidates


__all__ = [
    "CURRENT_VERSION",
    "MIGRATABLE_SECTIONS",
    "PRESERVED_SECTIONS",
    "MigrationChange",
    "MigrationConflict",
    "MigrationResult",
    "WikiDiscoveryProvider",
    "needs_migration",
    "auto_migrate_wiki_config",
    "detect_config_version",
    "discover_wikis",
]
