"""Shared patterns for matching concept names in wiki text.

The lint rule that detects missing cross-references and the maintenance
code that inserts them must agree on what "the page mentions this
concept" means — otherwise the rule reports a gap the fixer cannot
locate, or (worse) the fixer inserts a link the rule still considers
missing. Keeping one implementation in ``kernel`` makes that impossible:
``apps`` may import ``kernel``, never the other way round.

Two shapes must be told apart:

* a concept mentioned on its own — ``Risk Parity``
* the same concept written as a path — ``concepts/Risk Parity``

Matching the bare title inside a path would split it in half
(``concepts/[[concepts/Risk Parity]]``), so the title pattern refuses to
match next to a slash; the path pattern matches the whole path instead.
"""

from __future__ import annotations

import re


def concept_pattern(name: str) -> re.Pattern:
    """Pattern for a concept name standing on its own (case-insensitive).

    Uses lookarounds rather than ``\\b`` because ``\\b`` requires a word
    character at the boundary: a concept ending in punctuation ("C++")
    would never match, since the trailing ``+`` is not a word character.
    The slash is excluded so a name inside a path (``concepts/Foo``) is
    not matched as a bare title.
    """
    return re.compile(r"(?<![/\w])" + re.escape(name) + r"(?![/\w])", re.IGNORECASE)


def path_pattern(path: str) -> re.Pattern:
    """Pattern for a concept written as a full path (case-insensitive)."""
    return re.compile(r"(?<!\w)" + re.escape(path) + r"(?!\w)", re.IGNORECASE)


__all__ = ["concept_pattern", "path_pattern"]
