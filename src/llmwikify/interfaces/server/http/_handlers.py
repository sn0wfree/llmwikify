"""内置 Handler —— 可复用的单步处理器。

每个 Handler 实现 Handler 协议，处理一个具体步骤。
多个 Handler 通过 Helper 组合成完整的处理链。

可用 Handler:
- ReadBodyHandler: 读取原始 body，支持大小限制
- ParseJsonHandler: 解析 JSON
- ParseFormHandler: 解析 form data
- ValidateModelHandler: Pydantic model 校验
- LogHandler: 记录解析结果（钩子）
"""

from __future__ import annotations

import json
import logging

from fastapi import HTTPException
from pydantic import ValidationError

from ._helpers import HelperContext

logger = logging.getLogger(__name__)


class ReadBodyHandler:
    """读取原始 body，支持大小限制。

    写入:
        - ctx.raw: 原始 bytes
        - ctx.metadata["content_length"]: body 大小
        - ctx.metadata["content_type"]: Content-Type header
    """

    __slots__ = ("max_bytes",)

    def __init__(self, *, max_bytes: int = 1024 * 1024) -> None:
        self.max_bytes = max_bytes

    async def execute(self, ctx: HelperContext) -> None:
        ctx.raw = await ctx.request.body()
        if len(ctx.raw) > self.max_bytes:
            raise HTTPException(413, "request body too large")
        ctx.metadata["content_length"] = len(ctx.raw)
        ctx.metadata["content_type"] = ctx.request.headers.get("content-type", "")


class ParseJsonHandler:
    """解析 JSON body。

    读取: ctx.raw
    写入: ctx.parsed (dict)
    """

    __slots__ = ()

    async def execute(self, ctx: HelperContext) -> None:
        if not ctx.raw:
            raise HTTPException(400, "request body required")
        try:
            ctx.parsed = json.loads(ctx.raw)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"invalid JSON: {e}") from e


class ParseFormHandler:
    """解析 form data。

    读取: ctx.request
    写入: ctx.parsed (dict)
    """

    __slots__ = ()

    async def execute(self, ctx: HelperContext) -> None:
        form = await ctx.request.form()
        ctx.parsed = dict(form)


class ValidateModelHandler:
    """Pydantic model 校验。

    读取: ctx.parsed, ctx.model
    写入: ctx.result (model 实例)
    """

    __slots__ = ()

    async def execute(self, ctx: HelperContext) -> None:
        try:
            ctx.result = ctx.model(**ctx.parsed)
        except ValidationError as e:
            raise HTTPException(422, str(e)) from e


class LogHandler:
    """记录解析结果（钩子）。

    读取: ctx.model, ctx.parsed, ctx.metadata
    """

    __slots__ = ()

    async def execute(self, ctx: HelperContext) -> None:
        logger.info(
            "Parsed %s: %d fields, content_type=%s",
            ctx.model.__name__,
            len(ctx.parsed),
            ctx.metadata.get("content_type", "unknown"),
        )
