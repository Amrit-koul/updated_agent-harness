"""Business-friendly Agent Control Plane API. Existing APIs remain untouched."""
from datetime import datetime, timezone
import uuid
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from agent_harness.exceptions import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterError,
    AdapterResponseError,
    AdapterTimeoutError,
    AgentNotFoundError,
)
from agent_harness.invocation import InvocationRequest
from agent_harness.mcp_governance import MCPGovernanceError, MCPInvocationRequest
from agent_harness.authorization import AuthorizationRequest
from agent_harness.redaction import contract_summary, safe_summary
from agent_harness.tracing import get_tracer

from .harness.runtime import control_plane
from .prompts import prompt_registry
from agent_harness.prompt_registry import PromptRegistryError
from banking_agents.policy.tool_authorization import ToolInvocationRequest


router = APIRouter(prefix="/api/v1/control", tags=["Agent Control Plane"])


def _limit(value, maximum=500): return max(1, min(value, maximum))


def require_admin(x_control_plane_admin_secret: str | None = Header(default=None)):
    """Control-plane admin guard.

    Set CONTROL_PLANE_ADMIN_SECRET on the backend and send the same value in
    X-Control-Plane-Admin-Secret. Production hardening should replace this with
    enterprise identity, SSO, service auth and audit-grade administrator claims.
    """
    expected = os.getenv("CONTROL_PLANE_ADMIN_SECRET")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Admin API disabled: CONTROL_PLANE_ADMIN_SECRET is not configured")
    if not x_control_plane_admin_secret or x_control_plane_admin_secret != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin authorization failed")
    return {"admin": "control-plane-admin"}


def _trace_metadata(agent_id, trace_id, request_source):
    contract = control_plane.registry.get_contract(agent_id)
    return {
        **contract_summary(contract), "trace_id": trace_id, "status_before": contract.status.value,
        "status_after": contract.status.value, "request_source": request_source,
        "environment": os.getenv("APP_ENV", "local"), "client": "Bandhan Bank",
    }


def _agent_with_primitives(agent_id: str):
    contract_obj = control_plane.registry.get_contract(agent_id)
    contract = contract_obj.to_dict()
    registry_view = control_plane.registry.registry_contract_view(agent_id)
    contract.update({
        "effective_resolved_contract": registry_view["effective_resolved_contract"],
        "original_contract_version": registry_view["original_contract_version"],
        "validation_result": registry_view["validation_result"],
        "unresolved_references": registry_view["unresolved_references"],
        "active_runtime": registry_view["active_runtime"],
        "model_deployment": registry_view["model_deployment"],
        "budget_policy": registry_view["budget_policy"],
        "permissions": registry_view["permissions"],
        "observability_requirements": registry_view["observability_requirements"],
        "latest_evidence": registry_view["latest_evidence"],
    })
    contract["primitives"] = control_plane.primitives.agent_primitives(agent_id)
    contract["metrics"] = control_plane.registry.metrics(agent_id)
    latest = control_plane.store.query("SELECT * FROM kill_switch_events WHERE agent_id=? ORDER BY id DESC LIMIT 1", (agent_id,))
    contract["latest_kill_switch_event"] = latest[0] if latest else None
    for key, sql in {
        "latest_rag_evaluation": "SELECT * FROM rag_evaluations WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
        "latest_guardrail_event": "SELECT * FROM guardrail_events WHERE agent_id=? ORDER BY id DESC LIMIT 1",
        "latest_policy_decision": "SELECT * FROM policy_decisions WHERE agent_id=? ORDER BY id DESC LIMIT 1",
        "latest_usage_event": "SELECT * FROM usage_events WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
    }.items():
        rows = control_plane.store.query(sql, (agent_id,))
        contract[key] = rows[0] if rows else None
    return contract


def _agent_capability(agent_id: str) -> str:
    if agent_id in {"policy_assistant_agent", "loan_assessment_agent"}:
        return "rag"
    if agent_id == "collections_workflow_agent":
        return "collections_workflow"
    if agent_id and agent_id.startswith("sample_"):
        return "external"
    return "deterministic"


def _source_from_metadata(row: dict, default: str = "runtime") -> str:
    metadata = row.get("rag_evaluation") if isinstance(row.get("rag_evaluation"), dict) else {}
    source = metadata.get("source") or metadata.get("evaluation_source") or row.get("source") or default
    if source == "demo_endpoint":
        return "admin_validation"
    if source == "automatic":
        return "runtime"
    return source


def _enrich_rag_evaluation(row: dict) -> dict:
    metadata = row.get("rag_evaluation") if isinstance(row.get("rag_evaluation"), dict) else {}
    source = _source_from_metadata(row)
    method = row.get("evaluator_method") or metadata.get("evaluator_method")
    simulated = bool(metadata.get("is_simulated") or source in {"admin_validation", "simulation"} or method in {"admin_validation", "demo_simulation"})
    coverage = metadata.get("retrieved_evidence_coverage", row.get("citation_coverage"))
    row.update({
        "source": source,
        "evaluation_source": metadata.get("evaluation_source") or source,
        "is_simulated": simulated,
        "agent_capability": metadata.get("agent_capability") or _agent_capability(row.get("agent_id")),
        "retrieved_evidence_coverage": coverage,
        "score_methods": metadata.get("score_methods") or {
            "groundedness_score": "lexical_groundedness",
            "semantic_similarity_score": "embedding_similarity" if method in {"embedding_similarity", "hybrid"} else "lexical_similarity",
            "answer_relevance_score": "lexical_answer_relevance",
            "retrieved_evidence_coverage": "retrieved_evidence_coverage",
            "llm_judge_score": "llm_judge" if row.get("llm_judge_score") is not None else "not_run",
        },
        "score_method_labels": metadata.get("score_method_labels") or [
            "lexical_groundedness",
            "embedding_similarity",
            "lexical_answer_relevance",
            "retrieved_evidence_coverage",
        ],
    })
    return row


