"""Skill frontmatter parsing layer (Phase 11 — borrowed from nanobot).

借鉴 nanobot v0.2.1 ``skills/loader.py`` 的 YAML frontmatter 解析思路：

  - 把 SKILL.md 的 ``---`` 头块抽成强类型 ``SkillFrontmatter`` dataclass
  - 解析失败时返回降级 frontmatter 而非 raise，方便 plugin_loader 跳过坏 skill
  - 暴露 ``version`` / ``author`` / ``tags`` 等附加元数据给 /api/skills

设计目标：

  - **向后兼容** — 没有 frontmatter 时返回 ``SkillFrontmatter(name=...)``
    用 skill_dir.name 兜底，旧 SKILL.md 文件不破坏
  - **错误隔离** — YAML 解析错误、缺字段、字段类型错都不 raise，
    而是返回原值 + ``warnings`` 列表，调用方决定是否 skip
  - **纯函数** — ``parse_skill_frontmatter`` 是 pure function，
    无副作用，可单测
  - **职责单一** — 只管 SKILL.md → SkillFrontmatter + body，
    不负责注册到 registry（那是 plugin_loader 的活）

新字段含义（与 Agent Skills standard 兼容）：

  - ``name``       — 技能 ID（fallback: skill_dir.name）
  - ``description`` — LLM 可见描述
  - ``version``    — SemVer 字符串（默认 ``"0.1.0"``）
  - ``author``     — 字符串（默认 ``"unknown"``）
  - ``triggers``   — 触发字符串列表（沿用 plugin_loader 字段名）
  - ``allowed_tools`` — 工具白名单（沿用 plugin_loader 字段名）
  - ``tags``       — 自定义标签（plugin_loader 暂未消费，留给未来）
  - ``license``    — 可选（默认 ``""``）
  - ``requires_config`` — 是否需要 skill-specific 配置（默认 ``False``）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SkillFrontmatter:
    """Parsed SKILL.md frontmatter.

    Attributes
    ----------
    name
        Skill identifier. Required for registration uniqueness;
        falls back to ``skill_dir.name`` if not in frontmatter.
    description
        Human/LLM-readable description. Used in the LLM tool manifest.
    version
        SemVer-ish string (e.g. ``"0.1.0"``). Surfaced in
        ``/api/skills`` and the skill manifest so operators can
        see at a glance which version is loaded.
    author
        Free-form author string. Default ``"unknown"`` for plugin
        skills without metadata.
    triggers
        Command strings that invoke this skill (e.g. ``["/study"]``).
        Mirrors the existing ``plugin_loader`` semantics.
    allowed_tools
        Tool whitelist for prompt-based skills. Empty list = no
        restriction.
    tags
        Free-form labels for filtering. Plugin loader doesn't
        consume them today; reserved for future grouping.
    license
        Optional license identifier (SPDX-ish).
    requires_config
        If True, the skill expects runtime config (e.g. API keys)
        before it can execute. Plugin loader emits a warning if
        no config is provided.
    warnings
        Non-fatal parse issues (missing fields, wrong types,
        unparseable YAML). Empty list means a clean parse.
    """

    name: str = ""
    description: str = ""
    version: str = "0.1.0"
    author: str = "unknown"
    triggers: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    license: str = ""
    requires_config: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for /api/skills and logs."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "triggers": list(self.triggers),
            "allowed_tools": list(self.allowed_tools),
            "tags": list(self.tags),
            "license": self.license,
            "requires_config": self.requires_config,
        }


@dataclass
class SkillMarkdown:
    """Result of parsing a SKILL.md file.

    Attributes
    ----------
    frontmatter
        Parsed ``SkillFrontmatter``. Falls back to defaults if the
        file has no frontmatter block.
    body
        The markdown body (after the frontmatter), stripped of
        leading/trailing whitespace. This is what
        ``PromptBasedSkill.instructions`` receives.
    source_path
        Absolute path of the SKILL.md that was parsed. Useful for
        debugging (``/api/skills`` can show "loaded from ...").
    """

    frontmatter: SkillFrontmatter
    body: str
    source_path: Path


def _coerce_str_list(value: Any, field_name: str, warnings: list[str]) -> list[str]:
    """Best-effort coerce a value to ``list[str]`` with a warning if not.

    Plugin authors occasionally write a comma-separated string
    instead of a YAML list. Be tolerant: split on commas and warn,
    rather than failing the whole load.
    """
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            else:
                warnings.append(
                    f"{field_name}: non-string item {item!r} dropped"
                )
        return out
    if isinstance(value, str):
        warnings.append(
            f"{field_name}: expected list, got string — splitting on commas"
        )
        return [s.strip() for s in value.split(",") if s.strip()]
    warnings.append(
        f"{field_name}: expected list, got {type(value).__name__}; using empty"
    )
    return []


def _coerce_str(value: Any, field_name: str, default: str, warnings: list[str]) -> str:
    """Best-effort coerce a value to ``str`` with a warning if not.

    Strings pass through. ``None`` falls back to ``default`` silently
    (the schema treats absence as default). Other scalar types
    (int / float / bool) are stringified with a warning — they're
    almost certainly author mistakes (e.g. ``version: 1.0``
    instead of ``version: "1.0"``) but we don't want to fail the
    whole skill load over a typo.

    Lists / dicts are NOT stringified — they'd produce unreadable
    output. They fall back to default with a louder warning.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float, bool)):
        warnings.append(
            f"{field_name}: expected string, got {type(value).__name__} "
            f"({value!r}); coerced to string"
        )
        return str(value)
    warnings.append(
        f"{field_name}: expected string, got {type(value).__name__}; "
        f"using default {default!r}"
    )
    return default


