"""Configuration manager for reproduction module.

Centralizes all configurable parameters with three-layer priority:
1. Environment variables (highest priority)
2. Config file (~/.llmwikify/llmwikify.json)
3. Code defaults (lowest priority)

Usage:
    from llmwikify.reproduction.config import config

    # Get a value
    db_path = config.get("db.path")

    # Get with default
    timeout = config.get("akshare.timeout_s", default=5.0)

    # Validate all config
    errors = config.validate()
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".llmwikify" / "llmwikify.json"

# Default values for all parameters
DEFAULTS: dict[str, Any] = {
    "db.path": "~/.llmwikify/agent/reproduction.db",
    "ifind.config_path": "~/.llmwikify/ifind_http.yaml",
    "ifind.date_sequence_url": "https://quantapi.51ifind.com/api/v1/date_sequence",
    "ifind.mcp_dir": "~/Public/ifind-finance-data-1.1.0",
    "clickhouse.host": "0.0.0.0",
    "clickhouse.port": 8123,
    "clickhouse.user": "default",
    "clickhouse.password": "",
    "clickhouse.database": "quote",
    "clickhouse.table": "cn_stock",
    "backtest.initial_cash": 1000000,
    "backtest.commission": 0.001,
    "backtest.default_benchmark": "000300.SH",
    "backtest.trading_days": 252,
    "backtest.risk_free_rate": 0.03,
    "synth.n_days": 60,
    "synth.base_price": 10.0,
    "akshare.timeout_s": 5.0,
    "wiki.factor_dir": "factor",
    "wiki.strategy_dir": "strategy",
    "wiki.sources_dir": "sources",
    "wiki.reproduction_dir": "reproduction",
}

# Environment variable mapping (config.key -> env var name)
ENV_MAP: dict[str, str] = {
    "db.path": "LLMWIKIFY_DB_PATH",
    "ifind.config_path": "IFIND_CONFIG_PATH",
    "ifind.date_sequence_url": "IFIND_DATE_SEQUENCE_URL",
    "ifind.mcp_dir": "IFIND_MCP_DIR",
    "clickhouse.host": "CLICKHOUSE_HOST",
    "clickhouse.port": "CLICKHOUSE_PORT",
    "clickhouse.user": "CLICKHOUSE_USER",
    "clickhouse.password": "CLICKHOUSE_PASSWORD",
    "clickhouse.database": "CLICKHOUSE_DATABASE",
    "clickhouse.table": "CLICKHOUSE_TABLE",
    "backtest.initial_cash": "LLMWIKIFY_INITIAL_CASH",
    "backtest.commission": "LLMWIKIFY_COMMISSION",
    "backtest.default_benchmark": "LLMWIKIFY_DEFAULT_BENCHMARK",
    "backtest.trading_days": "LLMWIKIFY_TRADING_DAYS",
    "backtest.risk_free_rate": "LLMWIKIFY_RISK_FREE_RATE",
    "synth.n_days": "LLMWIKIFY_SYNTH_N_DAYS",
    "synth.base_price": "LLMWIKIFY_SYNTH_BASE_PRICE",
    "akshare.timeout_s": "LLMWIKIFY_AKSHARE_TIMEOUT",
}


class Config:
    """Configuration manager with three-layer priority.

    Priority: Environment variable > Config file > Code default
    """

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = self._load()

    def _load(self) -> dict:
        """Load configuration from file."""
        if not self.config_path.exists():
            logger.info("Config file not found: %s, using defaults", self.config_path)
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            # Extract reproduction section if exists
            return data.get("reproduction", data)
        except Exception as exc:
            logger.warning("Failed to load config from %s: %s", self.config_path, exc)
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with three-layer priority.

        Args:
            key: Dotted config path (e.g., "clickhouse.host")
            default: Default value if not found anywhere

        Returns:
            Configuration value
        """
        # 1. Check environment variable
        env_key = ENV_MAP.get(key)
        if env_key:
            env_val = os.getenv(env_key)
            if env_val is not None:
                return self._parse_env_value(env_val)

        # 2. Check config file (dotted path traversal)
        val = self._get_nested(self._config, key)

        # 3. Fall back to code default
        if val is not None:
            return val
        return DEFAULTS.get(key, default)

    def _get_nested(self, data: dict, key: str) -> Any:
        """Get nested value from dict using dotted path."""
        parts = key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _parse_env_value(self, val: str) -> Any:
        """Parse environment variable value to appropriate type."""
        if val.lower() in ("true", "false"):
            return val.lower() == "true"
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val

    def set(self, key: str, value: Any) -> None:
        """Set configuration value (in-memory only, not persisted).

        Args:
            key: Dotted config path (e.g., "clickhouse.host")
            value: Value to set
        """
        parts = key.split(".")
        current = self._config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def save(self) -> None:
        """Save current configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing file to preserve other sections
        existing = {}
        if self.config_path.exists():
            try:
                existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Update reproduction section
        existing["reproduction"] = self._config

        self.config_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Config saved to %s", self.config_path)

    def validate(self) -> list[str]:
        """Validate configuration completeness and types.

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check required paths exist
        db_path = Path(self.get("db.path", "")).expanduser()
        if not db_path.parent.exists():
            errors.append(f"db.path parent directory does not exist: {db_path.parent}")

        # Check numeric types
        for key in ["backtest.initial_cash", "backtest.commission", "backtest.trading_days"]:
            val = self.get(key)
            if val is not None and not isinstance(val, (int, float)):
                errors.append(f"{key} must be numeric, got {type(val).__name__}")

        # Check ClickHouse config
        ch_host = self.get("clickhouse.host")
        ch_port = self.get("clickhouse.port")
        if not ch_host:
            errors.append("clickhouse.host is required")
        if not isinstance(ch_port, int) or ch_port <= 0:
            errors.append(f"clickhouse.port must be positive integer, got {ch_port}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Export all config values as flat dict (for debugging)."""
        result = {}
        for key, default_val in DEFAULTS.items():
            result[key] = self.get(key, default_val)
        return result

    def __repr__(self) -> str:
        return f"Config(path={self.config_path})"


# Global singleton instance
config = Config()


__all__ = ["Config", "config", "DEFAULTS", "ENV_MAP"]
