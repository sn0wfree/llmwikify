"""Tests for foundation/logging: setup_logging + log_timing.

Covers idempotency, console-only mode, force-reconfigure, custom format,
and the sync/async timing decorator.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from llmwikify.foundation.logging import DEFAULT_FORMAT, log_timing, setup_logging


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    for h in saved:
        root.removeHandler(h)
    yield root
    for h in root.handlers[:]:
        root.removeHandler(h)
    for h in saved:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_console_only_adds_stream_handler(clean_root):
    setup_logging(log_file=None, console=True)
    assert any(isinstance(h, logging.StreamHandler) for h in clean_root.handlers)
    assert not any(
        isinstance(h, logging.FileHandler) for h in clean_root.handlers
    )


def test_idempotent_no_duplicate_handlers(clean_root):
    setup_logging(log_file=None)
    n = len(clean_root.handlers)
    setup_logging(log_file=None)
    assert len(clean_root.handlers) == n


def test_force_reconfigures(clean_root):
    setup_logging(log_file=None, fmt="%(message)s")
    setup_logging(log_file=None, fmt="X %(message)s", force=True)
    fmts = [h.formatter._fmt for h in clean_root.handlers if h.formatter]
    assert fmts == ["X %(message)s"]  # old handler cleared, only forced one remains


def test_default_format_used(clean_root):
    setup_logging(log_file=None, force=True)
    fmts = [h.formatter._fmt for h in clean_root.handlers if h.formatter]
    assert DEFAULT_FORMAT in fmts


def test_log_timing_sync_returns_value(clean_root, caplog):
    log = logging.getLogger("timing_sync")

    @log_timing(logger=log, label="job")
    def add(a, b):
        return a + b

    with caplog.at_level(logging.INFO, logger="timing_sync"):
        assert add(2, 3) == 5
    assert "start job.add" in caplog.text
    assert "job.add done in" in caplog.text


def test_log_timing_async_returns_value(clean_root, caplog):
    log = logging.getLogger("timing_async")

    @log_timing(logger=log)
    async def aadd(a, b):
        await asyncio.sleep(0)
        return a + b

    with caplog.at_level(logging.INFO, logger="timing_async"):
        assert asyncio.run(aadd(2, 3)) == 5
    assert "start aadd" in caplog.text
    assert "aadd done in" in caplog.text
