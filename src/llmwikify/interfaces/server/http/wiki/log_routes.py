"""日志路由 — 客户端错误日志（1 端点）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request


def register_log_routes(app) -> None:
    """注册客户端错误日志路由。"""

    log_router = APIRouter(tags=["log"])
    _log_logger = logging.getLogger("client.errors")

    @log_router.post("/api/log/error")
    async def log_client_error(request: Request):
        """Receive frontend error reports and write to server log."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        err_type = body.get("type", "unknown")
        message = body.get("message", "")
        url = body.get("url", "")
        filename = body.get("filename", "")
        lineno = body.get("lineno", "")
        colno = body.get("colno", "")
        stack = body.get("stack", "")
        status = body.get("status", "")
        method = body.get("method", "")
        req_body = body.get("requestBody", "")
        content_type = body.get("contentType", "")
        body_snippet = body.get("bodySnippet", "")
        endpoint = body.get("endpoint", "")
        client_ip = request.client.host if request.client else "unknown"

        if err_type == "api-error":
            parts = [f"[api-error] {method} {url} → {status}"]
            if content_type:
                parts.append(f"resp-ct={content_type}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
            if req_body:
                _log_logger.error(f"  req-body: {req_body}")
            if body_snippet:
                _log_logger.error(f"  resp-body: {body_snippet[:500]}")
        elif err_type == "fetch-error":
            parts = [f"[fetch-error] {method} {endpoint}"]
            if message:
                parts.append(f"err={message[:200]}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
        else:
            parts = [f"[{err_type}] {message}"]
            if url:
                parts.append(f"url={url}")
            if filename:
                parts.append(f"file={filename}:{lineno}:{colno}")
            if client_ip:
                parts.append(f"client={client_ip}")
            _log_logger.error(" | ".join(parts))
            if stack:
                _log_logger.error(f"Stack: {stack[:2000]}")
        return {"ok": True}

    app.include_router(log_router)
