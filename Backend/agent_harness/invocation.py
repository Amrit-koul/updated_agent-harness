"""Typed invocation models for the canonical control-plane runtime."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RuntimeErrorCode(str, Enum):
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    INPUT_SCHEMA_INVALID = "INPUT_SCHEMA_INVALID"
    AGENT_NOT_ACTIVE = "AGENT_NOT_ACTIVE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    GUARDRAIL_BLOCKED = "GUARDRAIL_BLOCKED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    ADAPTER_FAILURE = "ADAPTER_FAILURE"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    INTERNAL_RUNTIME_ERROR = "INTERNAL_RUNTIME_ERROR"


class InvocationRequest(BaseModel):
    agent_id: str
    action: str = "invoke"
    payload: dict[str, Any] = Field(default_factory=dict)
    invoking_user_id: Optional[str] = None
    invoking_agent_id: Optional[str] = None
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None
    requested_tools: Optional[list[str]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvocationContext(BaseModel):
    invocation_id: str
    trace_id: str
    contract_version: str
    agent_principal_id: str
    resolved_permissions: dict[str, Any] = Field(default_factory=dict)
    lifecycle_status: str
    runtime_type: str
    adapter_type: str
    model_policy: dict[str, Any] = Field(default_factory=dict)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    start_timestamp: str


class InvocationResult(BaseModel):
    status: str
    output: Any = None
    policy_decisions: list[dict[str, Any]] = Field(default_factory=list)
    guardrail_results: list[dict[str, Any]] = Field(default_factory=list)
    evaluator_results: list[dict[str, Any]] = Field(default_factory=list)
    usage: list[dict[str, Any]] = Field(default_factory=list)
    audit_reference: Optional[str] = None
    trace_id: str
    duration_ms: int = 0
    error: Optional[dict[str, Any]] = None
    invocation_id: Optional[str] = None
    agent_id: Optional[str] = None
    context: Optional[InvocationContext] = None

    def to_legacy_response(self) -> dict[str, Any]:
        if self.status == "completed":
            return {"trace_id": self.trace_id, "agent_id": self.agent_id, "result": self.output}
        reason = (self.error or {}).get("message") or (self.error or {}).get("code") or "Invocation failed"
        decision = "BLOCK" if self.status == "blocked" else "ERROR"
        return {
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "decision": decision,
            "reason": reason,
            "status": self.status,
            "error": self.error,
            "adapter_invoked": False,
        }


class RuntimeInvocationError(Exception):
    def __init__(self, code: RuntimeErrorCode, message: str, *, original: Exception | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.original = original
