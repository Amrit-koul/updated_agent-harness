"""Runtime RBAC authority for agent security principals."""
from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


POLICY_VERSION = "agent-rbac-v1"
_CURRENT_AUTH_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("agent_harness_auth_context", default=None)


class PermissionDenied(PermissionError):
    def __init__(self, decision: "AuthorizationDecision"):
        super().__init__(decision.reason_code)
        self.decision = decision


@dataclass
class AuthorizationRequest:
    agent_id: str
    action: str
    resource_type: str
    resource_id: str = ""
    invocation_id: str | None = None
    trace_id: str | None = None
    principal_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationDecision:
    decision_id: str
    invocation_id: str
    principal_id: str
    resource_type: str
    resource_id: str
    requested_action: str
    resolved_roles: list[dict[str, Any]]
    resolved_permissions: list[dict[str, Any]]
    decision: str
    reason_code: str
    policy_version: str
    timestamp: str

    def to_dict(self):
        return asdict(self)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def permission_id(resource_type: str, resource_id: str | None, action: str) -> str:
    resource = resource_type if not resource_id else f"{resource_type}:{resource_id}"
    return f"{resource}:{action}"


class AuthorizationService:
    """Authoritative RBAC evaluator.

    Contracts can request permissions. This service checks those requests against
    persisted principals, roles, role bindings and resource scopes.
    """

    def __init__(self, store, registry=None):
        self.store = store
        self.registry = registry
        self._cache: dict[str, tuple[float, list[dict[str, Any]], list[dict[str, Any]]]] = {}
        self.cache_ttl_seconds = 5.0

    def invalidate(self, principal_id: str | None = None):
        if principal_id:
            self._cache.pop(principal_id, None)
        else:
            self._cache.clear()

    def principal_id_for_agent(self, agent_id: str) -> str:
        rows = self.store.query("SELECT principal_id FROM agent_principals WHERE agent_id=?", (agent_id,))
        if rows:
            return rows[0]["principal_id"]
        return f"principal-{uuid.uuid5(uuid.NAMESPACE_URL, 'agent-principal:' + agent_id)}"

    def ensure_principal_for_contract(self, contract, granted_by: str = "rbac_bootstrap"):
        principal_id = self.principal_id_for_agent(contract.agent_id)
        self.store.execute(
            """
            INSERT INTO agent_principals(principal_id,agent_id,principal_type,display_name,status,credential_reference)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(principal_id) DO UPDATE SET
              agent_id=excluded.agent_id,
              display_name=excluded.display_name,
              updated_at=CURRENT_TIMESTAMP
            """,
            (principal_id, contract.agent_id, "agent", contract.name, "active", None),
        )

        requested = requested_permissions_for_contract(contract)
        role_id = f"role-{contract.agent_id}-runtime"
        existing_role = self.store.query("SELECT role_id FROM roles WHERE role_id=?", (role_id,))
        if requested and not existing_role:
            self.store.execute(
                "INSERT OR IGNORE INTO roles(role_id,role_name,description,system_role) VALUES(?,?,?,?)",
                (role_id, f"{contract.agent_id}.runtime", f"Runtime permissions for {contract.agent_id}", 1),
            )
        if requested:
            requested_ids = {item["permission_id"] for item in requested}
            for item in requested:
                self.store.execute(
                    "INSERT OR IGNORE INTO permissions(permission_id,resource_type,action,description) VALUES(?,?,?,?)",
                    (item["permission_id"], item["resource_type"], item["action"], item.get("description", "")),
                )
                self.store.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_id,permission_id) VALUES(?,?)",
                    (role_id, item["permission_id"]),
                )
            if requested_ids:
                placeholders = ",".join("?" for _ in requested_ids)
                self.store.execute(
                    f"DELETE FROM role_permissions WHERE role_id=? AND permission_id NOT IN ({placeholders})",
                    (role_id, *sorted(requested_ids)),
                )
            self.store.execute(
                """
                INSERT OR IGNORE INTO principal_roles(principal_id,role_id,scope_type,scope_value,valid_from,granted_by)
                VALUES(?,?,?,?,?,?)
                """,
                (principal_id, role_id, "global", "*", now_utc(), granted_by),
            )
        self.invalidate(principal_id)
        return principal_id

    def validate_contract_permissions(self, contract) -> list[str]:
        principal_id = self.principal_id_for_agent(contract.agent_id)
        errors = []
        for item in requested_permissions_for_contract(contract):
            if str(item.get("action", "")).startswith("deny:"):
                continue
            decision = self.evaluate(AuthorizationRequest(
                agent_id=contract.agent_id,
                principal_id=principal_id,
                invocation_id="contract-registration",
                action=item["action"],
                resource_type=item["request_resource_type"],
                resource_id=item["request_resource_id"],
                context={"lifecycle_status": contract.status.value, "skip_audit": True, "approval_state": "not_required"},
            ))
            if decision.decision != "ALLOW":
                errors.append(f"Requested permission not granted to principal {principal_id}: {item['permission_id']} ({decision.reason_code})")
        return errors

    def effective_permissions(self, principal_id: str) -> dict[str, Any]:
        principal = self._principal(principal_id)
        roles, permissions = self._effective(principal_id)
        return {"principal": principal, "roles": roles, "permissions": permissions}

    def evaluate(self, request: AuthorizationRequest) -> AuthorizationDecision:
        invocation_id = request.invocation_id or request.trace_id or str(uuid.uuid4())
        principal_id = request.principal_id or self.principal_id_for_agent(request.agent_id)
        timestamp = now_utc()
        principal = self._principal(principal_id)
        roles, permissions = self._effective(principal_id) if principal else ([], [])
        reason = "default_deny"
        decision = "DENY"
        context = request.context or {}

        if not principal:
            reason = "principal_not_found"
        elif principal.get("status") != "active":
            reason = "principal_inactive"
        elif context.get("lifecycle_status") in {"disabled", "quarantined"}:
            reason = "agent_lifecycle_not_executable"
        elif self._explicit_deny(permissions, request):
            reason = "explicit_deny"
        elif self._requires_approval(request) and not self._approval_satisfied(context):
            reason = "human_approval_required"
        elif self._allowed(roles, permissions, request):
            decision = "ALLOW"
            reason = "allowed"
        elif not roles:
            reason = "missing_valid_role"
        else:
            reason = "permission_not_granted"

        result = AuthorizationDecision(
            decision_id=str(uuid.uuid4()),
            invocation_id=invocation_id,
            principal_id=principal_id,
            resource_type=request.resource_type,
            resource_id=request.resource_id or "",
            requested_action=request.action,
            resolved_roles=roles,
            resolved_permissions=permissions,
            decision=decision,
            reason_code=reason,
            policy_version=POLICY_VERSION,
            timestamp=timestamp,
        )
        if not context.get("skip_audit"):
            self.audit(request.agent_id, request.trace_id, result)
        return result

    def enforce(self, request: AuthorizationRequest) -> AuthorizationDecision:
        decision = self.evaluate(request)
        if decision.decision != "ALLOW":
            raise PermissionDenied(decision)
        return decision

    def audit(self, agent_id: str, trace_id: str | None, decision: AuthorizationDecision):
        self.store.execute(
            """
            INSERT INTO authorization_decisions(decision_id,invocation_id,principal_id,resource_type,resource_id,requested_action,resolved_roles,resolved_permissions,decision,reason_code,policy_version,timestamp)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision.decision_id, decision.invocation_id, decision.principal_id,
                decision.resource_type, decision.resource_id, decision.requested_action,
                json.dumps(decision.resolved_roles, default=str),
                json.dumps(decision.resolved_permissions, default=str),
                decision.decision, decision.reason_code, decision.policy_version, decision.timestamp,
            ),
        )
        self.store.add_event(
            "AUTHORIZATION_DECISION",
            trace_id or decision.invocation_id,
            agent_id,
            {
                "decision_id": decision.decision_id,
                "principal_id": decision.principal_id,
                "resource_type": decision.resource_type,
                "resource_id": decision.resource_id,
                "action": decision.requested_action,
                "decision": decision.decision,
                "reason_code": decision.reason_code,
            },
        )

    def _principal(self, principal_id: str) -> dict[str, Any] | None:
        rows = self.store.query("SELECT * FROM agent_principals WHERE principal_id=?", (principal_id,))
        return rows[0] if rows else None

    def _effective(self, principal_id: str):
        import time

        cached = self._cache.get(principal_id)
        now = time.time()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1], cached[2]
        roles = self.store.query(
            """
            SELECT r.role_id,r.role_name,r.description,r.system_role,pr.scope_type,pr.scope_value,pr.valid_from,pr.valid_until
            FROM principal_roles pr
            JOIN roles r ON r.role_id=pr.role_id
            WHERE pr.principal_id=?
              AND (pr.valid_from IS NULL OR pr.valid_from <= CURRENT_TIMESTAMP OR pr.valid_from <= ?)
              AND (pr.valid_until IS NULL OR pr.valid_until > CURRENT_TIMESTAMP OR pr.valid_until > ?)
            """,
            (principal_id, now_utc(), now_utc()),
        )
        permissions = self.store.query(
            """
            SELECT p.permission_id,p.resource_type,p.action,p.description,rp.role_id,r.role_name,pr.scope_type,pr.scope_value
            FROM principal_roles pr
            JOIN roles r ON r.role_id=pr.role_id
            JOIN role_permissions rp ON rp.role_id=r.role_id
            JOIN permissions p ON p.permission_id=rp.permission_id
            WHERE pr.principal_id=?
              AND (pr.valid_from IS NULL OR pr.valid_from <= CURRENT_TIMESTAMP OR pr.valid_from <= ?)
              AND (pr.valid_until IS NULL OR pr.valid_until > CURRENT_TIMESTAMP OR pr.valid_until > ?)
            """,
            (principal_id, now_utc(), now_utc()),
        )
        self._cache[principal_id] = (now, roles, permissions)
        return roles, permissions

    def _explicit_deny(self, permissions: list[dict[str, Any]], request: AuthorizationRequest) -> bool:
        return any(
            self._permission_matches(item, request, allow_deny=True)
            and (str(item.get("action", "")).startswith("deny:") or str(item.get("permission_id", "")).startswith("deny:"))
            for item in permissions
        )

    def _allowed(self, roles: list[dict[str, Any]], permissions: list[dict[str, Any]], request: AuthorizationRequest) -> bool:
        return bool(roles) and any(self._permission_matches(item, request) for item in permissions)

    def _permission_matches(self, item: dict[str, Any], request: AuthorizationRequest, allow_deny: bool = False) -> bool:
        action = str(item.get("action") or "")
        if action.startswith("deny:"):
            action = action.split(":", 1)[1]
        if action not in {"*", request.action}:
            return False
        resource_type = str(item.get("resource_type") or "")
        candidates = {"*", request.resource_type}
        if request.resource_id:
            candidates.add(f"{request.resource_type}:{request.resource_id}")
        if resource_type not in candidates:
            return False
        return self._scope_matches(item, request)

    def _scope_matches(self, item: dict[str, Any], request: AuthorizationRequest) -> bool:
        scope_type = item.get("scope_type") or "global"
        scope_value = item.get("scope_value") or "*"
        if scope_type == "global" or scope_value == "*":
            return True
        if scope_type == request.resource_type and scope_value == request.resource_id:
            return True
        if scope_type == "data" and scope_value in {request.resource_id, request.context.get("data_scope")}:
            return True
        if scope_type == "agent" and scope_value == request.agent_id:
            return True
        return False

    def _requires_approval(self, request: AuthorizationRequest) -> bool:
        approval = request.context.get("required_human_approval_for") or []
        return request.action in approval or permission_id(request.resource_type, request.resource_id, request.action) in approval

    def _approval_satisfied(self, context: dict[str, Any]) -> bool:
        override = context.get("human_override") or {}
        return bool(context.get("approval_state") == "not_required" or (override.get("approved") and override.get("approved_by") and override.get("reason")))


def set_current_authorization_context(value: dict[str, Any]):
    return _CURRENT_AUTH_CONTEXT.set(value)


def reset_current_authorization_context(token):
    _CURRENT_AUTH_CONTEXT.reset(token)


def authorize_current_resource(resource_type: str, resource_id: str, action: str, extra_context: dict[str, Any] | None = None):
    current = _CURRENT_AUTH_CONTEXT.get()
    if not current:
        raise PermissionError("direct_resource_bypass_prevented")
    service: AuthorizationService = current["authorization"]
    context = {**current.get("context", {}), **(extra_context or {})}
    return service.enforce(AuthorizationRequest(
        agent_id=current["agent_id"],
        principal_id=current["principal_id"],
        invocation_id=current["invocation_id"],
        trace_id=current.get("trace_id"),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        context=context,
    ))


def requested_permissions_for_contract(contract) -> list[dict[str, str]]:
    permissions = contract.policy_permissions or {}
    requested: dict[str, dict[str, str]] = {}

    def add(resource_type: str, resource_id: str, action: str, description: str = ""):
        pid = permission_id(resource_type, resource_id, action)
        requested[pid] = {
            "permission_id": pid,
            "resource_type": resource_type if not resource_id else f"{resource_type}:{resource_id}",
            "request_resource_type": resource_type,
            "request_resource_id": resource_id,
            "action": action,
            "description": description,
        }

    for action in permissions.get("allowed_actions") or ["invoke"]:
        add("agent", contract.agent_id, action, f"Invoke/action permission for {contract.agent_id}")
    for tool_id in contract.tools or permissions.get("allowed_tools") or []:
        if tool_id != "invoke":
            add("tool", tool_id, "invoke", f"Invoke tool {tool_id}")
    for scope in permissions.get("allowed_data_scopes") or []:
        add("data", scope, "read", f"Read data scope {scope}")
    for mcp_tool in permissions.get("mcp_tools") or []:
        parts = str(mcp_tool).split(".", 1)
        server = parts[0]
        tool = parts[1] if len(parts) > 1 else "*"
        add("mcp", server, tool, f"Call MCP tool {mcp_tool}")
    deployment = (contract.model_preferences or {}).get("deployment") or (contract.model_preferences or {}).get("primary") or (contract.model_preferences or {}).get("llm_model")
    if deployment:
        add("model", deployment, "invoke", f"Invoke model deployment {deployment}")
    for denied in permissions.get("denied_actions") or []:
        add("agent", contract.agent_id, f"deny:{denied}", f"Explicit deny for {denied}")
    return list(requested.values())
