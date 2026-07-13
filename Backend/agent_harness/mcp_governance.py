"""Governed Model Context Protocol integration for the control-plane runtime."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from contextlib import AsyncExitStack
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from .authorization import AuthorizationRequest, AuthorizationService
from .redaction import safe_summary


SUPPORTED_TRANSPORTS = {"stdio", "streamable_http"}
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
_MCP_RUNTIME_CONTEXT: ContextVar[bool] = ContextVar("agent_harness_mcp_runtime", default=False)


class MCPGovernanceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class MCPInvocationRequest:
    agent_id: str
    server_id: str
    tool_name: str
    arguments: dict[str, Any]
    parent_agent_invocation_id: str | None = None
    trace_id: str | None = None
    human_override: dict[str, Any] | None = None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_hash(input_schema: dict[str, Any], output_schema: dict[str, Any] | None = None) -> str:
    return canonical_hash({"input_schema": input_schema or {}, "output_schema": output_schema or {}})


def _validate_schema(schema: dict[str, Any], label: str) -> None:
    if not isinstance(schema, dict):
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", f"{label} must be a JSON schema object")
    if schema.get("type", "object") != "object":
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", f"{label} must use object input")
    properties = schema.get("properties", {})
    if properties is not None and not isinstance(properties, dict):
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", f"{label}.properties must be an object")
    required = schema.get("required", [])
    if required is not None and not isinstance(required, list):
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", f"{label}.required must be an array")


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", "MCP arguments must be a JSON object")
    if len(json.dumps(arguments, default=str).encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise MCPGovernanceError("MCP_PAYLOAD_TOO_LARGE", "MCP argument payload exceeds maximum size")
    required = schema.get("required") or []
    missing = [key for key in required if key not in arguments]
    if missing:
        raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", "Missing MCP argument(s): " + ", ".join(missing))
    properties = schema.get("properties") or {}
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key, value in arguments.items():
        expected = properties.get(key, {}).get("type")
        if expected in type_map and value is not None and not isinstance(value, type_map[expected]):
            raise MCPGovernanceError("MCP_SCHEMA_MISMATCH", f"MCP argument '{key}' must be {expected}")


def _risk_for_tool(name: str, server_risk: str) -> str:
    lowered = name.lower()
    if any(word in lowered for word in ("customer", "payment", "repayment", "summary")):
        return "high"
    if server_risk in {"high", "critical"}:
        return server_risk
    return "low"


def _approval_for_tool(name: str, risk_level: str) -> bool:
    lowered = name.lower()
    return risk_level in {"critical"} or any(word in lowered for word in ("customer", "mock_customer"))


def _redact_result(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            key_lower = str(key).lower()
            if any(fragment in key_lower for fragment in ("phone", "email", "address", "customer_id")):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_result(child)
        return result
    if isinstance(value, list):
        return [_redact_result(item) for item in value]
    return value


class MCPTransportClient:
    """Thin wrapper around the official Python MCP SDK transports."""

    async def list_tools(self, server: dict[str, Any]) -> list[Any]:
        async with self._session(server) as session:
            response = await asyncio.wait_for(session.list_tools(), timeout=int(server.get("connect_timeout_seconds") or 10))
            return list(response.tools or [])

    async def call_tool(self, server: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> Any:
        async with self._session(server) as session:
            return await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=int(server.get("call_timeout_seconds") or 30))

    def _session(self, server: dict[str, Any]):
        return _MCPSessionContext(server)


class _MCPSessionContext:
    def __init__(self, server: dict[str, Any]):
        self.server = server
        self.stack = AsyncExitStack()
        self.session = None

    async def __aenter__(self):
        try:
            from mcp import ClientSession, StdioServerParameters
        except Exception as exc:  # pragma: no cover - exercised when dependency is absent
            raise MCPGovernanceError("MCP_SDK_UNAVAILABLE", "The official Python MCP SDK is not installed") from exc

        transport = self.server["transport"]
        if transport == "stdio":
            from mcp.client.stdio import stdio_client

            command_ref = self.server.get("command_reference") or {}
            if not isinstance(command_ref, dict):
                raise MCPGovernanceError("MCP_DISCOVERY_FAILURE", "stdio MCP server command_reference is invalid")
            command = command_ref.get("command")
            if command == "{python}":
                command = sys.executable
            args = [str(item).replace("{backend_root}", str(Path(__file__).resolve().parents[1])) for item in command_ref.get("args", [])]
            cwd = command_ref.get("cwd")
            if cwd:
                cwd = str(cwd).replace("{backend_root}", str(Path(__file__).resolve().parents[1]))
            params = StdioServerParameters(command=command, args=args, cwd=cwd, env=_resolve_env(self.server))
            read, write = await self.stack.enter_async_context(stdio_client(params))
        elif transport == "streamable_http":
            from mcp.client.streamable_http import streamablehttp_client

            endpoint = self.server.get("endpoint")
            if not endpoint:
                raise MCPGovernanceError("MCP_DISCOVERY_FAILURE", "streamable_http endpoint is required")
            read, write, _ = await self.stack.enter_async_context(streamablehttp_client(endpoint, headers=_auth_headers(self.server)))
        else:
            raise MCPGovernanceError("MCP_UNSUPPORTED_TRANSPORT", f"Unsupported MCP transport: {transport}")
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        await self.stack.aclose()


def _resolve_env(server: dict[str, Any]) -> dict[str, str] | None:
    env_ref = server.get("environment_reference")
    if not env_ref:
        return None
    allowed_prefix = str(env_ref).replace("env:", "")
    return {key: value for key, value in os.environ.items() if key.startswith(allowed_prefix)}


def _auth_headers(server: dict[str, Any]) -> dict[str, str] | None:
    if server.get("auth_type") in {None, "none"}:
        return None
    credential_reference = server.get("credential_reference")
    if not credential_reference or not str(credential_reference).startswith("env:"):
        raise MCPGovernanceError("MCP_AUTH_FAILURE", "MCP credential_reference must point to an environment variable")
    value = os.getenv(str(credential_reference).split(":", 1)[1])
    if not value:
        raise MCPGovernanceError("MCP_AUTH_FAILURE", "MCP credential is not configured")
    return {"Authorization": f"Bearer {value}"}


class GovernedMCPService:
    def __init__(self, store, registry, authorization: AuthorizationService, transport_client: MCPTransportClient | None = None):
        self.store = store
        self.registry = registry
        self.authorization = authorization
        self.transport_client = transport_client or MCPTransportClient()

    def load_config(self, config_dir: str | Path):
        import yaml

        path = Path(config_dir) / "mcp_servers.yaml"
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        servers = raw.get("mcp_servers", raw)
        result = []
        for server_id, item in (servers or {}).items():
            payload = {"server_id": server_id, **(item or {})}
            self.register_server(payload)
            result.append(payload)
        return result

    def register_server(self, server: dict[str, Any]) -> dict[str, Any]:
        if server.get("transport") not in SUPPORTED_TRANSPORTS:
            raise MCPGovernanceError("MCP_UNSUPPORTED_TRANSPORT", "Only stdio and streamable_http MCP transports are supported")
        if not server.get("server_id") or not server.get("name"):
            raise MCPGovernanceError("MCP_DISCOVERY_FAILURE", "server_id and name are required")
        if server.get("credential_reference") and not str(server["credential_reference"]).startswith(("env:", "secret:", "credential:")):
            raise MCPGovernanceError("MCP_AUTH_FAILURE", "MCP credentials must be referenced, not stored in plaintext")
        self.store.upsert_mcp_server({**server, "status": server.get("status", "registered")})
        return self.store.get_mcp_server(server["server_id"])

    async def refresh_server(self, server_id: str) -> dict[str, Any]:
        server = self._approved_server(server_id, allow_registered=True)
        try:
            tools = await self.transport_client.list_tools(server)
            discovered = []
            for tool in tools:
                name = getattr(tool, "name", None) or tool.get("name")
                input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or tool.get("inputSchema", {})
                output_schema = getattr(tool, "outputSchema", None) or getattr(tool, "output_schema", None) or (tool.get("outputSchema") if isinstance(tool, dict) else None)
                description = getattr(tool, "description", None) or (tool.get("description") if isinstance(tool, dict) else "")
                _validate_schema(input_schema or {}, f"{server_id}.{name}.input_schema")
                if output_schema:
                    _validate_schema(output_schema, f"{server_id}.{name}.output_schema")
                risk = _risk_for_tool(str(name), server.get("risk_tier", "medium"))
                persisted = {
                    "server_id": server_id,
                    "tool_name": str(name),
                    "description": description or "",
                    "input_schema": input_schema or {"type": "object", "properties": {}},
                    "output_schema": output_schema,
                    "risk_level": risk,
                    "requires_approval": _approval_for_tool(str(name), risk),
                    "schema_hash": _schema_hash(input_schema or {}, output_schema),
                    "enabled": True,
                }
                change = self.store.upsert_mcp_tool(persisted)
                discovered.append({**persisted, **change})
            status = "review" if any(item.get("review_required") for item in discovered) else "active"
            self.store.execute("UPDATE mcp_servers SET status=?,updated_at=CURRENT_TIMESTAMP WHERE server_id=?", (status, server_id))
            self.store.add_event("MCP_DISCOVERY_REFRESHED", str(uuid.uuid4()), "control_plane", {"server_id": server_id, "tool_count": len(discovered), "status": status})
            return {"server": self.store.get_mcp_server(server_id), "tools": self.store.list_mcp_tools(server_id)}
        except MCPGovernanceError:
            self.store.execute("UPDATE mcp_servers SET status='unavailable',updated_at=CURRENT_TIMESTAMP WHERE server_id=?", (server_id,))
            raise
        except TimeoutError as exc:
            self.store.execute("UPDATE mcp_servers SET status='unavailable',updated_at=CURRENT_TIMESTAMP WHERE server_id=?", (server_id,))
            raise MCPGovernanceError("MCP_TIMEOUT", "MCP discovery timed out") from exc
        except Exception as exc:
            self.store.execute("UPDATE mcp_servers SET status='unavailable',updated_at=CURRENT_TIMESTAMP WHERE server_id=?", (server_id,))
            raise MCPGovernanceError("MCP_DISCOVERY_FAILURE", str(exc)) from exc

    async def invoke_tool(self, request: MCPInvocationRequest) -> dict[str, Any]:
        token = _MCP_RUNTIME_CONTEXT.set(True)
        try:
            return await self._invoke_tool_guarded(request)
        finally:
            _MCP_RUNTIME_CONTEXT.reset(token)

    async def _invoke_tool_guarded(self, request: MCPInvocationRequest) -> dict[str, Any]:
        started = perf_counter()
        timestamp = now_utc()
        invocation_id = str(uuid.uuid4())
        server = self._approved_server(request.server_id)
        tool = self.store.get_mcp_tool(request.server_id, request.tool_name)
        if not tool or not tool.get("enabled"):
            raise MCPGovernanceError("MCP_TOOLSET_CHANGED", "MCP tool is not discovered or enabled")
        if tool.get("review_required"):
            raise MCPGovernanceError("MCP_TOOLSET_CHANGED", "MCP schema changed and requires review")
        contract = self.registry.get_contract(request.agent_id)
        self._contract_allows(contract, request.server_id, request.tool_name)
        _validate_arguments(tool["input_schema"], request.arguments)
        principal_id = self.authorization.principal_id_for_agent(request.agent_id)
        decision = self.authorization.evaluate(AuthorizationRequest(
            agent_id=request.agent_id,
            principal_id=principal_id,
            invocation_id=invocation_id,
            trace_id=request.trace_id,
            action=request.tool_name,
            resource_type="mcp",
            resource_id=request.server_id,
            context={
                "lifecycle_status": contract.status.value,
                "human_override": request.human_override or {},
                "required_human_approval_for": [request.tool_name] if tool.get("requires_approval") else [],
            },
        ))
        args_hash = canonical_hash(request.arguments)
        self.store.start_mcp_invocation(invocation_id, request.parent_agent_invocation_id, principal_id, request.server_id, request.tool_name, args_hash, decision.decision, timestamp)
        if decision.decision != "ALLOW":
            self.store.finish_mcp_invocation(invocation_id, now_utc(), int((perf_counter() - started) * 1000), "blocked", decision.reason_code)
            raise MCPGovernanceError("MCP_PERMISSION_DENIED", decision.reason_code)
        if not _MCP_RUNTIME_CONTEXT.get():
            raise MCPGovernanceError("MCP_DIRECT_BYPASS_PREVENTED", "MCP calls must go through the control-plane runtime")
        try:
            raw_result = await self.transport_client.call_tool(server, request.tool_name, request.arguments)
            normalized = self._normalize_result(raw_result)
            redacted = _redact_result(normalized)
            result_bytes = len(json.dumps(redacted, default=str).encode("utf-8"))
            truncated = result_bytes > MAX_RESULT_BYTES
            if truncated:
                redacted = {"content": str(redacted)[:MAX_RESULT_BYTES], "truncated": True}
            duration_ms = int((perf_counter() - started) * 1000)
            self.store.finish_mcp_invocation(invocation_id, now_utc(), duration_ms, "success")
            self.store.add_event("MCP_TOOL_INVOKED", request.trace_id or invocation_id, request.agent_id, {
                "mcp_invocation_id": invocation_id,
                "server_id": request.server_id,
                "tool_name": request.tool_name,
                "decision": decision.decision,
                "arguments_hash": args_hash,
                "duration_ms": duration_ms,
                "truncated": truncated,
            })
            return {
                "invocation_id": invocation_id,
                "server_id": request.server_id,
                "tool_name": request.tool_name,
                "status": "success",
                "decision": decision.decision,
                "result": redacted,
                "arguments_hash": args_hash,
                "duration_ms": duration_ms,
            }
        except asyncio.TimeoutError as exc:
            self._finish_error(invocation_id, started, "MCP_TIMEOUT")
            raise MCPGovernanceError("MCP_TIMEOUT", "MCP call timed out") from exc
        except MCPGovernanceError as exc:
            self._finish_error(invocation_id, started, exc.code)
            raise
        except Exception as exc:
            self._finish_error(invocation_id, started, "MCP_MALFORMED_RESULT")
            raise MCPGovernanceError("MCP_MALFORMED_RESULT", str(exc)) from exc

    def direct_sdk_call_forbidden(self):
        raise MCPGovernanceError("MCP_DIRECT_BYPASS_PREVENTED", "Direct MCP calls are disabled outside the control-plane runtime")

    def _finish_error(self, invocation_id: str, started: float, code: str):
        self.store.finish_mcp_invocation(invocation_id, now_utc(), int((perf_counter() - started) * 1000), "failed", code)

    def _approved_server(self, server_id: str, allow_registered: bool = False) -> dict[str, Any]:
        server = self.store.get_mcp_server(server_id)
        if not server:
            raise MCPGovernanceError("MCP_SERVER_UNAVAILABLE", "MCP server is not registered")
        allowed_status = {"active", "registered"} if allow_registered else {"active"}
        if server.get("status") not in allowed_status:
            raise MCPGovernanceError("MCP_SERVER_UNAVAILABLE", f"MCP server is {server.get('status')}")
        if server.get("transport") not in SUPPORTED_TRANSPORTS:
            raise MCPGovernanceError("MCP_UNSUPPORTED_TRANSPORT", f"Unsupported MCP transport: {server.get('transport')}")
        return server

    def _contract_allows(self, contract, server_id: str, tool_name: str) -> None:
        permissions = contract.policy_permissions or {}
        servers = set(permissions.get("mcp_servers") or [])
        tools = set(permissions.get("mcp_tools") or [])
        if server_id not in servers and "*" not in servers:
            raise MCPGovernanceError("MCP_PERMISSION_DENIED", "Agent contract does not declare this MCP server")
        allowed = {f"{server_id}.{tool_name}", f"{server_id}.*", "*"}
        if not tools.intersection(allowed):
            raise MCPGovernanceError("MCP_PERMISSION_DENIED", "Agent contract does not declare this MCP tool")

    def _normalize_result(self, raw_result: Any) -> dict[str, Any]:
        if getattr(raw_result, "isError", False):
            raise MCPGovernanceError("MCP_MALFORMED_RESULT", "MCP server returned an error result")
        content = getattr(raw_result, "content", None)
        if content is None and isinstance(raw_result, dict):
            content = raw_result.get("content")
        if content is None:
            raise MCPGovernanceError("MCP_MALFORMED_RESULT", "MCP result content is missing")
        normalized = []
        for item in content or []:
            item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
            if item_type == "text":
                text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else "")
                try:
                    normalized.append({"type": "json", "json": json.loads(text)})
                except (TypeError, json.JSONDecodeError):
                    normalized.append({"type": "text", "text": text})
            elif item_type == "resource":
                normalized.append({"type": "resource", "resource": safe_summary(item)})
            else:
                normalized.append(safe_summary(item))
        if not isinstance(normalized, list):
            raise MCPGovernanceError("MCP_MALFORMED_RESULT", "MCP result content is malformed")
        return {"content": normalized}
