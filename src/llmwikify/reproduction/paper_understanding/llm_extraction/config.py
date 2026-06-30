"""Pass2Config v4.0 — 4-Layer Configuration Architecture.

Layers (low → high priority):
  L0: dataclass default values (in this file)
  L1: env vars (PASS2_*, HYBRID_*, ADAPTIVE_*, etc.)
  L2: JSON file (~/.llmwikify/llmwikify.json field, or --pass2-config path)
  L3: CLI flags (--pass2-mode, --max-concurrency, etc.)
  L4: function argument `cfg: Pass2Config`

Use `PASS2_CONFIG` singleton (L0 + L1) for module-level defaults.

Refs:
  - docs/designs/pass2_config_v4.md
  - v3.0 smart mode + v3.1 hybrid mode + v3.2 supplement prompt
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# ─── Env var prefix mapping ─────────────────────────────────────────
# Not all fields use the same env var name. Some legacy names from v3.0
# (HYBRID_*, ADAPTIVE_*) are kept for backward compat.
_ENV_OVERRIDES: dict[str, str] = {
    # field name → env var name
    "mode_override": "PASS2_MODE_OVERRIDE",
    "mode_auto": "PASS2_MODE_AUTO",
    "max_concurrency": "PASS2_MAX_CONCURRENCY",
    "batch_size": "PASS2_BATCH_SIZE",
    "max_history_messages": "PASS2_MAX_HISTORY_MESSAGES",
    "max_supplements_per_signal": "PASS2_MAX_SUPPLEMENTS_PER_SIGNAL",
    "max_total_rounds": "PASS2_MAX_TOTAL_ROUNDS",
    "success_threshold_high": "PASS2_SUCCESS_THRESHOLD_HIGH",
    "success_threshold_low": "PASS2_SUCCESS_THRESHOLD_LOW",
    "max_retry_rounds": "PASS2_MAX_RETRY_ROUNDS",
    "hybrid_enabled": "PASS2_HYBRID_ENABLED",
    "hybrid_min_signals_auto": "HYBRID_MIN_SIGNALS_AUTO",
    "hybrid_intuition_threshold": "HYBRID_INTUITION_THRESHOLD",
    "hybrid_theoretical_min": "HYBRID_THEORETICAL_MIN",
    "hybrid_hypotheses_min": "HYBRID_HYPOTHESES_MIN",
    "hybrid_supplement_ratio": "HYBRID_SUPPLEMENT_RATIO",
    "hybrid_min_supplements": "HYBRID_MIN_SUPPLEMENTS",
    "hybrid_supplement_batch_size": "HYBRID_SUPPLEMENT_BATCH_SIZE",
    "hybrid_supplement_concurrency": "HYBRID_SUPPLEMENT_CONCURRENCY",
    "hybrid_supplement_use_specific_prompt": "HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT",
    "adaptive_min_signals": "ADAPTIVE_MIN_SIGNALS",
    "adaptive_max_signals": "ADAPTIVE_MAX_SIGNALS",
    "adaptive_avg_formula_len": "ADAPTIVE_AVG_FORMULA_LEN",
    "adaptive_avg_context_len": "ADAPTIVE_AVG_CONTEXT_LEN",
    "max_rounds": "PASS1_MAX_ROUNDS",
    "max_consecutive_zero": "PASS1_MAX_CONSECUTIVE_ZERO",
    "pass1_max_tokens_default": "PASS1_MAX_TOKENS_DEFAULT",
    "pass1_max_tokens_fallback": "PASS1_MAX_TOKENS_FALLBACK",
    "temperature": "PASS2_TEMPERATURE",
}


def _coerce(raw: str, target_type: Any) -> Any:
    """Coerce a string env var value to the target dataclass field type."""
    if target_type is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if target_type is int:
        return int(raw)
    if target_type is float:
        return float(raw)
    return raw


@dataclass(frozen=True)
class Pass2Config:
    """All Pass 2 (and Pass 1 multi-turn) tunable parameters.

    See docs/designs/pass2_config_v4.md §3 for full field inventory.
    """

    # ─── Adaptive multi-turn (v2.0) ─────────────────────────────────
    batch_size: int = 3
    max_history_messages: int = 20
    max_supplements_per_signal: int = 5
    max_total_rounds: int = 200

    # ─── Parallel ────────────────────────────────────────────────────
    max_concurrency: int = 3
    checkpoint_batch_size: int = 10

    # ─── Smart mode selection (v3.0) ─────────────────────────────────
    mode_auto: bool = True
    mode_override: str = ""  # "" | "adaptive" | "parallel" | "serial" | "hybrid"
    adaptive_min_signals: int = 20
    adaptive_max_signals: int = 200
    adaptive_avg_formula_len: int = 80
    adaptive_avg_context_len: int = 2000

    # ─── Hybrid mode (v3.1) ──────────────────────────────────────────
    hybrid_enabled: bool = True
    hybrid_min_signals_auto: int = 30  # signal_count >= this + complexity=adaptive → hybrid
    hybrid_intuition_threshold: int = 150
    hybrid_theoretical_min: int = 50
    hybrid_hypotheses_min: int = 2
    hybrid_supplement_ratio: float = 0.2
    hybrid_min_supplements: int = 3
    hybrid_supplement_batch_size: int = 4
    hybrid_supplement_concurrency: int = 3
    hybrid_supplement_use_specific_prompt: bool = True

    # ─── Success rate / retry ────────────────────────────────────────
    success_threshold_high: float = 0.95
    success_threshold_low: float = 0.80
    max_retry_rounds: int = 1

    # ─── Pass 1 multi-turn ───────────────────────────────────────────
    max_rounds: int = 10
    max_consecutive_zero: int = 2
    pass1_max_tokens_default: int = 32000
    pass1_max_tokens_fallback: int = 16384

    # ─── Context slicing (function-internal magic numbers) ───────────
    context_min_chars: int = 50
    fallback_slice_size: int = 5000

    # ─── Supplement levels (a/b/c) ───────────────────────────────────
    level_a_chars: int = 2000
    level_b_chars: int = 7000
    level_b_anchor_offset: int = 1000
    level_b_min_chars: int = 5000

    # ─── LLM sampling ────────────────────────────────────────────────
    temperature: float = 0.1

    # ─── Estimator weights (estimate_complexity) ─────────────────────
    complexity_signal_weight_high: float = 0.4
    complexity_formula_weight_max: float = 0.3
    complexity_formula_divisor: float = 300
    complexity_context_threshold: float = 1500
    complexity_context_weight: float = 0.3

    # ─── Planner token budgets (used by planner.py) ─────────────────
    planner_token_budget_default: dict = field(default_factory=lambda: {
        "track_a_tier1": 4500,
        "track_a_tier2_per_section": 3000,
        "track_b_pass1": 3500,
        "track_b_pass2_per_factor": 5500,
        "preview": 2000,
    })
    planner_token_budget_floor: dict = field(default_factory=lambda: {
        "track_a_tier1": 3072,
        "track_a_tier2_per_section": 2048,
        "track_b_pass1": 32000,
        "track_b_pass2_per_factor": 4096,
        "preview": 1536,
    })
    valid_schemas: frozenset = field(
        default_factory=lambda: frozenset({"factor", "signal", "allocation", "summary"})
    )

    # ─── Display truncation (preview/log) ───────────────────────────
    preview_table_max_rows: int = 30
    preview_table_max_kw: int = 10
    preview_table_max_strat_chars: int = 300
    raw_response_preview_chars: int = 1000
    issue_bullet_preview_chars: int = 200
    suggestion_bullet_preview_chars: int = 200
    revised_section_preview_chars: int = 500

    # ─── Retry ───────────────────────────────────────────────────────
    retry_max_attempts: int = 3
    retry_backoff_base: float = 0.5

    # ─── Methods ─────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> Pass2Config:
        """L1: Read overrides from environment variables.

        Naming convention: see `_ENV_OVERRIDES` mapping (legacy HYBRID_*/ADAPTIVE_*
        kept for backward compat).
        """
        overrides: dict[str, Any] = {}
        for f in fields(cls):
            env_key = _ENV_OVERRIDES.get(f.name)
            if not env_key:
                continue
            raw = os.getenv(env_key)
            if raw is None:
                continue
            try:
                overrides[f.name] = _coerce(raw, f.type)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Invalid env var {env_key}={raw!r} for field {f.name}: {exc}"
                ) from exc
        return cls(**overrides) if overrides else cls()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Pass2Config:
        """L2: Load from a dict (e.g., parsed JSON config).

        Unknown keys are ignored. Field-level validation via type coercion.
        """
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_file(cls, path: str | Path) -> Pass2Config:
        """L2: Load from a JSON file."""
        return cls.from_dict(json.loads(Path(path).read_text()))

    def merge(self, *overrides: Pass2Config | dict) -> Pass2Config:
        """L3/L4: Merge later overrides on top of self.

        Example:
            cfg = PASS2_CONFIG.merge({"mode_override": "hybrid"})
            cfg = cfg.merge(cli_overrides)
        """
        merged = asdict(self)
        for o in overrides:
            if isinstance(o, Pass2Config):
                merged.update(asdict(o))
            elif isinstance(o, dict):
                merged.update({k: v for k, v in o.items() if k in merged})
        return Pass2Config.from_dict(merged)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict (frozenset → list)."""
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, frozenset):
                d[k] = sorted(v)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ─── Module-level singleton (L0 defaults + L1 env overrides) ────────
PASS2_CONFIG: Pass2Config = Pass2Config.from_env()


__all__ = [
    "Pass2Config",
    "PASS2_CONFIG",
]