def _coerce_bool(value: Any, field_name: str, default: bool, warnings: list[str]) -> bool:
    """Best-effort coerce a value to ``bool`` with a warning if not."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    warnings.append(
        f"{field_name}: expected bool, got {type(value).__name__}; "
        f"using default {default!r}"
    )
    return default


def parse_skill_frontmatter(
    raw: str,
    *,
    fallback_name: str,
    source_path: Path | None = None,
) -> SkillMarkdown:
    """Parse a SKILL.md file's content into ``SkillMarkdown``.

    Parameters
    ----------
    raw
        Full file content (including any ``---`` frontmatter block).
    fallback_name
        Skill name to use when ``name`` is missing from frontmatter
        (usually the parent directory name).
    source_path
        Optional path recorded in the result for debugging. Not
        read; only stored.

    Returns
    -------
    SkillMarkdown
        Frontmatter (with warnings if any) + body + source path.
        Never raises — all parse failures degrade gracefully.
    """
    warnings: list[str] = []
    meta: dict[str, Any] = {}
    body = raw

    if raw.startswith("---"):
        # YAML frontmatter is delimited by ``---`` on its own lines.
        # Use ``split(..., maxsplit=2)`` so that a ``---`` inside the
        # body doesn't accidentally truncate it.
        parts = raw.split("\n---\n", 1)
        if len(parts) == 2:
            header = parts[0][len("---"):].lstrip("\n")
            body = parts[1].strip()
            try:
                parsed = yaml.safe_load(header)
                if isinstance(parsed, dict):
                    meta = parsed
                elif parsed is None:
                    pass
                else:
                    warnings.append(
                        f"frontmatter is a {type(parsed).__name__}, not a mapping"
                    )
            except yaml.YAMLError as e:
                warnings.append(f"YAML parse error: {e}")
        else:
            warnings.append(
                "file starts with --- but no closing --- found; treating as body-only"
            )

    fm = SkillFrontmatter(
        name=_coerce_str(
            meta.get("name"), "name", fallback_name, warnings
        ),
        description=_coerce_str(
            meta.get("description"),
            "description",
            f"Plugin skill: {fallback_name}",
            warnings,
        ),
        version=_coerce_str(
            meta.get("version"), "version", "0.1.0", warnings
        ),
        author=_coerce_str(
            meta.get("author"), "author", "unknown", warnings
        ),
        triggers=_coerce_str_list(
            meta.get("triggers", []), "triggers", warnings
        ),
        allowed_tools=_coerce_str_list(
            meta.get("allowed-tools", []), "allowed_tools", warnings
        ),
        tags=_coerce_str_list(
            meta.get("tags", []), "tags", warnings
        ),
        license=_coerce_str(
            meta.get("license"), "license", "", warnings
        ),
        requires_config=_coerce_bool(
            meta.get("requires-config", False),
            "requires_config",
            False,
            warnings,
        ),
        warnings=warnings,
    )

    return SkillMarkdown(
        frontmatter=fm,
        body=body,
        source_path=source_path or Path(""),
    )


__all__ = [
    "SkillFrontmatter",
    "SkillMarkdown",
    "parse_skill_frontmatter",
]
