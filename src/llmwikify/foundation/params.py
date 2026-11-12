"""Parameter registry — the single source of truth for every tunable default.

Layer: L1 (foundation). No deps on apps/kernel/interfaces.

Every knob llmwikify exposes is declared **once** here. ``foundation.config``
(the config hub) resolves a parameter through the documented three scopes:

    per-wiki ``.wiki-config.yaml``  >  global ``~/.llmwikify/llmwikify.json``
    >  this registry

The registry replaces the previous scattered defaults: the embedded
``DEFAULT_CONFIG`` dict, ``foundation/templates/llmwikify.default.json``,
``apps/research/config_defaults.yaml`` and
``apps/research/six_step_config_defaults.yaml`` all carried their own copy,
and the same concept sometimes had six different default values (see
``docs/designs/parameter-tiers.md`` §6.1).

Coverage is growing incrementally — see ``tests/test_foundation_params.py``
for the current numbers and the ratchet that keeps it from shrinking.
Keys not yet declared here still resolve through their original
definition; the registry becomes authoritative as each group lands.

Key naming
----------
Dotted paths matching the config file shape: ``"llm.timeout"``,
``"chat_mutable.max_chat_rounds"``, ``"wiki.similarity_threshold"``.
The prefix is the *scope section* the key is written under in
``~/.llmwikify/llmwikify.json`` (or ``.wiki-config.yaml`` for wiki-scoped
keys). Keys that are not user-facing (internal tuning) use their module
namespace instead: ``"agent.max_iterations"``, ``"maintenance.debounce_seconds"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, ClassVar

__all__ = [
    "Param",
    "PARAMS",
    "param_default",
    "param_spec",
    "has_param",
    "params_under",
    "defaults_for_prefix",
    "section_defaults",
    "canonical_key",
    "aliases_of",
    "nest",
    "FoundationParams",
    "KernelParams",
    "AppsParams",
    "InterfacesParams",
]


@dataclass(frozen=True)
class Param:
    """One declared parameter.

    Attributes:
        default: The value used when nothing overrides it. This is the
            **only** place a default is written down.
        type: Declared type, used for coercion and for the consistency
            test. ``None`` means "unconstrained" (e.g. union types).
        doc: One-line description.
        layer: Owning architecture layer — ``"foundation"`` (L1),
            ``"kernel"`` (L2), ``"apps"`` (L3), ``"interfaces"`` (L4).
            Drives which per-layer view exposes the parameter. The value is
            the layer's real name, not a number — no lookup table needed.
            Hub-specific: industry config registries express ownership
            structurally (separate declaration files / families), not per
            setting.
        env: Environment variable that overrides this parameter, when the
            parameter is meant to be settable from the environment.
        hot_reloadable: Whether the value can change while the process
            runs. Hand-maintained on purpose — ClickHouse's
            ``changeable_without_restart`` map is the only part of its
            1000+ settings that is not code-generated, with a comment
            asking developers to update it manually.
        deprecated: When set, the parameter still resolves but should
            stop being used; the replacement is named in ``alias_of``.
        alias_of: Canonical key this parameter is a deprecated alias of.
            D5 (iii): the default lives **only** on the canonical; aliases
            resolve through it at load time so one concept has one value.
            A key that is both a canonical and an alias (a cycle) is a
            registry bug and raises.
    """

    default: Any
    type: type | None
    doc: str
    layer: str
    env: str | None = None
    hot_reloadable: bool = True
    deprecated: bool = False
    alias_of: str | None = None


# ─────────────────────────────────────────────────────────────────────
# Config-file scoped parameters
#
# These are the keys a user can write into ~/.llmwikify/llmwikify.json
# (global scope) or .wiki-config.yaml (wiki scope).
# ─────────────────────────────────────────────────────────────────────

PARAMS: dict[str, Param] = {
    # ── directories（L2：kernel/wiki 读取）──────────────────────────
    "directories.raw": Param("raw", str, "源文件目录名", "kernel"),
    "directories.wiki": Param("wiki", str, "wiki 页面目录名", "kernel"),
    # ── database（L2）───────────────────────────────────────────────
    "database.name": Param(".llmwikify.db", str, "SQLite 数据库文件名", "kernel"),
    # ── reference_index（L2）────────────────────────────────────────
    "reference_index.name": Param("reference_index.json", str, "引用索引导出文件名", "kernel"),
    "reference_index.auto_export": Param(True, bool, "构建后自动导出引用索引", "kernel"),
    # ── orphan_detection（L2）───────────────────────────────────────
    "orphan_detection.default_exclude_patterns": Param([], list, "默认排除的页名正则", "kernel"),
    "orphan_detection.exclude_frontmatter": Param([], list, "标记排除的 frontmatter 键", "kernel"),
    "orphan_detection.archive_directories": Param([], list, "归档目录名", "kernel"),
    # ── performance（L2）────────────────────────────────────────────
    "performance.batch_size": Param(100, int, "索引构建每批文件数", "kernel"),
    # ── llm（L1：foundation/llm 定义与使用）────────────────────────
    # LAL (PR 4): all fields are None / False by default. The legacy
    # hardcoded gpt-4 / openai / localhost:11434 values are removed;
    # LLMNotConfiguredError is raised when LLM code tries to use them.
    "llm.enabled": Param(False, bool, "是否启用 LLM", "foundation"),
    "llm.provider": Param(None, str, "LLM provider（openai/anthropic/minimax/...）", "foundation"),
    "llm.model": Param(None, str, "模型名", "foundation"),
    "llm.base_url": Param(None, str, "OpenAI 兼容端点", "foundation"),
    "llm.api_key": Param("", str, "API key（支持 env:VAR 引用）", "foundation"),
    "llm.timeout": Param(120, int, "单次 LLM 调用超时（秒）", "foundation"),
    "llm.context_window": Param(None, int, "上下文窗口大小（token）", "foundation"),
    "llm.budget_on_exceed": Param("warn", str, "超预算行为 warn/raise/truncate", "foundation"),
    # ── mcp（L4）────────────────────────────────────────────────────
    "mcp.name": Param(None, str, "MCP server 名称", "interfaces", hot_reloadable=False),
    "mcp.host": Param("127.0.0.1", str, "MCP 监听地址", "interfaces", hot_reloadable=False),
    "mcp.port": Param(8765, int, "MCP 监听端口", "interfaces", hot_reloadable=False),
    "mcp.transport": Param(
        "stdio", str, "MCP 传输方式 stdio/http/sse", "interfaces", hot_reloadable=False
    ),
    # ── web（L4）────────────────────────────────────────────────────
    "web.port": Param(8766, int, "Web UI 端口", "interfaces", hot_reloadable=False),
    "web.host": Param("127.0.0.1", str, "Web UI 监听地址", "interfaces", hot_reloadable=False),
    # ── prompts（L2）────────────────────────────────────────────────
    "prompts.custom_dir": Param(None, str, "自定义 prompt 目录", "kernel"),
    # ── search（L2：kernel/search）──────────────────────────────────
    "search.backend": Param("fts5", str, "检索后端 fts5/qmd", "kernel", hot_reloadable=False),
    "search.qmd.host": Param("127.0.0.1", str, "QMD 服务地址", "kernel", hot_reloadable=False),
    "search.qmd.port": Param(8181, int, "QMD 服务端口", "kernel", hot_reloadable=False),
    "search.qmd.auto_start": Param(False, bool, "是否自动拉起 QMD", "kernel"),
    # ── wikis（L2：kernel/multi_wiki）───────────────────────────────
    "wikis.default": Param(None, str, "默认 wiki id", "kernel"),
    "wikis.local": Param([], list, "本地 wiki 列表", "kernel"),
    "wikis.remote": Param([], list, "远程 wiki 列表", "kernel"),
    "wikis.discovery.enabled": Param(False, bool, "是否自动发现 wiki", "kernel"),
    "wikis.discovery.scan_paths": Param(["."], list, "扫描路径", "kernel"),
    "wikis.discovery.scan_depth": Param(2, int, "扫描深度", "kernel"),
    "wikis.discovery.exclude_patterns": Param(
        [
            "node_modules",
            ".git",
            "__pycache__",
            ".venv",
            "venv",
        ],
        list,
        "扫描排除目录名",
        "kernel",
    ),
    "wikis.discovery.auto_register": Param(False, bool, "发现后是否自动注册", "kernel"),
    "wikis.discovery.scan_interval": Param(3600, int, "扫描间隔（秒）", "kernel"),
    # ── research（L3）───────────────────────────────────────────────
    "research.enabled": Param(True, bool, "是否启用 research", "apps"),
    "research.search_provider": Param("auto", str, "搜索 provider auto/minimax/tavily/searxng", "apps"),
    "research.minimax_api_key": Param("", str, "Minimax 搜索 API key", "apps"),
    "research.minimax_api_host": Param("", str, "Minimax 搜索 host", "apps"),
    # ── chat_mutable（L3，用户可改）─────────────────────────────────
    # max_chat_rounds is a deprecated *name* for agent.max_iterations
    # (D5 iii): the default lives on the canonical key, and the user's
    # setting on this alias flows through to it at load time.
    "chat_mutable.max_chat_rounds": Param(
        None, int, "对话最大轮数（规范键 agent.max_iterations 的别名）", "apps",
        alias_of="agent.max_iterations",
    ),
    "chat_mutable.max_messages": Param(50, int, "历史消息上限", "apps"),
    "chat_mutable.observation_limit": Param(10, int, "observation 上限", "apps"),
    "chat_mutable.llm_retry_max_attempts": Param(3, int, "LLM 重试次数", "apps"),
    "chat_mutable.llm_retry_base_delay": Param(2.0, float, "LLM 重试基础延迟（秒）", "apps"),
    "chat_mutable.llm_retry_call_timeout": Param(120.0, float, "LLM 重试单次超时（秒）", "apps"),
    "chat_mutable.llm_retry_max_delay": Param(30.0, float, "LLM 重试最大延迟（秒）", "apps"),
    "chat_mutable.chat_db_retry_max_attempts": Param(3, int, "chat DB 重试次数", "apps"),
    "chat_mutable.chat_db_retry_base_delay": Param(0.2, float, "chat DB 重试基础延迟（秒）", "apps"),
    # ── research_mutable（L3，用户可改）─────────────────────────────
    "research_mutable.search_provider": Param("auto", str, "搜索 provider", "apps"),
    "research_mutable.max_sub_queries": Param(20, int, "子查询上限", "apps"),
    "research_mutable.research_timeout_minutes": Param(30, int, "research 超时（分钟）", "apps"),
    "research_mutable.max_parallel_gathering": Param(5, int, "并行抓取上限", "apps"),
    "research_mutable.web_search_results_per_query": Param(5, int, "每查询搜索结果数", "apps"),
    "research_mutable.max_retry_attempts": Param(3, int, "最大重试次数", "apps"),
    "research_mutable.max_review_rounds": Param(2, int, "评审轮数上限", "apps"),
    # ── 规范键（D5 iii）────────────────────────────────────────────
    # One canonical per concept; deprecated names point here via alias_of.
    # agent.max_iterations is the canonical for the agent iteration cap —
    # seven different names used to carry five different defaults
    # (4/5/8/10). See docs/designs/config-hub-design-log.md D5.
    "agent.max_iterations": Param(
        4, int, "agent 迭代上限（规范键；别名见 chat_mutable.max_chat_rounds）", "apps"
    ),
    # Independent scopes — deliberately NOT aliases of agent.max_iterations:
    # a subagent is meant to run fewer rounds than its parent, and a dream
    # task is a different loop entirely.
    "subagent.max_iterations": Param(
        5, int, "子 agent 迭代上限（独立 scope，刻意小于主 agent）", "apps"
    ),
    "dream.max_iterations": Param(
        10, int, "dream 任务迭代上限（独立 scope）", "apps"
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Internal tuning parameters
#
# Not part of any config file: code-owned defaults that a developer may
# override, or that a user can only influence indirectly.
# ─────────────────────────────────────────────────────────────────────

PARAMS.update(
    {
        # ── wiki 阈值（L2：kernel/wiki）────────────────────────────
        "wiki.similarity_threshold": Param(0.3, float, "页面相似度阈值", "kernel"),
        "wiki.min_keyword_length": Param(3, int, "参与匹配的关键词最小长度", "kernel"),
        "wiki.jaccard_overlap_threshold": Param(0.85, float, "query 页重叠阈值", "kernel"),
        "wiki.min_missing_ref_count": Param(2, int, "触发缺失引用的最小提及次数", "kernel"),
        "wiki.max_dated_claim_hints": Param(3, int, "过期声明提示上限", "kernel"),
        "wiki.max_query_overlap_hints": Param(2, int, "query 重叠提示上限", "kernel"),
        "wiki.max_cross_ref_hints": Param(3, int, "交叉引用提示上限", "kernel"),
        "wiki.max_contradictions": Param(3, int, "矛盾提示上限", "kernel"),
        "wiki.min_assertion_length": Param(21, int, "断言最小长度", "kernel"),
        "wiki.min_assertions_for_gap": Param(3, int, "构成知识缺口的最少断言数", "kernel"),
        "wiki.outdated_year_gap": Param(2, int, "内容过期年份差", "kernel"),
        "wiki.year_gap_threshold": Param(3, int, "年份差告警阈值", "kernel"),
        "wiki.min_year_threshold": Param(2018, int, "不过期的最早年份", "kernel"),
        "wiki.max_missing_display": Param(5, int, "缺失引用展示上限", "kernel"),
        "wiki.max_summary_items": Param(5, int, "摘要条目上限", "kernel"),
        "wiki.max_key_topics": Param(5, int, "关键词主题上限", "kernel"),
        "wiki.max_query_topic_length": Param(50, int, "query 页名主题长度上限", "kernel"),
        "wiki.max_content_chars": Param(8000, int, "单页参与分析的最大字符数", "kernel"),
        "wiki.hash_truncate_length": Param(16, int, "内容哈希截断长度", "kernel"),
        "wiki.max_suggested_updates": Param(10, int, "建议更新条目上限", "kernel"),
        "wiki.small_wiki_threshold": Param(5, int, "小 wiki 页数阈值", "kernel"),
        "wiki.growing_wiki_threshold": Param(20, int, "成长中 wiki 页数阈值", "kernel"),
        "wiki.claim_overlap_threshold": Param(0.4, float, "声明重叠阈值", "kernel"),
        "wiki.contradiction_overlap_threshold": Param(0.5, float, "矛盾重叠阈值", "kernel"),
    }
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def has_param(key: str) -> bool:
    """True when ``key`` is declared in the registry."""
    return key in PARAMS


def param_spec(key: str) -> Param:
    """Return the declaration for ``key``.

    Raises:
        KeyError: when the key is not declared. That is deliberate — an
            undeclared key means someone used a parameter that was never
            registered, which should fail loudly rather than silently
            fall back to a default.
    """
    try:
        return PARAMS[key]
    except KeyError:
        raise KeyError(
            f"Unregistered parameter {key!r}. Add it to "
            f"llmwikify.foundation.params.PARAMS."
        ) from None


def canonical_key(key: str) -> str:
    """Follow ``alias_of`` to the root (canonical) key.

    Unknown keys and keys with no alias return themselves. A cycle is a
    registry bug and raises.
    """
    seen: set[str] = set()
    current = key
    while True:
        spec = PARAMS.get(current)
        if spec is None or spec.alias_of is None:
            return current
        if current in seen:  # pragma: no cover - caught by tests
            raise ValueError(f"alias_of cycle at {current!r}")
        seen.add(current)
        current = spec.alias_of


def aliases_of(key: str) -> list[str]:
    """Every registered key whose ``alias_of`` points at ``key``."""
    root = canonical_key(key)
    return sorted(k for k, p in PARAMS.items() if p.alias_of == root and k != root)


def param_default(key: str, fallback: Any = None) -> Any:
    """Return the effective default for ``key``.

    Resolves ``alias_of`` chains (D5 iii): an alias's default lives on its
    canonical key, so this returns the canonical's default. Unknown keys
    yield ``fallback`` (default ``None``).
    """
    spec = PARAMS.get(canonical_key(key))
    return spec.default if spec is not None else fallback


def params_under(prefix: str) -> dict[str, Param]:
    """Return every declaration whose key starts with ``prefix``.

    The prefix must be a full dotted segment boundary, e.g. ``"llm."``.
    """
    if not prefix.endswith("."):
        prefix += "."
    return {k: v for k, v in PARAMS.items() if k.startswith(prefix)}


def defaults_for_prefix(prefix: str) -> dict[str, Any]:
    """Return ``{key_suffix: default}`` for every key under ``prefix``.

    The suffix is the key with ``prefix`` stripped, so
    ``defaults_for_prefix("llm")`` yields ``{"timeout": 120, ...}`` —
    the flat shape. Defaults go through :func:`param_default` so aliases
    inherit their canonical's value (D5 iii).
    """
    if not prefix.endswith("."):
        prefix += "."
    return {
        k[len(prefix) :]: param_default(k)
        for k, v in PARAMS.items()
        if k.startswith(prefix)
    }


def section_defaults(prefix: str) -> dict[str, Any]:
    """Return the nested ``{section: {...}}`` shape for every key under ``prefix``.

    This is the shape the config files use, so
    ``section_defaults("search")`` yields
    ``{"backend": "fts5", "qmd": {"host": ..., "port": ...}}``.
    """
    if not prefix.endswith("."):
        prefix += "."
    section: dict[str, Any] = {}
    for key in PARAMS:
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix) :].split(".")
        cursor = section
        for part in parts[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):  # pragma: no cover - malformed key
                raise ValueError(f"Conflicting parameter key: {key!r}")
            cursor = nxt
        cursor[parts[-1]] = param_default(key)
    return section


# ─────────────────────────────────────────────────────────────────────
# Dynamic nested views (option C)
#
# The per-layer views expose attribute access (``params.wiki.similarity_threshold``)
# without hand-written field declarations: values are nested from the dotted
# keys at construction time. Static types come from the generated
# ``params.pyi`` (see scripts/gen_params_stub.py); drift between the two is
# caught by tests/test_foundation_params.py.
# ─────────────────────────────────────────────────────────────────────


def nest(values: Mapping[str, Any]) -> Any:
    """Build a nested namespace from dotted keys.

    ``{"wiki.similarity_threshold": 0.3, "llm.timeout": 120}`` becomes an
    object with ``.wiki.similarity_threshold`` and ``.llm.timeout``.

    Keys are the registry keys, so the nesting mirrors the config-file
    shape and is unique by construction. A key that is both a leaf and a
    section prefix (``llm`` and ``llm.timeout``) is a registry bug — it
    raises rather than silently clobbering one of them.
    """
    root = SimpleNamespace()
    for key, value in values.items():
        parts = key.split(".")
        node = root
        for part in parts[:-1]:
            existing = getattr(node, part, None)
            if existing is None:
                existing = SimpleNamespace()
                setattr(node, part, existing)
            elif not isinstance(existing, SimpleNamespace):
                raise ValueError(
                    f"Parameter key {key!r} collides with leaf "
                    f"{part!r} — a key cannot be both a section and a value"
                )
            node = existing
        leaf = parts[-1]
        if hasattr(node, leaf) and isinstance(getattr(node, leaf), SimpleNamespace):
            raise ValueError(
                f"Parameter key {key!r} collides with section {leaf!r}"
            )
        setattr(node, leaf, value)
    return root


def _layer_values(layer: str, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve every key owned by ``layer``, or a caller-supplied subset."""
    if values is not None:
        return dict(values)
    return {k: param_default(k) for k, p in PARAMS.items() if p.layer == layer}


class _ParamView:
    """Thin per-layer view over :func:`nest`.

    Subclasses only declare which layer they expose; the attribute
    structure is derived from the registry. Static types for the
    attributes come from the generated ``params.pyi``.
    """

    LAYER: ClassVar[str] = ""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._view = nest(_layer_values(self.LAYER, values))

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not found on the instance/class, i.e.
        # the nested sections and leaves.
        return getattr(self._view, name)

    @classmethod
    def layer_keys(cls) -> frozenset[str]:
        """Registry keys this view exposes."""
        return frozenset(k for k, p in PARAMS.items() if p.layer == cls.LAYER)


class FoundationParams(_ParamView):
    """L1 (foundation) view — ``llm.*``."""

    LAYER = "foundation"


class KernelParams(_ParamView):
    """L2 (kernel) view — ``wiki.*``, ``directories.*``, ``search.*``, …"""

    LAYER = "kernel"


class AppsParams(_ParamView):
    """L3 (apps) view — ``chat_mutable.*``, ``research*``."""

    LAYER = "apps"


class InterfacesParams(_ParamView):
    """L4 (interfaces) view — ``mcp.*``, ``web.*``."""

    LAYER = "interfaces"

