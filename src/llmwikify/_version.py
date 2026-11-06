"""Single source of truth for the package version.

Leaf module: imports nothing, so lower layers (``kernel`` / ``foundation``)
can read the version without importing the ``llmwikify`` package root.
Importing the root from inside ``kernel`` creates a package-level import
cycle (``llmwikify -> kernel -> ... -> status -> llmwikify``).

``llmwikify.__version__`` re-exports this value; ``pyproject.toml``
carries its own copy, checked by ``TestVersionConsistency``.
"""

__version__ = "0.40.6"

__all__ = ["__version__"]
