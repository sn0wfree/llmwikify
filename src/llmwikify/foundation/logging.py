"""Unified logging setup + timing decorator for llmwikify (L1 foundation).

This is the single entry point for configuring the root logger. All layers
(server, CLI, scripts, tests) route through ``setup_logging`` instead of
calling ``logging.basicConfig`` with ad-hoc format strings.

Modules should keep using ``logger = logging.getLogger(__name__)``; this
module only configures handlers on the root logger.

Usage::

    from llmwikify.foundation.logging import setup_logging, log_timing

    setup_logging()                       # server: file + console
    setup_logging(log_file=None)          # CLI / scripts: console only
    setup_logging(fmt="%(message)s", log_file=None, force=True)

    @log_timing()
    def expensive(): ...

    @log_timing(level=logging.DEBUG, label="track_a")
    async def run_track_a(): ...
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TypeVar

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

F = TypeVar("F", bound=Callable[..., Any])


def setup_logging(
    level: int = logging.INFO,
    log_dir: Path | None = None,
    log_file: str | None = "server.log",
    console: bool = True,
    fmt: str | None = None,
    datefmt: str | None = None,
    force: bool = False,
) -> None:
    """Configure the root logger with optional file + console handlers.

    Idempotent: if the root logger already has handlers and ``force`` is
    False, this is a no-op (so repeated calls don't stack handlers).

    Args:
        level: root logger level (default INFO).
        log_dir: directory for the log file. None -> ``~/.llmwikify/agent``.
            Only used when ``log_file`` is not None.
        log_file: file name for the RotatingFileHandler (10MB x5). None
            disables the file handler (console-only mode).
        console: attach a StreamHandler to stdout/stderr (default True).
        fmt: log format string. None -> ``DEFAULT_FORMAT``.
        datefmt: date format string passed to the Formatter.
        force: clear existing root handlers and reconfigure.
    """
    root = logging.getLogger()
    if root.handlers:
        if not force:
            return
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    root.setLevel(level)
    formatter = logging.Formatter(fmt or DEFAULT_FORMAT, datefmt=datefmt)

    if log_file is not None:
        if log_dir is None:
            log_dir = Path.home() / ".llmwikify" / "agent"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / log_file, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)

    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        root.addHandler(sh)


def log_timing(
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    label: str = "",
) -> Callable[[F], F]:
    """Decorate a sync or async function to log entry, exit, and elapsed time.

    Logs ``start <name>`` on entry and ``<name> done in <s>s`` on return.
    Automatically detects async functions and wraps accordingly.

    Args:
        logger: logger to use. None -> ``getLogger(fn.__module__)``.
        level: logging level for the timing messages (default INFO).
        label: optional prefix prepended to the function name.
    """
    def decorator(fn: F) -> F:
        log = logger or logging.getLogger(fn.__module__)
        name = f"{label}.{fn.__name__}" if label else fn.__name__

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                log.log(level, "start %s", name)
                t0 = time.monotonic()
                try:
                    return await fn(*args, **kwargs)
                finally:
                    log.log(level, "%s done in %.3fs", name, time.monotonic() - t0)
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            log.log(level, "start %s", name)
            t0 = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                log.log(level, "%s done in %.3fs", name, time.monotonic() - t0)
        return sync_wrapper  # type: ignore[return-value]

    return decorator
