"""Type stub for llmwikify.foundation.params — GENERATED, do not edit.

Regenerate with ``python scripts/gen_params_stub.py`` after changing
the registry. Drift is caught by tests/test_foundation_params.py.
"""

import builtins
from collections.abc import Mapping
from typing import Any, ClassVar

class Param:
    """One declared parameter (see the runtime dataclass)."""

    default: Any
    type: builtins.type | None
    doc: str
    layer: str
    env: str | None
    hot_reloadable: bool
    deprecated: bool
    alias_of: str | None
    def __init__(
        self,
        default: Any,
        type: builtins.type | None,
        doc: str,
        layer: str,
        env: str | None = ...,
        hot_reloadable: bool = ...,
        deprecated: bool = ...,
        alias_of: str | None = ...,
    ) -> None: ...

class AgentSection:
    """agent section."""

    max_iterations: int

class ChatMutableSection:
    """chat_mutable section."""

    chat_db_retry_base_delay: float
    chat_db_retry_max_attempts: int
    llm_retry_base_delay: float
    llm_retry_call_timeout: float
    llm_retry_max_attempts: int
    llm_retry_max_delay: float
    max_chat_rounds: int
    max_messages: int
    observation_limit: int

class DatabaseSection:
    """database section."""

    name: str

class DirectoriesSection:
    """directories section."""

    raw: str
    wiki: str

class DreamSection:
    """dream section."""

    max_iterations: int

class LlmSection:
    """llm section."""

    api_key: str
    base_url: str
    budget_on_exceed: str
    context_window: int
    enabled: bool
    model: str
    provider: str
    timeout: int

class McpSection:
    """mcp section."""

    host: str
    name: str
    port: int
    transport: str

class OrphanDetectionSection:
    """orphan_detection section."""

    archive_directories: list[Any]
    default_exclude_patterns: list[Any]
    exclude_frontmatter: list[Any]

class PerformanceSection:
    """performance section."""

    batch_size: int

class PromptsSection:
    """prompts section."""

    custom_dir: str

class ReferenceIndexSection:
    """reference_index section."""

    auto_export: bool
    name: str

class ResearchSection:
    """research section."""

    enabled: bool
    minimax_api_host: str
    minimax_api_key: str
    search_provider: str

class ResearchMutableSection:
    """research_mutable section."""

    max_parallel_gathering: int
    max_retry_attempts: int
    max_review_rounds: int
    max_sub_queries: int
    research_timeout_minutes: int
    search_provider: str
    web_search_results_per_query: int

class SearchSection:
    """search section."""

    backend: str
    qmd: SearchQmdSection

class SearchQmdSection:
    """search.qmd section."""

    auto_start: bool
    host: str
    port: int

class SubagentSection:
    """subagent section."""

    max_iterations: int

class WebSection:
    """web section."""

    host: str
    port: int

class WikiSection:
    """wiki section."""

    claim_overlap_threshold: float
    contradiction_overlap_threshold: float
    growing_wiki_threshold: int
    hash_truncate_length: int
    jaccard_overlap_threshold: float
    max_content_chars: int
    max_contradictions: int
    max_cross_ref_hints: int
    max_dated_claim_hints: int
    max_key_topics: int
    max_missing_display: int
    max_query_overlap_hints: int
    max_query_topic_length: int
    max_suggested_updates: int
    max_summary_items: int
    min_assertion_length: int
    min_assertions_for_gap: int
    min_keyword_length: int
    min_missing_ref_count: int
    min_year_threshold: int
    outdated_year_gap: int
    similarity_threshold: float
    small_wiki_threshold: int
    year_gap_threshold: int

class WikisSection:
    """wikis section."""

    default: str
    local: list[Any]
    remote: list[Any]
    discovery: WikisDiscoverySection

class WikisDiscoverySection:
    """wikis.discovery section."""

    auto_register: bool
    enabled: bool
    exclude_patterns: list[Any]
    scan_depth: int
    scan_interval: int
    scan_paths: list[Any]

class FoundationParams:
    """L1 (foundation) view — ``llm.*``."""

    LAYER: ClassVar[str]

    llm: LlmSection

    def __init__(self, values: Mapping[str, Any] | None = None) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    @classmethod
    def layer_keys(cls) -> frozenset[str]: ...

class KernelParams:
    """L2 (kernel) view — ``wiki.*``, ``directories.*``, …"""

    LAYER: ClassVar[str]

    database: DatabaseSection
    directories: DirectoriesSection
    orphan_detection: OrphanDetectionSection
    performance: PerformanceSection
    prompts: PromptsSection
    reference_index: ReferenceIndexSection
    search: SearchSection
    wiki: WikiSection
    wikis: WikisSection

    def __init__(self, values: Mapping[str, Any] | None = None) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    @classmethod
    def layer_keys(cls) -> frozenset[str]: ...

class AppsParams:
    """L3 (apps) view — ``chat_mutable.*``, ``research*``."""

    LAYER: ClassVar[str]

    agent: AgentSection
    chat_mutable: ChatMutableSection
    dream: DreamSection
    research: ResearchSection
    research_mutable: ResearchMutableSection
    subagent: SubagentSection

    def __init__(self, values: Mapping[str, Any] | None = None) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    @classmethod
    def layer_keys(cls) -> frozenset[str]: ...

class InterfacesParams:
    """L4 (interfaces) view — ``mcp.*``, ``web.*``."""

    LAYER: ClassVar[str]

    mcp: McpSection
    web: WebSection

    def __init__(self, values: Mapping[str, Any] | None = None) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
    @classmethod
    def layer_keys(cls) -> frozenset[str]: ...

PARAMS: dict[str, Param]

def param_default(key: str, fallback: Any = None) -> Any: ...
def param_spec(key: str) -> Param: ...
def has_param(key: str) -> bool: ...
def params_under(prefix: str) -> dict[str, Param]: ...
def defaults_for_prefix(prefix: str) -> dict[str, Any]: ...
def section_defaults(prefix: str) -> dict[str, Any]: ...
def canonical_key(key: str) -> str: ...
def aliases_of(key: str) -> list[str]: ...
def nest(values: Mapping[str, Any]) -> Any: ...

