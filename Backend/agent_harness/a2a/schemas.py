"""Minimal A2A-compatible protocol models used by the bank-grade gateway."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class A2APart(BaseModel):
    type: Literal["text", "data", "file"] = "text"
    text: str | None = None
    data: dict[str, Any] | None = None
    file: dict[str, Any] | None = None


class A2AMessage(BaseModel):
    role: Literal["user", "agent"] = "user"
    parts: list[A2APart] = Field(default_factory=list)
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    context_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ASendMessageRequest(BaseModel):
    agent_id: str
    message: A2AMessage
    context_id: str | None = None
    invoking_agent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskStatus(BaseModel):
    state: Literal["submitted", "working", "input-required", "completed", "canceled", "failed", "rejected"]
    timestamp: str = Field(default_factory=now_utc)
    message: A2AMessage | None = None


class A2ATask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    context_id: str | None = None
    agent_id: str
    status: TaskStatus
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AJsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
