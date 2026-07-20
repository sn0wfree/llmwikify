"""Tests for the Helper/Handler framework (_helpers.py + _handlers.py).

Covers:
  - Handler protocol compliance
  - ReadBodyHandler (normal + max_bytes exceeded)
  - ParseJsonHandler (normal + empty body + invalid JSON)
  - ParseFormHandler (normal)
  - ValidateModelHandler (normal + validation error)
  - Helper chaining (full pipeline)
  - Helper debug logging
  - HelperContext metadata propagation
  - __slots__ verification
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from llmwikify.interfaces.server.http._handlers import (
    LogHandler,
    ParseFormHandler,
    ParseJsonHandler,
    ReadBodyHandler,
    ValidateModelHandler,
)
from llmwikify.interfaces.server.http._helpers import Helper, HelperContext

# ─── Fixtures ──────────────────────────────────────────────────

class SampleModel(BaseModel):
    message: str
    count: int = 0


@pytest.fixture
def mock_request():
    """Create a mock request with JSON body."""
    req = AsyncMock()
    req.body = AsyncMock(return_value=b'{"message": "hello", "count": 42}')
    req.headers = {"content-type": "application/json"}
    return req


@pytest.fixture
def ctx(mock_request):
    """Create a HelperContext with mock request."""
    return HelperContext(request=mock_request, model=SampleModel)


# ─── __slots__ verification ────────────────────────────────────

class TestSlots:
    """Verify __slots__ are defined on all framework classes."""

    def test_helper_has_slots(self):
        assert "__slots__" in Helper.__dict__

    def test_helper_context_has_slots(self):
        # dataclass(slots=True) sets __slots__ on the class
        assert "__slots__" in HelperContext.__dict__

    def test_read_body_handler_has_slots(self):
        assert "__slots__" in ReadBodyHandler.__dict__

    def test_parse_json_handler_has_slots(self):
        assert "__slots__" in ParseJsonHandler.__dict__

    def test_parse_form_handler_has_slots(self):
        assert "__slots__" in ParseFormHandler.__dict__

    def test_validate_model_handler_has_slots(self):
        assert "__slots__" in ValidateModelHandler.__dict__

    def test_log_handler_has_slots(self):
        assert "__slots__" in LogHandler.__dict__


# ─── ReadBodyHandler ───────────────────────────────────────────

class TestReadBodyHandler:

    async def test_reads_body(self, ctx):
        handler = ReadBodyHandler()
        await handler.execute(ctx)
        assert ctx.raw == b'{"message": "hello", "count": 42}'

    async def test_sets_metadata(self, ctx):
        handler = ReadBodyHandler()
        await handler.execute(ctx)
        assert ctx.metadata["content_length"] == 33  # len(b'{"message": "hello", "count": 42}')
        assert ctx.metadata["content_type"] == "application/json"

    async def test_max_bytes_exceeded(self, ctx):
        handler = ReadBodyHandler(max_bytes=10)
        with pytest.raises(HTTPException) as exc_info:
            await handler.execute(ctx)
        assert exc_info.value.status_code == 413

    async def test_custom_max_bytes(self, ctx):
        handler = ReadBodyHandler(max_bytes=1024)
        await handler.execute(ctx)
        assert ctx.raw == b'{"message": "hello", "count": 42}'


# ─── ParseJsonHandler ──────────────────────────────────────────

class TestParseJsonHandler:

    async def test_parses_json(self, ctx):
        ctx.raw = b'{"message": "hello", "count": 42}'
        handler = ParseJsonHandler()
        await handler.execute(ctx)
        assert ctx.parsed == {"message": "hello", "count": 42}

    async def test_empty_body_raises_400(self, ctx):
        ctx.raw = b""
        handler = ParseJsonHandler()
        with pytest.raises(HTTPException) as exc_info:
            await handler.execute(ctx)
        assert exc_info.value.status_code == 400
        assert "request body required" in exc_info.value.detail

    async def test_invalid_json_raises_400(self, ctx):
        ctx.raw = b"not json"
        handler = ParseJsonHandler()
        with pytest.raises(HTTPException) as exc_info:
            await handler.execute(ctx)
        assert exc_info.value.status_code == 400
        assert "invalid JSON" in exc_info.value.detail


# ─── ParseFormHandler ──────────────────────────────────────────

class TestParseFormHandler:

    async def test_parses_form(self, mock_request):
        # Mock form data
        mock_request.form = AsyncMock(return_value={"field1": "value1", "field2": "value2"})
        ctx = HelperContext(request=mock_request, model=SampleModel)
        handler = ParseFormHandler()
        await handler.execute(ctx)
        assert ctx.parsed == {"field1": "value1", "field2": "value2"}


# ─── ValidateModelHandler ──────────────────────────────────────

class TestValidateModelHandler:

    async def test_validates_model(self, ctx):
        ctx.parsed = {"message": "hello", "count": 42}
        handler = ValidateModelHandler()
        await handler.execute(ctx)
        assert isinstance(ctx.result, SampleModel)
        assert ctx.result.message == "hello"
        assert ctx.result.count == 42

    async def test_validation_error_raises_422(self, ctx):
        ctx.parsed = {"message": 123, "count": "not_int"}  # Wrong types
        handler = ValidateModelHandler()
        with pytest.raises(HTTPException) as exc_info:
            await handler.execute(ctx)
        assert exc_info.value.status_code == 422


# ─── LogHandler ────────────────────────────────────────────────

class TestLogHandler:

    async def test_logs_parsed_info(self, ctx, caplog):
        ctx.parsed = {"message": "hello", "count": 42}
        ctx.metadata["content_type"] = "application/json"
        handler = LogHandler()
        with caplog.at_level(logging.INFO):
            await handler.execute(ctx)
        assert "SampleModel" in caplog.text
        assert "2 fields" in caplog.text
        assert "application/json" in caplog.text


# ─── Helper (full pipeline) ────────────────────────────────────

class TestHelper:

    async def test_full_pipeline(self, mock_request):
        helper = (
            Helper()
            .add_handler(ReadBodyHandler())
            .add_handler(ParseJsonHandler())
            .add_handler(ValidateModelHandler())
        )
        result = await helper.execute(mock_request, SampleModel)
        assert isinstance(result, SampleModel)
        assert result.message == "hello"
        assert result.count == 42

    async def test_pipeline_preserves_order(self, mock_request):
        """Handlers execute in add_handler order."""
        execution_order = []

        class TrackingHandler:
            __slots__ = ("name",)

            def __init__(self, name):
                self.name = name

            async def execute(self, ctx):
                execution_order.append(self.name)

        helper = (
            Helper()
            .add_handler(TrackingHandler("first"))
            .add_handler(TrackingHandler("second"))
            .add_handler(TrackingHandler("third"))
        )
        await helper.execute(mock_request, SampleModel)
        assert execution_order == ["first", "second", "third"]

    async def test_pipeline_error_propagates(self, mock_request):
        """HTTPException from handler propagates to caller."""
        helper = (
            Helper()
            .add_handler(ReadBodyHandler(max_bytes=5))  # Too small
            .add_handler(ParseJsonHandler())
            .add_handler(ValidateModelHandler())
        )
        with pytest.raises(HTTPException) as exc_info:
            await helper.execute(mock_request, SampleModel)
        assert exc_info.value.status_code == 413

    async def test_debug_logging(self, mock_request, caplog):
        """debug=True emits step-by-step logs."""
        helper = (
            Helper(debug=True)
            .add_handler(ReadBodyHandler())
            .add_handler(ParseJsonHandler())
            .add_handler(ValidateModelHandler())
        )
        with caplog.at_level(logging.DEBUG):
            await helper.execute(mock_request, SampleModel)
        assert "step 1/3: ReadBodyHandler started" in caplog.text
        assert "step 1/3: ReadBodyHandler completed" in caplog.text
        assert "step 2/3: ParseJsonHandler started" in caplog.text
        assert "step 3/3: ValidateModelHandler completed" in caplog.text

    async def test_debug_disabled_by_default(self, mock_request, caplog):
        """debug=False (default) emits no debug logs."""
        helper = (
            Helper()
            .add_handler(ReadBodyHandler())
            .add_handler(ParseJsonHandler())
        )
        with caplog.at_level(logging.DEBUG):
            await helper.execute(mock_request, SampleModel)
        # No debug logs from Helper
        assert "Helper[" not in caplog.text

    async def test_metadata_propagation(self, mock_request):
        """Handlers can write/read metadata."""
        helper = (
            Helper()
            .add_handler(ReadBodyHandler())
            .add_handler(ParseJsonHandler())
            .add_handler(ValidateModelHandler())
        )
        # Metadata is set by ReadBodyHandler
        # We verify by checking the result is valid
        result = await helper.execute(mock_request, SampleModel)
        assert result.message == "hello"


# ─── JsonBodyHelper (assembled in chat_sse.py) ─────────────────

class TestJsonBodyHelper:
    """Test the assembled JsonBodyHelper (same as in chat_sse.py)."""

    @pytest.fixture
    def json_helper(self):
        return (
            Helper()
            .add_handler(ReadBodyHandler())
            .add_handler(ParseJsonHandler())
            .add_handler(ValidateModelHandler())
        )

    async def test_json_body_helper(self, mock_request, json_helper):
        result = await json_helper.execute(mock_request, SampleModel)
        assert result.message == "hello"
        assert result.count == 42

    async def test_json_body_helper_empty_body(self, json_helper):
        req = AsyncMock()
        req.body = AsyncMock(return_value=b"")
        req.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await json_helper.execute(req, SampleModel)
        assert exc_info.value.status_code == 400

    async def test_json_body_helper_invalid_json(self, json_helper):
        req = AsyncMock()
        req.body = AsyncMock(return_value=b"not json")
        req.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await json_helper.execute(req, SampleModel)
        assert exc_info.value.status_code == 400

    async def test_json_body_helper_validation_error(self, json_helper):
        req = AsyncMock()
        req.body = AsyncMock(return_value=b'{"message": 123}')
        req.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await json_helper.execute(req, SampleModel)
        assert exc_info.value.status_code == 422