def _with_source(rows, source="runtime"):
    normalized = []
    for row in rows:
        item = dict(row)
        item.setdefault("source", source)
        if item["source"] == "automatic":
            item["source"] = "runtime"
        normalized.append(item)
    return normalized


@router.get("/agents")
async def agents(): return {"agents": [_agent_with_primitives(item["agent_id"]) for item in control_plane.registry.list_agents()]}


@router.get("/agents/{agent_id}")
async def agent(agent_id: str):
    try: return _agent_with_primitives(agent_id)
    except KeyError as exc: raise HTTPException(404, str(exc))


@router.get("/agents/{agent_id}/contract")
async def agent_contract(agent_id: str):
    """Return the Agent Contract for a registered agent.

    This is a read-only view of the manifest-backed contract used by the harness
    to govern agent execution.  It contains only contract/manifest fields - no
    runtime metrics, no event history, no enriched primitives.  The caller should
    use GET /agents/{agent_id} for the full runtime-enriched agent detail.
    """
    try:
        contract = control_plane.registry.get_contract(agent_id)
    except (AgentNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc))

    return control_plane.registry.registry_contract_view(agent_id)


@router.get("/agents/{agent_id}/status")
async def agent_status(agent_id: str):
    contract = control_plane.registry.get_contract(agent_id)
    return {"agent_id": agent_id, "status": contract.status.value}


