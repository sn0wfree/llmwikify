"""Maintenance configuration — ``maintenance`` section of ``~/.llmwikify/llmwikify.json``."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH: Path = Path.home() / ".llmwikify" / "llmwikify.json"


@dataclass
class AutoIngestConfig:
    """Track A: raw/ new-file auto ingest + LLM page write."""

    enabled: bool = True
    write_mode: str = "auto"  # "auto" (write directly) | "proposal"
    fallback_to_proposal: bool = True
    max_concurrent_per_wiki: int = 1
    debounce_seconds: float = 2.0


@dataclass
class GapFillerConfig:
    """Track B: lint-driven gap detection + proposal-based filling."""

    enabled: bool = True
    max_per_cycle: int = 5
    min_priority: int = 30
    auto_approve_mechanical: bool = True


@dataclass
class MaintenanceConfig:
    """Root config for the self-maintenance subsystem."""

    enabled: bool = True
    auto_ingest: AutoIngestConfig = field(default_factory=AutoIngestConfig)
    gap_filler: GapFillerConfig = field(default_factory=GapFillerConfig)
    lint_interval_seconds: float = 86400.0
    gaps_interval_seconds: float = 604800.0
    db_maintenance_interval_seconds: float = 604800.0


def load_maintenance_config(config_path: Path | None = None) -> MaintenanceConfig:
    """Load the ``maintenance`` section of ``~/.llmwikify/llmwikify.json``.

    Missing file / section / individual keys all fall back to defaults.
    """
    path = config_path or CONFIG_PATH
    cfg = MaintenanceConfig()
    if not path.exists():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return cfg

    section = data.get("maintenance", {})
    if not isinstance(section, dict):
        logger.warning("maintenance section is not a dict, using defaults")
        return cfg

    cfg.enabled = bool(section.get("enabled", cfg.enabled))
    cfg.lint_interval_seconds = float(
        section.get("lint_interval_seconds", cfg.lint_interval_seconds),
    )
    cfg.gaps_interval_seconds = float(
        section.get("gaps_interval_seconds", cfg.gaps_interval_seconds),
    )
    cfg.db_maintenance_interval_seconds = float(
        section.get(
            "db_maintenance_interval_seconds",
            cfg.db_maintenance_interval_seconds,
        ),
    )

    ai = section.get("auto_ingest", {})
    if isinstance(ai, dict):
        cfg.auto_ingest.enabled = bool(ai.get("enabled", cfg.auto_ingest.enabled))
        cfg.auto_ingest.write_mode = str(ai.get("write_mode", cfg.auto_ingest.write_mode))
        cfg.auto_ingest.fallback_to_proposal = bool(
            ai.get("fallback_to_proposal", cfg.auto_ingest.fallback_to_proposal),
        )
        cfg.auto_ingest.max_concurrent_per_wiki = int(
            ai.get("max_concurrent_per_wiki", cfg.auto_ingest.max_concurrent_per_wiki),
        )
        cfg.auto_ingest.debounce_seconds = float(
            ai.get("debounce_seconds", cfg.auto_ingest.debounce_seconds),
        )

    gf = section.get("gap_filler", {})
    if isinstance(gf, dict):
        cfg.gap_filler.enabled = bool(gf.get("enabled", cfg.gap_filler.enabled))
        cfg.gap_filler.max_per_cycle = int(
            gf.get("max_per_cycle", cfg.gap_filler.max_per_cycle),
        )
        cfg.gap_filler.min_priority = int(
            gf.get("min_priority", cfg.gap_filler.min_priority),
        )
        cfg.gap_filler.auto_approve_mechanical = bool(
            gf.get("auto_approve_mechanical", cfg.gap_filler.auto_approve_mechanical),
        )

    return cfg


def to_dict(cfg: MaintenanceConfig) -> dict[str, Any]:
    """Serialize config back to a dict (for /api/maintenance/status)."""
    return {
        "enabled": cfg.enabled,
        "auto_ingest": {
            "enabled": cfg.auto_ingest.enabled,
            "write_mode": cfg.auto_ingest.write_mode,
            "fallback_to_proposal": cfg.auto_ingest.fallback_to_proposal,
            "max_concurrent_per_wiki": cfg.auto_ingest.max_concurrent_per_wiki,
            "debounce_seconds": cfg.auto_ingest.debounce_seconds,
        },
        "gap_filler": {
            "enabled": cfg.gap_filler.enabled,
            "max_per_cycle": cfg.gap_filler.max_per_cycle,
            "min_priority": cfg.gap_filler.min_priority,
            "auto_approve_mechanical": cfg.gap_filler.auto_approve_mechanical,
        },
        "lint_interval_seconds": cfg.lint_interval_seconds,
        "gaps_interval_seconds": cfg.gaps_interval_seconds,
        "db_maintenance_interval_seconds": cfg.db_maintenance_interval_seconds,
    }
