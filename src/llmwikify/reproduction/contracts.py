"""Pydantic contracts for Wiki pages.

All Wiki pages MUST be serializable to/from these Pydantic models.
This is the single source of truth for page schemas.

Usage:
    from llmwikify.reproduction.contracts import FactorPage, render_page

    # Create a factor page
    page = FactorPage(
        title="Momentum",
        factor_class="momentum",
        signal_type="momentum",
    )

    # Render to markdown
    md = render_page(page, body="# Momentum\n\n...")

    # Parse from markdown
    page = parse_page(content)
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────


class FactorClass(str, Enum):
    """Factor classification."""
    MOMENTUM = "momentum"
    VALUE = "value"
    VOLATILITY = "volatility"
    QUALITY = "quality"
    SIZE = "size"
    GROWTH = "growth"
    SIGNAL_COMPOSITE = "signal_composite"
    UNKNOWN = "unknown"


class SignalType(str, Enum):
    """Signal type for strategies."""
    MA_CROSS = "ma_cross"
    RSI = "rsi"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    FACTOR_RANK = "factor_rank"
    SIGNAL_COMPOSITE = "signal_composite"
    UNKNOWN = "unknown"


class StrategyClass(str, Enum):
    """Strategy classification."""
    TREND_FOLLOWING = "trend_following"
    FACTOR_RANKING = "factor_ranking"
    STAT_ARB = "stat_arb"
    MEAN_REVERSION = "mean_reversion"
    COMPOSITE = "composite"
    UNKNOWN = "unknown"


class PageStatus(str, Enum):
    """Page status."""
    DRAFT = "draft"
    VALIDATED = "validated"
    BACKTESTED = "backtested"
    DEPRECATED = "deprecated"


class RunStatus(str, Enum):
    """Backtest run status."""
    SUCCESS = "success"
    ERROR = "error"


class SessionStage(str, Enum):
    """Reproduction session stage."""
    PENDING = "pending"
    EXTRACTING = "extracting"
    DATA_FETCHING = "data.fetching"
    BACKTESTING = "backtesting"
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"


# ─── Base models ──────────────────────────────────────────────


class WikiPage(BaseModel):
    """Base model for all Wiki pages."""
    title: str
    type: str
    status: PageStatus = PageStatus.DRAFT
    created: date = Field(default_factory=date.today)
    updated: date = Field(default_factory=date.today)

    def to_frontmatter(self) -> str:
        """Render to YAML frontmatter."""
        lines = [
            "---",
            f"title: {self.title}",
            f"type: {self.type}",
            f"status: {self.status.value}",
            f"created: {self.created.isoformat()}",
            f"updated: {self.updated.isoformat()}",
        ]
        return "\n".join(lines)


# ─── Page models ──────────────────────────────────────────────


class FactorPage(WikiPage):
    """Factor definition page."""
    type: str = "Factor"
    factor_class: FactorClass = FactorClass.UNKNOWN
    factor_params: dict[str, Any] = Field(default_factory=dict)
    signal_type: SignalType = SignalType.UNKNOWN
    signal_params: dict[str, Any] = Field(default_factory=dict)
    factor_source: str | None = None
    description: str | None = None
    formula: str | None = None

    @field_validator("factor_class", mode="before")
    @classmethod
    def validate_factor_class(cls, v: Any) -> FactorClass:
        if isinstance(v, str):
            try:
                return FactorClass(v)
            except ValueError:
                return FactorClass.UNKNOWN
        return v

    @field_validator("signal_type", mode="before")
    @classmethod
    def validate_signal_type(cls, v: Any) -> SignalType:
        if isinstance(v, str):
            try:
                return SignalType(v)
            except ValueError:
                return SignalType.UNKNOWN
        return v


class StrategyPage(WikiPage):
    """Strategy definition page."""
    type: str = "Strategy"
    strategy_class: StrategyClass = StrategyClass.UNKNOWN
    signal_type: SignalType = SignalType.UNKNOWN
    signal_params: dict[str, Any] = Field(default_factory=dict)
    factor_refs: list[str] = Field(default_factory=list)
    rebalance_freq: str = "daily"  # daily | weekly | monthly | quarterly
    description: str | None = None

    @field_validator("strategy_class", mode="before")
    @classmethod
    def validate_strategy_class(cls, v: Any) -> StrategyClass:
        if isinstance(v, str):
            try:
                return StrategyClass(v)
            except ValueError:
                return StrategyClass.UNKNOWN
        return v

    @field_validator("signal_type", mode="before")
    @classmethod
    def validate_signal_type(cls, v: Any) -> SignalType:
        if isinstance(v, str):
            try:
                return SignalType(v)
            except ValueError:
                return SignalType.UNKNOWN
        return v


class SourcePage(WikiPage):
    """Paper source page."""
    type: str = "Source"
    paper_id: str | None = None
    source_type: str = "pdf"  # pdf | url | text
    source_ref: str | None = None
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    extraction_status: str = "pending"  # pending | success | error


class BacktestResultPage(WikiPage):
    """Backtest result page (factor backtest)."""
    type: str = "BacktestResult"
    factor_ref: str | None = None
    strategy_ref: str | None = None
    universe: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    run_id: str | None = None

    # Factor backtest metrics
    ic_mean: float | None = None
    rank_ic_mean: float | None = None
    icir: float | None = None
    rank_icir: float | None = None
    win_rate: float | None = None
    annual_return: float | None = None
    longshort_ann_return: float | None = None
    longshort_sharpe: float | None = None
    longshort_max_dd: float | None = None

    # Strategy backtest metrics
    total_return: float | None = None
    final_cash: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    total_trades: int | None = None

    # Metadata
    adj_mode: str | None = None
    hedge: str | None = None
    data_source: str | None = None
    run_status: RunStatus = RunStatus.SUCCESS
    error: str | None = None

    @field_validator("run_status", mode="before")
    @classmethod
    def validate_run_status(cls, v: Any) -> RunStatus:
        if isinstance(v, str):
            try:
                return RunStatus(v)
            except ValueError:
                return RunStatus.SUCCESS
        return v


class ReproductionPage(WikiPage):
    """Reproduction report page."""
    type: str = "Reproduction"
    paper_ref: str | None = None
    factor_refs: list[str] = Field(default_factory=list)
    strategy_refs: list[str] = Field(default_factory=list)
    session_id: str | None = None
    stage: SessionStage = SessionStage.PENDING
    error: str | None = None

    @field_validator("stage", mode="before")
    @classmethod
    def validate_stage(cls, v: Any) -> SessionStage:
        if isinstance(v, str):
            try:
                return SessionStage(v)
            except ValueError:
                return SessionStage.PENDING
        return v


# ─── Page type registry ───────────────────────────────────────


PAGE_TYPES: dict[str, type[WikiPage]] = {
    "Factor": FactorPage,
    "Strategy": StrategyPage,
    "Source": SourcePage,
    "BacktestResult": BacktestResultPage,
    "Reproduction": ReproductionPage,
}


# ─── Rendering functions ──────────────────────────────────────


def render_page(page: WikiPage, body: str = "") -> str:
    """Render a WikiPage to markdown content.

    Args:
        page: WikiPage instance.
        body: Optional body content (markdown).

    Returns:
        Complete markdown content with frontmatter.
    """
    frontmatter = page.to_frontmatter()

    # Add type-specific fields
    lines = [frontmatter]

    if isinstance(page, FactorPage):
        lines.append(f"factor_class: {page.factor_class.value}")
        if page.factor_params:
            lines.append(f"factor_params: {page.factor_params}")
        lines.append(f"signal_type: {page.signal_type.value}")
        if page.signal_params:
            lines.append(f"signal_params: {page.signal_params}")
        if page.factor_source:
            lines.append(f"factor_source: {page.factor_source}")
        if page.description:
            lines.append(f"description: {page.description}")
        if page.formula:
            lines.append(f"formula: {page.formula}")

    elif isinstance(page, StrategyPage):
        lines.append(f"strategy_class: {page.strategy_class.value}")
        lines.append(f"signal_type: {page.signal_type.value}")
        if page.signal_params:
            lines.append(f"signal_params: {page.signal_params}")
        if page.factor_refs:
            lines.append(f"factor_refs: {page.factor_refs}")
        lines.append(f"rebalance_freq: {page.rebalance_freq}")
        if page.description:
            lines.append(f"description: {page.description}")

    elif isinstance(page, SourcePage):
        if page.paper_id:
            lines.append(f"paper_id: {page.paper_id}")
        lines.append(f"source_type: {page.source_type}")
        if page.source_ref:
            lines.append(f"source_ref: {page.source_ref}")
        if page.authors:
            lines.append(f"authors: {page.authors}")
        if page.abstract:
            lines.append(f"abstract: {page.abstract}")
        lines.append(f"extraction_status: {page.extraction_status}")

    elif isinstance(page, BacktestResultPage):
        if page.factor_ref:
            lines.append(f"factor_ref: {page.factor_ref}")
        if page.strategy_ref:
            lines.append(f"strategy_ref: {page.strategy_ref}")
        if page.universe:
            lines.append(f"universe: {page.universe}")
        if page.start_date:
            lines.append(f"start_date: {page.start_date.isoformat()}")
        if page.end_date:
            lines.append(f"end_date: {page.end_date.isoformat()}")
        if page.run_id:
            lines.append(f"run_id: {page.run_id}")
        if page.ic_mean is not None:
            lines.append(f"ic_mean: {page.ic_mean:.4f}")
        if page.rank_ic_mean is not None:
            lines.append(f"rank_ic_mean: {page.rank_ic_mean:.4f}")
        if page.icir is not None:
            lines.append(f"icir: {page.icir:.4f}")
        if page.rank_icir is not None:
            lines.append(f"rank_icir: {page.rank_icir:.4f}")
        if page.win_rate is not None:
            lines.append(f"win_rate: {page.win_rate:.4f}")
        if page.annual_return is not None:
            lines.append(f"annual_return: {page.annual_return:.4f}")
        if page.longshort_ann_return is not None:
            lines.append(f"longshort_ann_return: {page.longshort_ann_return:.4f}")
        if page.longshort_sharpe is not None:
            lines.append(f"longshort_sharpe: {page.longshort_sharpe:.4f}")
        if page.longshort_max_dd is not None:
            lines.append(f"longshort_max_dd: {page.longshort_max_dd:.4f}")
        if page.total_return is not None:
            lines.append(f"total_return: {page.total_return:.4f}")
        if page.final_cash is not None:
            lines.append(f"final_cash: {page.final_cash:.2f}")
        if page.sharpe_ratio is not None:
            lines.append(f"sharpe_ratio: {page.sharpe_ratio:.4f}")
        if page.max_drawdown is not None:
            lines.append(f"max_drawdown: {page.max_drawdown:.4f}")
        if page.total_trades is not None:
            lines.append(f"total_trades: {page.total_trades}")
        if page.adj_mode:
            lines.append(f"adj_mode: {page.adj_mode}")
        if page.hedge:
            lines.append(f"hedge: {page.hedge}")
        if page.data_source:
            lines.append(f"data_source: {page.data_source}")
        lines.append(f"run_status: {page.run_status.value}")
        if page.error:
            lines.append(f"error: {page.error}")

    elif isinstance(page, ReproductionPage):
        if page.paper_ref:
            lines.append(f"paper_ref: {page.paper_ref}")
        if page.factor_refs:
            lines.append(f"factor_refs: {page.factor_refs}")
        if page.strategy_refs:
            lines.append(f"strategy_refs: {page.strategy_refs}")
        if page.session_id:
            lines.append(f"session_id: {page.session_id}")
        lines.append(f"stage: {page.stage.value}")
        if page.error:
            lines.append(f"error: {page.error}")

    lines.append("---")

    if body:
        lines.append("")
        lines.append(body)

    return "\n".join(lines)


# ─── Parsing functions ────────────────────────────────────────


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Markdown content with frontmatter.

    Returns:
        Dict of frontmatter values.
    """
    from .utils import parse_frontmatter as _parse_frontmatter
    return _parse_frontmatter(content)


def parse_page(content: str) -> WikiPage | None:
    """Parse markdown content to a WikiPage.

    Args:
        content: Markdown content with frontmatter.

    Returns:
        WikiPage instance, or None if parsing fails.
    """
    fm = parse_frontmatter(content)
    if not fm:
        return None

    page_type = fm.get("type", "")
    if page_type not in PAGE_TYPES:
        return None

    page_cls = PAGE_TYPES[page_type]

    try:
        # Convert date strings
        for date_field in ("created", "updated", "start_date", "end_date"):
            if date_field in fm and isinstance(fm[date_field], str):
                try:
                    fm[date_field] = date.fromisoformat(fm[date_field])
                except ValueError:
                    pass

        return page_cls(**fm)
    except Exception:
        return None


__all__ = [
    "FactorClass",
    "SignalType",
    "StrategyClass",
    "PageStatus",
    "RunStatus",
    "SessionStage",
    "FactorPage",
    "StrategyPage",
    "SourcePage",
    "BacktestResultPage",
    "ReproductionPage",
    "PAGE_TYPES",
    "render_page",
    "parse_page",
    "parse_frontmatter",
]
