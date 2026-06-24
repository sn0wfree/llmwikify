"""Pipeline configuration — workspace-level settings."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceConfig:
    """Configuration for a pipeline workspace.

    Attributes:
        workspace_path: Root directory for pipeline I/O.
        alpha_indices: List of alpha index names to process.
        max_workers: Max parallel workers (reserved for future use).
        timeout_s: Per-stage timeout in seconds.
    """

    workspace_path: Path = field(default_factory=lambda: Path("."))
    alpha_indices: list[str] = field(default_factory=list)
    max_workers: int = 1
    timeout_s: float = 300.0
