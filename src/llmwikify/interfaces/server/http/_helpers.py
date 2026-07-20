"""Helper 框架核心 —— Helper 类、Handler 协议、HelperContext。

可组合的请求解析框架。Helper 链式组合多个 Handler，每个 Handler
处理一个具体步骤（读取 body / 解析 JSON / 校验 model 等）。

用法::

    from llmwikify.interfaces.server.http._helpers import Helper
    from llmwikify.interfaces.server.http._handlers import (
        ReadBodyHandler, ParseJsonHandler, ValidateModelHandler,
    )

    JsonBodyHelper = (
        Helper()
        .add_handler(ReadBodyHandler())
        .add_handler(ParseJsonHandler())
        .add_handler(ValidateModelHandler())
    )

    # endpoint 中
    req = await JsonBodyHelper.execute(request, ChatRequest)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from fastapi import Request
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Handler(Protocol):
    """单步处理器协议。任何实现 execute 方法的类都是合法 Handler。"""

    async def execute(self, ctx: HelperContext) -> None:
        ...


@dataclass(slots=True)
class HelperContext:
    """Helper 上下文，Handler 间共享数据。

    步骤之间通过 ctx 传递数据：
    - ReadBodyHandler 写入 ctx.raw
    - ParseJsonHandler 读取 ctx.raw，写入 ctx.parsed
    - ValidateModelHandler 读取 ctx.parsed，写入 ctx.result
    """
    request: Request
    model: type[BaseModel]
    raw: bytes = b""
    parsed: dict = field(default_factory=dict)
    result: BaseModel | None = None
    metadata: dict = field(default_factory=dict)


class Helper:
    """链式处理器，组合多个 Handler。

    Args:
        debug: 启用调试日志，输出每个 Handler 的执行状态。
    """

    __slots__ = ("_handlers", "_debug", "_logger")

    def __init__(self, *, debug: bool = False) -> None:
        self._handlers: list[Handler] = []
        self._debug = debug
        self._logger = logging.getLogger(__name__)

    def add_handler(self, handler: Handler) -> Helper:
        """添加 Handler，返回 self 支持链式调用。"""
        self._handlers.append(handler)
        return self

    async def execute(self, request: Request, model: type[T]) -> T:
        """执行 Helper，返回校验后的 model 实例。

        Args:
            request: FastAPI Request
            model: Pydantic BaseModel 子类

        Returns:
            校验后的 model 实例

        Raises:
            HTTPException: Handler 抛出的任何 HTTPException
        """
        ctx = HelperContext(request=request, model=model)
        for i, handler in enumerate(self._handlers):
            handler_name = type(handler).__name__
            step_info = f"step {i + 1}/{len(self._handlers)}: {handler_name}"
            if self._debug:
                self._logger.debug(
                    "Helper[%s] %s started | raw=%d bytes, parsed=%d keys",
                    id(self), step_info, len(ctx.raw), len(ctx.parsed),
                )
            try:
                await handler.execute(ctx)
            except Exception as e:
                self._logger.error(
                    "Helper[%s] %s failed: %s",
                    id(self), step_info, e,
                )
                raise
            if self._debug:
                self._logger.debug(
                    "Helper[%s] %s completed | raw=%d bytes, parsed=%d keys, result=%s",
                    id(self), step_info, len(ctx.raw), len(ctx.parsed),
                    type(ctx.result).__name__ if ctx.result else "None",
                )
        return ctx.result  # type: ignore[return-value]
