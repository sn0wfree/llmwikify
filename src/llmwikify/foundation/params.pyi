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

class ChatImmutableSection:
    """chat_immutable section."""

    clarify_enabled: bool
    clarify_max_retries: int
    compaction_enabled: bool
    compaction_max_tokens: int
    compaction_min_messages: int
    compaction_threshold_ratio: float
    content_truncate_chars: int
    context_reserve_tokens: int
    context_store_max_size: int
    context_store_ttl_seconds: int
    context_window_override: int
    db_retry_base_delay: float
    db_retry_max_retries: int
    evidence_max_retries: int
    evidence_scoring_enabled: bool
    framework_check_enabled: bool
    gate_max_reasoning_issues: int
    gate_min_evidence_score: float
    gate_min_reasoning_score: int
    gate_min_source_refs: int
    gate_min_structure_score: int
    gate_min_traceable_sources: int
    llm_parse_max_retries: int
    observation_summary_limit: int
    reasoning_check_enabled: bool
    self_loop_budget_ratio: float
    stage_max_retries: int
    stage_retry_base_delay: float
    strict_exit: bool
    structure_check_enabled: bool
    summary_truncate_chars: int
    llm_params: ChatImmutableLlmParamsSection

class ChatImmutableLlmParamsSection:
    """chat_immutable.llm_params section."""

    research_clarify: ChatImmutableLlmParamsResearchClarifySection
    research_plan: ChatImmutableLlmParamsResearchPlanSection
    research_reason: ChatImmutableLlmParamsResearchReasonSection
    research_replan: ChatImmutableLlmParamsResearchReplanSection
    research_report: ChatImmutableLlmParamsResearchReportSection
    research_review: ChatImmutableLlmParamsResearchReviewSection
    research_revise: ChatImmutableLlmParamsResearchReviseSection

class ChatImmutableLlmParamsResearchClarifySection:
    """chat_immutable.llm_params.research_clarify section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchPlanSection:
    """chat_immutable.llm_params.research_plan section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchReasonSection:
    """chat_immutable.llm_params.research_reason section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchReplanSection:
    """chat_immutable.llm_params.research_replan section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchReportSection:
    """chat_immutable.llm_params.research_report section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchReviewSection:
    """chat_immutable.llm_params.research_review section."""

    json_mode: bool
    max_tokens: int
    temperature: float

class ChatImmutableLlmParamsResearchReviseSection:
    """chat_immutable.llm_params.research_revise section."""

    json_mode: bool
    max_tokens: int
    temperature: float

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

class ResearchImmutableSection:
    """research_immutable section."""

    gate_enabled: bool
    gate_max_knowledge_gaps: int
    gate_min_analyzed: int
    gate_min_avg_credibility: int
    gate_min_reinforced_claims: int
    gate_min_sources: int
    gate_min_type_diversity: int
    llm_call_timeout_seconds: int
    max_react_rounds: int
    max_replan_attempts: int
    max_source_content_length: int
    minimax_api_host: str
    minimax_api_key: str
    parallel_wiki_search: bool
    planning_model: str
    quality_threshold: int
    report_max_per_source: int
    report_max_total_content: int
    report_model: str
    search_provider: str
    searxng_url: str
    similarity_threshold: float
    source_filter_enabled: bool
    source_min_content_length: int
    source_min_quality_score: float
    tavily_api_key: str

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
    chat_immutable: ChatImmutableSection
    chat_mutable: ChatMutableSection
    dream: DreamSection
    research: ResearchSection
    research_immutable: ResearchImmutableSection
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

