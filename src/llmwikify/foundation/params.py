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

from dataclasses import dataclass
from typing import Any

__all__ = [
    "Param",
    "PARAMS",
    "param_default",
    "param_spec",
    "has_param",
    "params_under",
    "defaults_for_prefix",
    "section_defaults",
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
        env: Environment variable that overrides this parameter, when the
            parameter is meant to be settable from the environment.
    """

    default: Any
    type: type | None = None
    doc: str = ""
    env: str | None = None


# ─────────────────────────────────────────────────────────────────────
# Config-file scoped parameters
#
# These are the keys a user can write into ~/.llmwikify/llmwikify.json
# (global scope) or .wiki-config.yaml (wiki scope).
# ─────────────────────────────────────────────────────────────────────

PARAMS: dict[str, Param] = {
    # ── directories ──────────────────────────────────────────────────
    "directories.raw": Param("raw", str, "源文件目录名"),
    "directories.wiki": Param("wiki", str, "wiki 页面目录名"),
    # ── database ────────────────────────────────────────────────────
    "database.name": Param(".llmwikify.db", str, "SQLite 数据库文件名"),
    # ── reference_index ─────────────────────────────────────────────
    "reference_index.name": Param("reference_index.json", str, "引用索引导出文件名"),
    "reference_index.auto_export": Param(True, bool, "构建后自动导出引用索引"),
    # ── orphan_detection ────────────────────────────────────────────
    "orphan_detection.default_exclude_patterns": Param([], list, "默认排除的页名正则"),
    "orphan_detection.exclude_frontmatter": Param([], list, "标记排除的 frontmatter 键"),
    "orphan_detection.archive_directories": Param([], list, "归档目录名"),
    # ── performance ─────────────────────────────────────────────────
    "performance.batch_size": Param(100, int, "索引构建每批文件数"),
    # ── llm ─────────────────────────────────────────────────────────
    # LAL (PR 4): all fields are None / False by default. The legacy
    # hardcoded gpt-4 / openai / localhost:11434 values are removed;
    # LLMNotConfiguredError is raised when LLM code tries to use them.
    "llm.enabled": Param(False, bool, "是否启用 LLM"),
    "llm.provider": Param(None, str, "LLM provider（openai/anthropic/minimax/...）"),
    "llm.model": Param(None, str, "模型名"),
    "llm.base_url": Param(None, str, "OpenAI 兼容端点"),
    "llm.api_key": Param("", str, "API key（支持 env:VAR 引用）"),
    "llm.timeout": Param(120, int, "单次 LLM 调用超时（秒）"),
    "llm.context_window": Param(None, int, "上下文窗口大小（token）"),
    "llm.budget_on_exceed": Param("warn", str, "超预算行为 warn/raise/truncate"),
    # ── mcp ─────────────────────────────────────────────────────────
    "mcp.name": Param(None, str, "MCP server 名称"),
    "mcp.host": Param("127.0.0.1", str, "MCP 监听地址"),
    "mcp.port": Param(8765, int, "MCP 监听端口"),
    "mcp.transport": Param("stdio", str, "MCP 传输方式 stdio/http/sse"),
    # ── web ─────────────────────────────────────────────────────────
    "web.port": Param(8766, int, "Web UI 端口"),
    "web.host": Param("127.0.0.1", str, "Web UI 监听地址"),
    # ── prompts ─────────────────────────────────────────────────────
    "prompts.custom_dir": Param(None, str, "自定义 prompt 目录"),
    # ── search ──────────────────────────────────────────────────────
    "search.backend": Param("fts5", str, "检索后端 fts5/qmd"),
    "search.qmd.host": Param("127.0.0.1", str, "QMD 服务地址"),
    "search.qmd.port": Param(8181, int, "QMD 服务端口"),
    "search.qmd.auto_start": Param(False, bool, "是否自动拉起 QMD"),
    # ── wikis ───────────────────────────────────────────────────────
    "wikis.default": Param(None, str, "默认 wiki id"),
    "wikis.local": Param([], list, "本地 wiki 列表"),
    "wikis.remote": Param([], list, "远程 wiki 列表"),
    "wikis.discovery.enabled": Param(False, bool, "是否自动发现 wiki"),
    "wikis.discovery.scan_paths": Param(["."], list, "扫描路径"),
    "wikis.discovery.scan_depth": Param(2, int, "扫描深度"),
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
    ),
    "wikis.discovery.auto_register": Param(False, bool, "发现后是否自动注册"),
    "wikis.discovery.scan_interval": Param(3600, int, "扫描间隔（秒）"),
    # ── research（全局段）────────────────────────────────────────────
    "research.enabled": Param(True, bool, "是否启用 research"),
    "research.search_provider": Param("auto", str, "搜索 provider auto/minimax/tavily/searxng"),
    "research.minimax_api_key": Param("", str, "Minimax 搜索 API key"),
    "research.minimax_api_host": Param("", str, "Minimax 搜索 host"),
    # ── chat_mutable（用户可改）──────────────────────────────────────
    "chat_mutable.max_chat_rounds": Param(4, int, "对话最大轮数"),
    "chat_mutable.max_messages": Param(50, int, "历史消息上限"),
    "chat_mutable.observation_limit": Param(10, int, "observation 上限"),
    "chat_mutable.llm_retry_max_attempts": Param(3, int, "LLM 重试次数"),
    "chat_mutable.llm_retry_base_delay": Param(2.0, float, "LLM 重试基础延迟（秒）"),
    "chat_mutable.llm_retry_call_timeout": Param(120.0, float, "LLM 重试单次超时（秒）"),
    "chat_mutable.llm_retry_max_delay": Param(30.0, float, "LLM 重试最大延迟（秒）"),
    "chat_mutable.chat_db_retry_max_attempts": Param(3, int, "chat DB 重试次数"),
    "chat_mutable.chat_db_retry_base_delay": Param(0.2, float, "chat DB 重试基础延迟（秒）"),
    # ── research_mutable（用户可改）──────────────────────────────────
    "research_mutable.search_provider": Param("auto", str, "搜索 provider"),
    "research_mutable.max_sub_queries": Param(20, int, "子查询上限"),
    "research_mutable.research_timeout_minutes": Param(30, int, "research 超时（分钟）"),
    "research_mutable.max_parallel_gathering": Param(5, int, "并行抓取上限"),
    "research_mutable.web_search_results_per_query": Param(5, int, "每查询搜索结果数"),
    "research_mutable.max_retry_attempts": Param(3, int, "最大重试次数"),
    "research_mutable.max_review_rounds": Param(2, int, "评审轮数上限"),
}


# ─────────────────────────────────────────────────────────────────────
# Internal tuning parameters
#
# Not part of any config file: code-owned defaults that a developer may
# override, or that a user can only influence indirectly.
# ─────────────────────────────────────────────────────────────────────

PARAMS.update(
    {
        # ── wiki 阈值（kernel/wiki/constants.py）────────────────────
        "wiki.similarity_threshold": Param(0.3, float, "页面相似度阈值"),
        "wiki.min_keyword_length": Param(3, int, "参与匹配的关键词最小长度"),
        "wiki.jaccard_overlap_threshold": Param(0.85, float, "query 页重叠阈值"),
        "wiki.min_missing_ref_count": Param(2, int, "触发缺失引用的最小提及次数"),
        "wiki.max_dated_claim_hints": Param(3, int, "过期声明提示上限"),
        "wiki.max_query_overlap_hints": Param(2, int, "query 重叠提示上限"),
        "wiki.max_cross_ref_hints": Param(3, int, "交叉引用提示上限"),
        "wiki.max_contradictions": Param(3, int, "矛盾提示上限"),
        "wiki.min_assertion_length": Param(21, int, "断言最小长度"),
        "wiki.min_assertions_for_gap": Param(3, int, "构成知识缺口的最少断言数"),
        "wiki.outdated_year_gap": Param(2, int, "内容过期年份差"),
        "wiki.year_gap_threshold": Param(3, int, "年份差告警阈值"),
        "wiki.min_year_threshold": Param(2018, int, "不过期的最早年份"),
        "wiki.max_missing_display": Param(5, int, "缺失引用展示上限"),
        "wiki.max_summary_items": Param(5, int, "摘要条目上限"),
        "wiki.max_key_topics": Param(5, int, "关键词主题上限"),
        "wiki.max_query_topic_length": Param(50, int, "query 页名主题长度上限"),
        "wiki.max_content_chars": Param(8000, int, "单页参与分析的最大字符数"),
        "wiki.hash_truncate_length": Param(16, int, "内容哈希截断长度"),
        "wiki.max_suggested_updates": Param(10, int, "建议更新条目上限"),
        "wiki.small_wiki_threshold": Param(5, int, "小 wiki 页数阈值"),
        "wiki.growing_wiki_threshold": Param(20, int, "成长中 wiki 页数阈值"),
        "wiki.claim_overlap_threshold": Param(0.4, float, "声明重叠阈值"),
        "wiki.contradiction_overlap_threshold": Param(0.5, float, "矛盾重叠阈值"),
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


def param_default(key: str, fallback: Any = None) -> Any:
    """Return the declared default for ``key``.

    Unlike :func:`param_spec` this never raises: an unknown key yields
    ``fallback`` (default ``None``). Use it where a key is genuinely
    optional.
    """
    spec = PARAMS.get(key)
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
    the flat shape.
    """
    if not prefix.endswith("."):
        prefix += "."
    return {
        k[len(prefix) :]: v.default
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
    for key, spec in PARAMS.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix) :].split(".")
        cursor = section
        for part in parts[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):  # pragma: no cover - malformed key
                raise ValueError(f"Conflicting parameter key: {key!r}")
            cursor = nxt
        cursor[parts[-1]] = spec.default
    return section
