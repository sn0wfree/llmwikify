"""Shared utilities for reproduction module.

Canonical slug generation and frontmatter parsing used across
extract_paper, extract_factors, factor, and strategy modules.
"""

from __future__ import annotations

import re
from typing import Any

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name.

    Rules:
    - Lowercase
    - Replace spaces and underscores with hyphens
    - Strip all characters except [a-z0-9-]
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    - Max 80 characters
    """
    slug = name.lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Pull YAML-ish key:value frontmatter out of a markdown page.

    Handles:
    - Simple scalar values: ``key: value``
    - Lists: ``key: [a, b, c]``
    - Dicts: ``key: {k1: v1, k2: v2}``
    """
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [
                v.strip().strip('"').strip("'")
                for v in inner.split(",")
                if v.strip()
            ]
        elif value.startswith("{") and value.endswith("}"):
            inner = value[1:-1].strip()
            as_dict: dict[str, Any] = {}
            for pair in inner.split(","):
                if ":" not in pair:
                    continue
                k, _, v = pair.partition(":")
                as_dict[k.strip()] = v.strip().strip('"').strip("'")
            out[key] = as_dict
        else:
            out[key] = value.strip('"').strip("'")
    return out


__all__ = ["generate_slug", "parse_frontmatter", "FRONTMATTER_RE"]