@router.get("/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    return control_plane.registry.get_adapter(agent_id).get_health()


@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(agent_id: str, body: dict):
    return await _invoke_control_plane(agent_id, body, typed=True)


async def _invoke_control_plane(agent_id: str, body: dict, *, trace_name=None, request_source="generic_invoke", typed=False):
    payload = body or {}
    request = InvocationRequest(
        agent_id=agent_id,
        action=payload.get("action", "invoke"),
        payload=payload,
        invoking_user_id=payload.get("invoking_user_id"),
        invoking_agent_id=payload.get("invoking_agent_id"),
        correlation_id=payload.get("trace_id") or payload.get("correlation_id"),
        session_id=payload.get("session_id") or payload.get("user_id"),
        requested_tools=payload.get("requested_tools"),
        metadata={"trace_name": trace_name, "request_source": request_source},
    )
    result = await control_plane.invoke_result(request)
    response = result.model_dump()
    if result.status == "completed":
        response["result"] = result.output
    else:
        response["decision"] = "BLOCK" if result.status == "blocked" else "ERROR"
        response["reason"] = (result.error or {}).get("message")
        response["adapter_invoked"] = False
    return response if typed else ({**response, "result": result.output} if result.status == "completed" else response)


@router.post("/agents/{agent_id}/heartbeat")
async def heartbeat(agent_id: str, body: dict | None = None):
    contract = control_plane.registry.get_contract(agent_id)
    trace_id = (body or {}).get("trace_id", str(uuid.uuid4()))
    control_plane.store.add_event("HEARTBEAT", trace_id, agent_id, body or {})
    return {"agent_id": agent_id, "status": contract.status.value, "heartbeat": "accepted", "trace_id": trace_id, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/runs")
async def runs(limit: int = 100): return {"runs": control_plane.store.list_runs(limit=_limit(limit))}


@router.get("/runs/{trace_id}")
async def run(trace_id: str):
    result = control_plane.store.list_runs(trace_id=trace_id)
    if not result: raise HTTPException(404, "Execution Trace not found")
    return result


@router.get("/usage/summary")
async def usage_summary():
    return control_plane.services.usage_meter.get_summary()


@router.get("/usage/events")
async def usage_events(limit: int = 100, agent_id: str | None = None, model: str | None = None):
    return {"events": control_plane.services.usage_meter.get_events(limit=_limit(limit), agent_id=agent_id, model=model)}


@router.get("/usage/budgets")
async def usage_budgets():
    status = control_plane.services.budget_manager.get_budget_status()
    existing = {item["agent_id"] for item in status.get("definitions", [])}
    for item in control_plane.registry.list_agents():
        contract = control_plane.registry.get_contract(item["agent_id"])
        policy = contract.budget_policy or {}
        if policy and contract.agent_id not in existing:
            effective = contract.effective_contract()["model_policy"]
            status["definitions"].append({
                "definition_id": f"{contract.agent_id}:{policy.get('period', 'invocation')}",
                "agent_id": contract.agent_id,
                "provider": effective.get("provider"),
                "model": effective.get("deployment"),
                "currency": "USD",
                "active": True,
                "policy": policy,
                "configured_only": True,
            })
    return status


@router.get("/events")
async def events(limit: int = 100): return {"events": control_plane.store.list_events(limit=_limit(limit))}


@router.get("/evaluations")
async def evaluations(limit: int = 100, agent_id: str | None = None):
    rows = control_plane.store.list_rag_evaluations(limit=_limit(limit), agent_id=agent_id)
    rules = (control_plane.degradation.rules or {}).get("rag", {})
    for row in rows:
        _enrich_rag_evaluation(row)
        scores = [("groundedness_score", "min_groundedness"), ("semantic_similarity_score", "min_semantic_similarity"), ("retrieved_evidence_coverage", "min_citation_coverage"), ("answer_relevance_score", "min_answer_relevance")]
        failed = [score for score, threshold in scores if row.get(score) is not None and threshold in rules and row[score] < rules[threshold]]
        row["quality_gate"] = "BLOCK" if any(row.get(score) is not None and row[score] < .4 for score, _ in scores) else "REVIEW" if failed else "PASS"
        row["action_taken"] = "human_review_required" if row["quality_gate"] != "PASS" else "no_action"
    return {"evaluations": rows}


@router.get("/evaluations/{trace_id}")
async def evaluation(trace_id: str):
    evaluations = control_plane.store.list_rag_evaluations(trace_id=trace_id)
    if not evaluations:
        raise HTTPException(404, "RAG evaluation not found")
    return _enrich_rag_evaluation(evaluations[0])


@router.post("/events/ingest")
async def ingest_event(body: dict):
    agent_id = body.get("agent_id")
    if not agent_id or not control_plane.registry.exists(agent_id): raise HTTPException(404, "Registered agent_id is required")
    trace_id = body.get("trace_id") or str(uuid.uuid4())
    event_type = body.get("event_type", "EXTERNAL_EVENT")
    contract = control_plane.registry.get_contract(agent_id)
    with get_tracer().trace(f"Agent Control Plane Event - {agent_id}", inputs=safe_summary(body), metadata=_trace_metadata(agent_id, trace_id, "external_event"), tags=["agent_harness", "control_plane", "banking", agent_id, contract.business_function, contract.adapter_type]) as root:
        with get_tracer().span("audit_persist", inputs={"event_type": event_type}) as span:
            control_plane.store.add_event(event_type, trace_id, agent_id, body.get("payload", {}))
            span.set_output({"stored": True})
        result = {"ingested": True, "trace_id": trace_id, "event_type": event_type}; root.set_output(result); return result


@router.get("/events/{trace_id}")
async def trace_events(trace_id: str): return {"trace_id": trace_id, "events": control_plane.store.list_events(trace_id, 500)}


@router.post("/policy/check")
async def policy_check(body: dict):
    try:
        decision = control_plane.policy.check(body["agent_id"], body.get("action", "invoke"), body.get("context", body), body.get("trace_id"))
        return decision.to_dict()
    except KeyError as exc: raise HTTPException(404, str(exc))


@router.get("/policy/decisions")
async def policy_decisions(limit: int = 100): return {"decisions": _with_source(control_plane.store.query("SELECT * FROM policy_decisions ORDER BY id DESC LIMIT ?", (_limit(limit),)))}


@router.post("/tools/authorize")
async def authorize_tool(body: dict):
    try:
        request = ToolInvocationRequest(**body)
        response = control_plane.tool_authorization.authorize(request)
        result = response.to_dict()
        
        # Build nested llm_judge object for the API response
        result["llm_judge"] = {
            "status": response.llm_judge_status,
            "model": response.llm_judge_model,
            "risk_score": response.llm_judge_score,
            "recommended_decision": response.llm_judge_decision,
            "detected_risks": response.llm_judge_detected_risks,
            "reasons": response.llm_judge_reasons,
            "prompt_version": response.llm_judge_prompt_version,
            "latency_ms": response.llm_judge_latency_ms
        }
        
        # Remove flat fields
        for field in ["llm_judge_status", "llm_judge_model", "llm_judge_score", "llm_judge_decision", "llm_judge_reasons", "llm_judge_prompt_version", "llm_judge_latency_ms", "llm_judge_detected_risks"]:
            result.pop(field, None)
            
        return result
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/tools/authorization-events")
async def tool_authorization_events(limit: int = 100, agent_id: str | None = None, decision: str | None = None, source: str | None = None):
    return {"events": control_plane.store.list_tool_authorization_events(limit=_limit(limit), agent_id=agent_id, decision=decision, source=source)}


def _mcp_error(exc: MCPGovernanceError):
    status_code = {
        "MCP_PERMISSION_DENIED": 403,
        "MCP_DIRECT_BYPASS_PREVENTED": 403,
        "MCP_AUTH_FAILURE": 401,
        "MCP_SERVER_UNAVAILABLE": 503,
        "MCP_TIMEOUT": 504,
        "MCP_SCHEMA_MISMATCH": 422,
        "MCP_TOOLSET_CHANGED": 409,
        "MCP_UNSUPPORTED_TRANSPORT": 422,
        "MCP_PAYLOAD_TOO_LARGE": 413,
    }.get(exc.code, 500)
    raise HTTPException(status_code, {"code": exc.code, "message": exc.message})


@router.get("/mcp/servers")
async def mcp_servers():
    servers = control_plane.store.list_mcp_servers()
    tools = control_plane.store.list_mcp_tools()
    invocations = control_plane.store.list_mcp_invocations(limit=20)
    server_ids = {server["server_id"] for server in servers}
    if "banking_mcp" in server_ids:
        servers = [server for server in servers if server["server_id"] != "demo_banking_mcp"]
        tools = [tool for tool in tools if tool["server_id"] != "demo_banking_mcp"]
        invocations = [item for item in invocations if item.get("server_id") != "demo_banking_mcp"]
    by_server = {}
    for tool in tools:
        by_server.setdefault(tool["server_id"], []).append(tool)
    allowed_agents = {}
    for item in control_plane.registry.list_agents():
        contract = control_plane.registry.get_contract(item["agent_id"])
        for ref in (contract.policy_permissions or {}).get("mcp_tools") or []:
            allowed_agents.setdefault(ref, []).append(contract.agent_id)
    return {
        "servers": [{**server, "tools": by_server.get(server["server_id"], [])} for server in servers],
        "allowed_agents": allowed_agents,
        "recent_invocations": invocations,
        "integration_types": {
            "internal_tools": "In-process harness tools governed by tool authorization.",
            "rest_integrations": "REST/webhook adapters governed as external agents.",
            "mcp_tools": "Real MCP tools discovered through approved stdio or streamable HTTP transports.",
        },
    }


@router.get("/mcp/servers/{server_id}")
async def mcp_server(server_id: str):
    server = control_plane.store.get_mcp_server(server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    return {"server": server, "tools": control_plane.store.list_mcp_tools(server_id)}


@router.post("/mcp/servers/{server_id}/refresh", dependencies=[Depends(require_admin)])
async def refresh_mcp_server(server_id: str):
    try:
        return await control_plane.mcp.refresh_server(server_id)
    except MCPGovernanceError as exc:
        _mcp_error(exc)


@router.get("/mcp/tools")
async def mcp_tools(server_id: str | None = None):
    return {"tools": control_plane.store.list_mcp_tools(server_id)}


@router.get("/mcp/invocations")
async def mcp_invocations(limit: int = 100, server_id: str | None = None, tool_name: str | None = None, decision: str | None = None):
    return {"invocations": control_plane.store.list_mcp_invocations(limit=_limit(limit), server_id=server_id, tool_name=tool_name, decision=decision)}


@router.post("/agents/{agent_id}/mcp/{server_id}/{tool_name}")
async def invoke_mcp_tool(agent_id: str, server_id: str, tool_name: str, body: dict):
    if any(key in (body or {}) for key in ("server_url", "endpoint", "transport", "command", "command_reference")):
        raise HTTPException(400, {"code": "MCP_ARBITRARY_SERVER_REJECTED", "message": "MCP servers are administrator configured; request payloads cannot supply endpoints or commands"})
    try:
        return await control_plane.mcp.invoke_tool(MCPInvocationRequest(
            agent_id=agent_id,
            server_id=server_id,
            tool_name=tool_name,
            arguments=(body or {}).get("arguments") or {},
            parent_agent_invocation_id=(body or {}).get("parent_agent_invocation_id"),
            trace_id=(body or {}).get("trace_id") or str(uuid.uuid4()),
            human_override=(body or {}).get("human_override") or {},
        ))
    except MCPGovernanceError as exc:
        _mcp_error(exc)


@router.get("/security/principals", dependencies=[Depends(require_admin)])
async def list_principals():
    return {"principals": control_plane.store.list_principals()}


@router.get("/security/principals/{principal_id}", dependencies=[Depends(require_admin)])
async def read_principal(principal_id: str):
    principal = control_plane.store.get_principal(principal_id)
    if not principal:
        raise HTTPException(404, "Principal not found")
    return principal


@router.post("/security/principals", dependencies=[Depends(require_admin)])
async def create_principal(body: dict):
    agent_id = body.get("agent_id")
    if not agent_id or not control_plane.registry.exists(agent_id):
        raise HTTPException(422, "Registered agent_id is required")
    principal_id = body.get("principal_id") or f"principal-{uuid.uuid4()}"
    control_plane.store.execute(
        "INSERT INTO agent_principals(principal_id,agent_id,principal_type,display_name,status,credential_reference) VALUES(?,?,?,?,?,?)",
        (principal_id, agent_id, body.get("principal_type", "agent"), body.get("display_name") or agent_id, body.get("status", "active"), body.get("credential_reference")),
    )
    control_plane.authorization.invalidate(principal_id)
    return control_plane.store.get_principal(principal_id)


@router.post("/security/principals/{principal_id}/disable", dependencies=[Depends(require_admin)])
async def disable_principal(principal_id: str, body: dict | None = None):
    if not control_plane.store.get_principal(principal_id):
        raise HTTPException(404, "Principal not found")
    control_plane.store.execute("UPDATE agent_principals SET status='disabled',updated_at=CURRENT_TIMESTAMP WHERE principal_id=?", (principal_id,))
    control_plane.authorization.invalidate(principal_id)
    return {"principal_id": principal_id, "status": "disabled"}


@router.get("/security/roles", dependencies=[Depends(require_admin)])
async def list_roles():
    return {"roles": control_plane.store.list_roles()}


@router.post("/security/principals/{principal_id}/roles", dependencies=[Depends(require_admin)])
async def assign_role(principal_id: str, body: dict):
    role_id = body.get("role_id")
    if not role_id:
        raise HTTPException(422, "role_id is required")
    if not control_plane.store.get_principal(principal_id):
        raise HTTPException(404, "Principal not found")
    if not control_plane.store.query("SELECT role_id FROM roles WHERE role_id=?", (role_id,)):
        raise HTTPException(404, "Role not found")
    control_plane.store.execute(
        "INSERT OR REPLACE INTO principal_roles(principal_id,role_id,scope_type,scope_value,valid_from,valid_until,granted_by) VALUES(?,?,?,?,?,?,?)",
        (principal_id, role_id, body.get("scope_type", "global"), body.get("scope_value", "*"), body.get("valid_from") or datetime.now(timezone.utc).isoformat(), body.get("valid_until"), body.get("granted_by", "local-demo-admin")),
    )
    control_plane.authorization.invalidate(principal_id)
    return control_plane.authorization.effective_permissions(principal_id)


@router.delete("/security/principals/{principal_id}/roles/{role_id}", dependencies=[Depends(require_admin)])
async def revoke_role(principal_id: str, role_id: str, scope_type: str = "global", scope_value: str = "*"):
    control_plane.store.execute("DELETE FROM principal_roles WHERE principal_id=? AND role_id=? AND scope_type=? AND scope_value=?", (principal_id, role_id, scope_type, scope_value))
    control_plane.authorization.invalidate(principal_id)
    return {"principal_id": principal_id, "role_id": role_id, "revoked": True}


@router.get("/security/principals/{principal_id}/effective-permissions", dependencies=[Depends(require_admin)])
async def effective_permissions(principal_id: str):
    if not control_plane.store.get_principal(principal_id):
        raise HTTPException(404, "Principal not found")
    return control_plane.authorization.effective_permissions(principal_id)


@router.get("/security/authorization-decisions", dependencies=[Depends(require_admin)])
async def authorization_decisions(limit: int = 100, principal_id: str | None = None, decision: str | None = None):
    return {"decisions": control_plane.store.list_authorization_decisions(limit=_limit(limit), principal_id=principal_id, decision=decision)}


@router.get("/guardrails")
async def guardrails():
    names = [("GRD-CUST-DATA-001","Manifest action/data-scope policy"),("GRD-PII-001","Regex-based PII guardrail"),("GRD-PAY-001","Banking business-rule policy"),("GRD-SQL-001","Pattern-based SQL guardrail"),("GRD-CONDUCT-001","Collections Conduct Guardrail"),("GRD-REG-001","Regulatory Advice Boundary Guardrail"),("GRD-INJECT-001","Static prompt-injection heuristic"),("GRD-SCOPE-001","Lifecycle status enforcement")]
    return {"guardrails": [{"guardrail_id": gid, "name": name} for gid, name in names]}


@router.get("/guardrails/events")
async def guardrail_events(limit: int = 100): return {"events": _with_source(control_plane.store.query("SELECT * FROM guardrail_events ORDER BY id DESC LIMIT ?", (_limit(limit),)))}


@router.get("/prompts")
async def prompts():
    try:
        return {"prompts": control_plane.primitives.prompts()}
    except PromptRegistryError as exc:
        raise HTTPException(500, str(exc))


@router.get("/prompts/{prompt_id}")
async def prompt(prompt_id: str, debug: bool = False):
    unified = control_plane.primitives.prompt(prompt_id)
    if unified and unified["source"] == "local_markdown":
        try:
            # Retain the established detail response (including debug text) and enrich it.
            return {**prompt_registry.load(prompt_id).public_dict(include_text=debug), **unified}
        except PromptRegistryError as exc:
            raise HTTPException(404, str(exc))
    if unified:
        return unified
    try:
        return prompt_registry.load(prompt_id).public_dict(include_text=debug)
    except PromptRegistryError as exc:
        raise HTTPException(404, str(exc))


@router.get("/skills")
async def skills(): return {"skills": control_plane.primitives.list_skills()}


@router.get("/skills/{skill_id}")
async def skill(skill_id: str):
    try: return control_plane.primitives.skill(skill_id)
    except KeyError: raise HTTPException(404, "Skill not found")


@router.get("/tools")
async def tools(): return {"tools": control_plane.primitives.list_tools()}


@router.get("/tools/{tool_id}")
async def tool(tool_id: str):
    try: return control_plane.primitives.tool(tool_id)
    except KeyError: raise HTTPException(404, "Tool not found")


@router.get("/primitives/validation")
async def primitive_validation(): return control_plane.primitives.validation()


@router.get("/memory/contracts")
async def memory_contracts(): return {"contracts": control_plane.primitives.list_memory_contracts()}


@router.get("/memory/contracts/{scope}")
async def memory_contract(scope: str):
    try: return control_plane.primitives.memory_contract(scope)
    except KeyError: raise HTTPException(404, "Memory contract not found")


@router.get("/memory/events")
async def memory_events(limit: int = 100):
    # Contract-level telemetry only; no raw memory record or customer PII is returned.
    rows = control_plane.store.query("SELECT agent_id, entity_id, updated_at FROM agent_memory ORDER BY updated_at DESC LIMIT ?", (_limit(limit),))
    return {"events": [{"agent_id": row["agent_id"], "record_present": True, "updated_at": row["updated_at"]} for row in rows]}


@router.get("/hooks")
async def hooks(): return {"hooks": control_plane.primitives.list_hooks()}


@router.get("/hooks/events")
async def hook_events(limit: int = 100):
    return {"events": control_plane.store.query("SELECT * FROM observability_events WHERE event_type LIKE 'HOOK_%' ORDER BY id DESC LIMIT ?", (_limit(limit),))}

@router.get("/observability/status")
async def observability_status():
    """Return integration status for the observability layer.
    Safe to expose: no API keys or secrets are returned.
    """
    from agent_harness.observability import get_langsmith_status
    ls = get_langsmith_status()

    sdk = ls.get("sdk_available", False)
    enabled = ls.get("tracing_enabled", False)

    if enabled:
        integration_level = "LIVE_BACKEND"
        status_label = (
            "LangSmith tracing is active. Spans are sent to LangSmith for every "
            "control-plane invocation when LANGSMITH_TRACING=true and "
            "LANGSMITH_API_KEY are set. Run URLs are not persisted in the local DB."
        )
    elif sdk:
        integration_level = "CONFIG_PRESENT_NOT_ENABLED"
        status_label = (
            "LangSmith SDK is installed and tracing code is wired in the backend. "
            "Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to activate."
        )
    else:
        integration_level = "NOT_PRESENT"
        status_label = (
            "LangSmith SDK is not installed. "
            "Install langsmith and set LANGSMITH_TRACING + LANGSMITH_API_KEY to enable."
        )

    return {
        "sdk_available": sdk,
        "tracing_enabled": enabled,
        "project": ls.get("project"),
        "endpoint": ls.get("endpoint"),
        "status_label": status_label,
        "integration_level": integration_level,
        "trace_url_persisted": False,
        "local_store": True,
        "local_store_note": (
            "All observability_events, policy_decisions, guardrail_events, and "
            "kill_switch_events are always written to the local SQLite store. "
            "LangSmith is additive and layered on top."
        ),
    }

@router.get("/evaluators")
async def evaluator_registry(): return {"evaluators": control_plane.primitives.list_evaluators()}


@router.get("/evaluators/{evaluator_id}")
async def evaluator(evaluator_id: str):
    try: return control_plane.primitives.evaluator(evaluator_id)
    except KeyError: raise HTTPException(404, "Evaluator not found")


@router.post("/kill-switch/{agent_id}")
async def kill_switch(agent_id: str, body: dict):
    try:
        status = body.get("status", body.get("new_status", "disabled"))
        reason = body.get("reason")
        if not reason: raise HTTPException(400, "reason is required for manual lifecycle transitions")
        source = body.get("source", "manual_admin")
        approved_by = body.get("approved_by")
        result = control_plane.kill_switch.change_status(
            agent_id,
            status,
            source,
            reason,
            body.get("triggered_by", "admin"),
            trace_id=body.get("trace_id"),
            severity=body.get("severity", "INFO"),
            approved_by=approved_by,
            override_type=body.get("override_type"),
            evidence=body.get("evidence"),
            change_ticket=body.get("change_ticket"),
            second_approved_by=body.get("second_approved_by"),
        )
        return {**result, "status": result["new_status"]}
    except AgentNotFoundError as exc: raise HTTPException(404, str(exc))
    except ValueError as exc: raise HTTPException(400, str(exc))


@router.get("/kill-switch/events")
async def kill_events(limit: int = 50): return {"events": _with_source(control_plane.store.query("SELECT * FROM kill_switch_events ORDER BY id DESC LIMIT ?", (_limit(limit, 200),)))}


@router.get("/degradation/events")
async def degradation_events(limit: int = 50): return {"events": _with_source(control_plane.store.query("SELECT * FROM degradation_events ORDER BY id DESC LIMIT ?", (_limit(limit, 200),)))}


@router.post("/demo/run-policy-agent")
async def demo_policy(body: dict): return await _invoke_control_plane("policy_assistant_agent", body or {"query": "What are the bank KYC requirements?"}, trace_name="Policy Assistant Demo Run", request_source="demo_endpoint")


@router.post("/demo/run-loan-assessment")
async def demo_loan(body: dict): return await _invoke_control_plane("loan_assessment_agent", body, trace_name="Loan Assessment Demo Run", request_source="demo_endpoint")


@router.post("/demo/run-collections")
async def demo_collections(body: dict):
    """Multi-mode Collections invoke - delegates through control plane governance.

    Accepted modes: pre_call | post_call | full_lifecycle | voice_greet | voice_analyze
    The frontend must send only account_id + transcript text (or captured_transcript_id).
    All evidence extraction is server-side.
    """
    payload = body or {"mode": "pre_call", "account_id": "ACC-DEMO-01"}
    if "mode" not in payload:
        payload = {"mode": "pre_call", **payload}
    return await _invoke_control_plane(
        "collections_workflow_agent", payload,
        trace_name=f"Collections {payload['mode'].replace('_', ' ').title()} Run",
        request_source="demo_endpoint",
    )


@router.get("/demo/collections/accounts")
async def collections_accounts():
    from banking_agents.collections_domain import list_accounts
    principal_id = control_plane.authorization.principal_id_for_agent("collections_workflow_agent")
    control_plane.authorization.enforce(AuthorizationRequest(
        agent_id="collections_workflow_agent",
        principal_id=principal_id,
        invocation_id=str(uuid.uuid4()),
        action="read",
        resource_type="data",
        resource_id="collections_accounts",
        context={"lifecycle_status": control_plane.registry.get_contract("collections_workflow_agent").status.value, "approval_state": "not_required"},
    ))
    return {"accounts": list_accounts(authorize=False)}


@router.get("/collections/transcripts")
async def collections_transcripts():
    """Return the captured transcript library for UI selection."""
    from banking_agents.external_plugins.collections_working_demo.wrapper import list_captured_transcripts
    return {"transcripts": list_captured_transcripts()}


def _collections_voice_status() -> dict:
    from banking_agents.external_plugins.collections_working_demo.vendor_src.voice_pipeline import groq_configured

    contract = control_plane.registry.get_contract("collections_workflow_agent")
    stt_available = groq_configured()
    lifecycle_status = contract.status.value
    ready = lifecycle_status == "active" and stt_available
    blocker = None
    if lifecycle_status != "active":
        blocker = f"collections_workflow_agent is {lifecycle_status}; lifecycle review/reset is required before live voice"
    elif not stt_available:
        blocker = "GROQ_API_KEY not configured; live STT/LLM/TTS voice processing unavailable"
    return {
        "agent_id": "collections_workflow_agent",
        "lifecycle_status": lifecycle_status,
        "provider": "groq" if stt_available else "unconfigured",
        "mic_capture_required": "browser MediaRecorder audio/webm",
        "stt_available": stt_available,
        "turn_route": "/api/v1/control/collections/voice/turn",
        "finalize_route": "/api/v1/control/collections/voice/finalize",
        "ready": ready,
        "blocker": blocker,
    }


def _require_live_voice_ready() -> dict:
    status = _collections_voice_status()
    if status["lifecycle_status"] != "active":
        raise HTTPException(403, status["blocker"])
    if not status["stt_available"]:
        raise HTTPException(503, status["blocker"])
    return status


def _voice_conversation_to_transcript(conversation: list[dict]) -> str:
    lines = []
    for turn in conversation or []:
        role = str(turn.get("role", "")).lower()
        content = str(turn.get("content", "")).strip()
        if not content:
            continue
        speaker = "Customer" if role in {"user", "customer"} else "ARIA" if role in {"assistant", "aria"} else role.title() or "Speaker"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


@router.post("/collections/{account_id}/post-call")
async def collections_post_call(account_id: str, body: dict):
    """Run server-side transcript extraction + post-call pipeline.

    The frontend must send ONLY:
      { "transcript": "...", "captured_transcript_id": "optional" }

    Do NOT send pre-extracted fields (sentiment, ptp_date, life_event_detected, etc.).
    The backend extracts all evidence via ConversationIntelligenceAgent.
    """
    transcript = body.get("transcript", "")
    captured_id = body.get("captured_transcript_id")

    # Resolve transcript from sample library if direct text not provided
    if not transcript.strip() and captured_id:
        from banking_agents.external_plugins.collections_working_demo.wrapper import _load_sample
        sample = _load_sample(captured_id)
        if sample:
            transcript = sample.get("transcript", "")

    if not transcript.strip():
        raise HTTPException(422, "transcript or captured_transcript_id with text is required")

    # Route through wrapper via control plane (preserves governance)
    payload = {
        "mode": "post_call",
        "account_id": account_id,
        "transcript": transcript,
        "captured_transcript_id": captured_id,
    }
    try:
        result = await _invoke_control_plane(
            "collections_workflow_agent", payload,
            trace_name="Collections Post-Call Analysis",
            request_source="post_call_endpoint",
        )
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/collections/{account_id}/history")
async def collections_post_call_history(account_id: str):
    from banking_agents.collections_domain.post_call_service import account_post_call_history
    try:
        return account_post_call_history(account_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/collections/voice/greet")
async def collections_voice_greet(body: dict):
    """Generate ARIA voice greeting for an account.

    Returns aria_text (always) + audio_b64 (if Groq configured).
    provider: 'groq' | 'template'
    voice_pipeline_status: backend availability and frontend wiring status.

    Browser microphone wiring is integrated through the live voice endpoints.
    """
    payload = {"mode": "voice_greet", **body}
    return await _invoke_control_plane(
        "collections_workflow_agent", payload,
        trace_name="Collections Voice Greeting",
        request_source="voice_endpoint",
    )


@router.get("/collections/voice/status")
async def collections_voice_status():
    """Report whether browser mic audio can be processed by the governed backend."""
    return _collections_voice_status()


@router.post("/collections/voice/start")
async def collections_voice_start(body: dict):
    """Start a governed live voice session after lifecycle/provider checks."""
    status = _require_live_voice_ready()
    greeting = await collections_voice_greet(body or {})
    return {"voice_status": status, "greeting": greeting}


@router.post("/collections/voice/turn")
async def collections_voice_turn(body: dict):
    """Process one voice turn: audio_b64 -> STT -> LLM -> TTS + intelligence.

    Requires:
      { account_id, audio_b64, conversation: [{role, content}] }

    Note: Frontend browser MediaRecorder integration required to send audio.
    Backend pipeline (Groq Whisper + LLaMA + Orpheus) is fully operational.
    """
    account_id = body.get("account_id", "ACC-DEMO-01")
    audio_b64 = body.get("audio_b64", "")

    if not audio_b64:
        raise HTTPException(422, "audio_b64 required via browser MediaRecorder")

    voice_status = _require_live_voice_ready()
    payload = {"mode": "voice_turn", **body, "account_id": account_id}
    result = await _invoke_control_plane(
        "collections_workflow_agent",
        payload,
        trace_name="Collections Live Voice Turn",
        request_source="live_voice_endpoint",
    )
    return {"voice_status": voice_status, **result}


@router.post("/collections/voice/finalize")
async def collections_voice_finalize(body: dict):
    """Finalize a live voice session through the governed post-call workflow."""
    account_id = body.get("account_id", "ACC-DEMO-01")
    conversation = body.get("conversation", [])
    transcript = body.get("transcript") or _voice_conversation_to_transcript(conversation)
    if not transcript.strip():
        raise HTTPException(422, "live voice transcript is required")

    _require_live_voice_ready()
    payload = {
        "mode": "post_call",
        "account_id": account_id,
        "transcript": transcript,
        "call_metadata": {
            "channel": "live_browser_voice",
            "source": "mediarecorder_groq_voice_pipeline",
            "turn_count": len(conversation or []),
        },
    }
    return await _invoke_control_plane(
        "collections_workflow_agent",
        payload,
        trace_name="Collections Live Voice Finalize",
        request_source="live_voice_endpoint",
    )


@router.post("/demo/run-unsafe-sql")
async def demo_unsafe_sql(body: dict):
    agent_id, trace_id = body.get("agent_id", "collections_workflow_agent"), str(uuid.uuid4())
    sql = body.get("sql", "DROP TABLE customers; -- malicious")
    contract = control_plane.registry.get_contract(agent_id); tracer = get_tracer()
    tags = ["agent_harness", "control_plane", "banking", "demo", agent_id, contract.business_function, contract.adapter_type]
    with tracer.trace("Unsafe SQL Governance Test", inputs={"sql": "[REDACTED_SQL]"}, metadata=_trace_metadata(agent_id, trace_id, "demo_endpoint"), tags=tags) as root:
        with tracer.span("tool_authorization", inputs={"agent_id": agent_id, "action": "execute_sql", "raw_sql": "[REDACTED]"}) as span:
            req = ToolInvocationRequest(
                agent_id=agent_id, tool_id="sql_executor", action="execute_sql",
                data_scope="customer_db", payload_summary=sql, trace_id=trace_id, source="admin_validation"
            )
            decision = control_plane.tool_authorization.authorize(req)
            span.set_output(decision.to_dict())
            
        if decision.decision != "ALLOW":
            control_plane.registry.record_block(agent_id)
            
        with tracer.span("kill_switch_evaluation", inputs={"critical_events": decision.guardrails_evaluated}) as span:
            kill_result = None
            for event in decision.guardrails_evaluated: kill_result = control_plane.kill_switch.apply_guardrail(agent_id, event) or kill_result
            span.set_output({"action": kill_result or "no_action"})
        status = control_plane.registry.get_contract(agent_id).status.value
        event = next((item for item in decision.guardrails_evaluated if item["guardrail_id"] == "GRD-SQL-001"), None)
        severity = event.get("severity") if event else decision.risk_level.toLowerCase() if hasattr(decision.risk_level, 'toLowerCase') else decision.risk_level.lower()
        evidence = {
            "decision": decision.decision, "guardrail_id": event.get("guardrail_id") if event else decision.matched_policy, "severity": severity,
            "agent_id": agent_id, "kill_switch_action": "quarantine" if kill_result else ("quarantine" if decision.risk_level == "CRITICAL" or decision.risk_level == "HIGH" else None),
            "previous_status": (kill_result or {}).get("previous_status", contract.status.value), "new_status": "quarantined" if decision.risk_level in ["CRITICAL", "HIGH"] else status,
            "reason": "unsafe_sql", "adapter_invoked": False, "trace_id": trace_id,
        }
        
        if not kill_result and decision.risk_level in ["CRITICAL", "HIGH"]:
            kill_result = control_plane.kill_switch.change_status(
                agent_id,
                "quarantined",
                "unsafe_sql",
                "Blocked by tool authorization: " + decision.reason,
                trace_id=trace_id,
                severity=severity,
                evidence=evidence,
            )
            status = "quarantined"
            evidence["new_status"] = "quarantined"

        control_plane.store.add_event("UNSAFE_SQL_BLOCKED", trace_id, agent_id, evidence)
        result = {"trace_id": trace_id, "policy_decision": decision.to_dict(), "kill_switch_event": kill_result, "agent_status": status, "control_evidence": evidence}
        root.add_metadata({"status_after": result["agent_status"]}); root.set_output(result); return result


@router.post("/demo/simulate-degradation")
async def demo_degradation(body: dict):
    agent_id = body.get("agent_id", "collections_workflow_agent"); scenario = body.get("scenario", "repeated_failures")
    trace_id = str(uuid.uuid4()); contract = control_plane.registry.get_contract(agent_id); tracer = get_tracer()
    with tracer.trace("Degradation Simulation", inputs=safe_summary(body), metadata=_trace_metadata(agent_id, trace_id, "demo_endpoint"), tags=["agent_harness", "control_plane", "banking", "demo", agent_id, contract.business_function, contract.adapter_type]) as root:
        control_plane.registry.set_status(agent_id, "active")
        if scenario == "low_confidence":
            for index in range(3): control_plane.registry.record_run(agent_id, True, 400, 0.2)
        elif scenario == "high_latency":
            for index in range(3): control_plane.registry.record_run(agent_id, True, 15000 + index * 100, 0.8)
        elif scenario == "low_groundedness":
            evaluation = {
                "groundedness_score": 0.2,
                "semantic_similarity_score": 0.3,
                "llm_judge_score": None,
                "answer_relevance_score": 0.3,
                "retrieved_evidence_coverage": 0.0,
                "citation_coverage": 0.0,
                "evaluator_method": "admin_validation",
                "source": "admin_validation",
                "evaluation_source": "admin_validation",
                "is_simulated": True,
                "agent_capability": _agent_capability(agent_id),
                "score_methods": {
                    "groundedness_score": "admin_validation",
                    "semantic_similarity_score": "admin_validation",
                    "answer_relevance_score": "admin_validation",
                    "retrieved_evidence_coverage": "admin_validation",
                    "llm_judge_score": "not_run",
                },
                "reason": "Admin validation quality signal for lifecycle testing; hidden from runtime RAG views by default.",
            }
            control_plane.store.add_rag_evaluation(trace_id, agent_id, "[admin validation quality signal]", evaluation)
        else:
            for index in range(min(body.get("failed_runs", 3), 10)): control_plane.registry.record_run(agent_id, False, 3000 + index * 100, 0.3)
        with tracer.span("degradation_evaluation", inputs={"agent_id": agent_id, "metrics": control_plane.registry.metrics(agent_id)}) as span:
            event = control_plane.degradation.evaluate(agent_id, trace_id); span.set_output({"status_change": event or "no_change"})
        result = {"agent_id": agent_id, "scenario": scenario, "degradation_event": event, "status": control_plane.registry.get_contract(agent_id).status.value, "metrics": control_plane.registry.metrics(agent_id), "trace_id": trace_id}
        root.add_metadata({"status_after": result["status"]}); root.set_output(result); return result
