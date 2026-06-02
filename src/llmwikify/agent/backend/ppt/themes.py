"""PPT Generator - Preset theme configurations."""

from typing import Dict, List
from .schema import Theme, ThemeColors


# 8 preset themes
THEMES: Dict[str, Theme] = {
    "professional": Theme(
        name="professional",
        label="Professional",
        colors=ThemeColors(
            primary="#1a73e8",
            secondary="#5f6368",
            background="#ffffff",
            text="#202124",
            accent="#ea4335",
        ),
    ),
    "modern": Theme(
        name="modern",
        label="Modern",
        colors=ThemeColors(
            primary="#6366f1",
            secondary="#8b5cf6",
            background="#0f172a",
            text="#f8fafc",
            accent="#06b6d4",
        ),
    ),
    "minimal": Theme(
        name="minimal",
        label="Minimal",
        colors=ThemeColors(
            primary="#18181b",
            secondary="#71717a",
            background="#ffffff",
            text="#18181b",
            accent="#a1a1aa",
        ),
    ),
    "nature": Theme(
        name="nature",
        label="Nature",
        colors=ThemeColors(
            primary="#16a34a",
            secondary="#22c55e",
            background="#f0fdf4",
            text="#14532d",
            accent="#86efac",
        ),
    ),
    "warm": Theme(
        name="warm",
        label="Warm",
        colors=ThemeColors(
            primary="#ea580c",
            secondary="#f97316",
            background="#fff7ed",
            text="#7c2d12",
            accent="#fdba74",
        ),
    ),
    "dark": Theme(
        name="dark",
        label="Dark",
        colors=ThemeColors(
            primary="#3b82f6",
            secondary="#60a5fa",
            background="#111827",
            text="#f9fafb",
            accent="#fbbf24",
        ),
    ),
    "academic": Theme(
        name="academic",
        label="Academic",
        colors=ThemeColors(
            primary="#1e3a5f",
            secondary="#2563eb",
            background="#f8fafc",
            text="#1e293b",
            accent="#dc2626",
        ),
    ),
    "creative": Theme(
        name="creative",
        label="Creative",
        colors=ThemeColors(
            primary="#d946ef",
            secondary="#a855f7",
            background="#fdf4ff",
            text="#701a75",
            accent="#f472b6",
        ),
    ),
}


def get_theme(name: str) -> Theme:
    """Get theme by name, fallback to professional if not found."""
    return THEMES.get(name, THEMES["professional"])


def list_themes() -> List[Theme]:
    """List all available themes."""
    return list(THEMES.values())
