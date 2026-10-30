"""Single source of truth for the package version.

Kept in a leaf module so that ``kernel`` can read the version without
importing the package root — ``llmwikify/__init__.py`` imports
``kernel``, so any ``from llmwikify import __version__`` inside kernel
closes an import cycle and violates the layer direction
(kernel must not depend on the package root; see
``docs/designs/code-reuse-optimization.md`` R5).
"""

from __future__ import annotations

__version__ = "0.40.6"

__all__ = ["__version__"]
