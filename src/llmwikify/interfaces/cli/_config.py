"""Config loading for the CLI.

Phase 1 #2 / C1 — extract the wiki_root + config loading logic
that currently lives at the bottom of ``cli/commands.py:2153-2165``
into a reusable module.

The current logic:

    wiki_root = Path(os.environ.get('WIKI_ROOT', Path.cwd()))
    config: dict[str, Any] = {}
    config_file = wiki_root / '.wiki-config.yaml'
    if config_file.exists():
        try:
            import yaml
            config = yaml.safe_load(config_file.read_text()) or {}
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", config_file, e)
    cli = WikiCLI(wiki_root, config=config)

This module exposes ``load_cli_config(wiki_root=None) -> tuple[Path, dict]``
that performs the same steps, with one small improvement: it
returns both the resolved wiki_root and the config dict, so the
caller doesn't have to repeat the env-var lookup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_cli_config(wiki_root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Load wiki_root and merged config dict for the CLI.

    Args:
        wiki_root: Explicit wiki root. If None, the WIKI_ROOT env
            var is consulted; if that's also unset, the current
            working directory is used.

    Returns:
        A 2-tuple ``(resolved_wiki_root, config_dict)`` where
        ``config_dict`` is the parsed contents of
        ``.wiki-config.yaml`` (or ``{}`` if the file is missing
        or unparseable — a warning is logged in the latter case).

    The returned config dict is suitable for passing to
    ``WikiCLI(wiki_root, config=...)`` or to a future Command's
    ``run(args, wiki_root, config)`` method.
    """
    if wiki_root is None:
        env_root = os.environ.get("WIKI_ROOT")
        wiki_root = Path(env_root) if env_root else Path.cwd()

    config: dict[str, Any] = {}
    config_file = wiki_root / ".wiki-config.yaml"
    if config_file.exists():
        try:
            import yaml  # optional dep — only required if config file exists

            config = yaml.safe_load(config_file.read_text()) or {}
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", config_file, e)
            config = {}

    return wiki_root, config
