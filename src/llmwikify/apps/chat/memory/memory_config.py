"""memory_config — Phase 6 config helpers.

Reads ~/.llmwikify/memory_config.json if present, otherwise falls
back to defaults. Lets users tune consolidation threshold, dream
schedule, etc. without code changes.

Default config:
    {
      "consolidation": {
        "trigger_token_threshold": 4000,
        "keep_recent_messages": 8,
        "min_consolidation_interval_sec": 60.0,
        "summary_max_tokens": 1024,
        "enable_md_write": true
      },
      "dream": {
        "enabled": true,
        "cron_expression": "0 3 * * *",
        "max_batch_size": 20,
        "timeout_seconds": 300.0
      }
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_CONFIG_FILENAME = "memory_config.json"


@dataclass
class MemoryConfig:
    """Parsed ~/.llmwikify/memory_config.json."""

    consolidation: dict[str, Any] = field(default_factory=lambda: {
        "trigger_token_threshold": 4000,
        "keep_recent_messages": 8,
        "min_consolidation_interval_sec": 60.0,
        "summary_max_tokens": 1024,
        "enable_md_write": True,
    })
    dream: dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "cron_expression": "0 3 * * *",
        "max_batch_size": 20,
        "timeout_seconds": 300.0,
    })


def load_memory_config(data_dir: Path | str) -> MemoryConfig:
    """Load memory config from ``<data_dir>/memory_config.json``.

    Returns defaults if the file is missing or malformed.
    Never raises — logs warnings and returns defaults on parse errors.
    """
    config_path = Path(data_dir) / DEFAULT_CONFIG_FILENAME
    if not config_path.exists():
        return MemoryConfig()

    try:
        text = config_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "memory_config: failed to load %s: %s. Using defaults.",
            config_path, e,
        )
        return MemoryConfig()

    cfg = MemoryConfig()
    if isinstance(data, dict):
        if "consolidation" in data and isinstance(data["consolidation"], dict):
            cfg.consolidation.update(data["consolidation"])
        if "dream" in data and isinstance(data["dream"], dict):
            cfg.dream.update(data["dream"])
    return cfg


def write_default_memory_config(data_dir: Path | str) -> Path:
    """Write the default config file if it doesn't exist.

    Returns the path written. Useful for first-run setup.
    """
    config_path = Path(data_dir) / DEFAULT_CONFIG_FILENAME
    if config_path.exists():
        return config_path
    cfg = MemoryConfig()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(asdict(cfg), indent=2),
        encoding="utf-8",
    )
    logger.info("memory_config: wrote default to %s", config_path)
    return config_path


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "MemoryConfig",
    "load_memory_config",
    "write_default_memory_config",
]
