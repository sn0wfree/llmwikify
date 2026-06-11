"""Pydantic request models for agent chat endpoints.

Replaces raw ``body.get()`` calls with typed, validated models.
Pydantic is available as a transitive dependency of FastAPI.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/agent/chat"""
    message: str = Field(default="", min_length=0, max_length=100_000)
    session_id: str | None = None
    wiki_id: str | None = None
    # v0.40: file attachments (base64-encoded)
    attachments: list[dict] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    """POST /api/agent/sessions"""
    wiki_id: str | None = None


class ApprovalRequest(BaseModel):
    """POST /api/agent/confirmations/{id}/approve-and-continue"""
    session_id: str = ""
    wiki_id: str | None = None
    arguments: dict | None = None


class BatchApproveRequest(BaseModel):
    """POST /api/agent/confirmations/batch"""
    ids: list[str] = Field(default_factory=list)


class BatchApproveProposalsRequest(BaseModel):
    """POST /api/agent/dream/proposals/batch-approve"""
    ids: list[str] = Field(default_factory=list)


class ApplyProposalsRequest(BaseModel):
    """POST /api/agent/dream/proposals/apply"""
    wiki_id: str | None = None
    ids: list[str] | None = None


class SaveConfigRequest(BaseModel):
    """PUT /api/agent/config"""
    api_key: str = ""
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
