"""Utility helper functions."""

import re
from datetime import datetime, timezone


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def now() -> str:
    """Get current ISO timestamp."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
