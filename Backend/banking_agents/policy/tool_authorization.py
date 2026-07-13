"""Tool and Action Authorization Boundary"""
import json
import re
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

from agent_harness.registry import AgentRegistry
from agent_harness.store import ControlPlaneStore
from agent_harness.primitives import PrimitiveCatalog
from agent_harness.authorization import AuthorizationRequest, AuthorizationService, PermissionDenied

from banking_agents.policy.llm_risk_judge import LLMRiskJudge, LLMRiskJudgeRequest

@dataclass
class ToolInvocationRequest:
    agent_id: str
    tool_id: str
    action: str
    data_scope: str
    payload_summary: str = ""
    resource_type: str = None
    resource_id: str = None
    customer_id: str = None
    account_id: str = None
    risk_context: dict = field(default_factory=dict)
    trace_id: str = None
    requested_by: str = None
    source: str = "runtime" # runtime | admin_validation | manual_validation
    human_override: dict = field(default_factory=dict)

@dataclass
class ToolAuthorizationResponse:
    decision: str
    agent_id: str
    tool_id: str
    action: str
    data_scope: str
    reason: str
    matched_policy: str
    required_approval: bool
    approval_satisfied: bool
    risk_level: str
    lifecycle_status: str
    guardrails_evaluated: list
    violations: list
    runtime_enforced: bool
    authorization_status: str
    audit_event_id: str
    trace_id: str
    source: str
    timestamp: str

    llm_judge_status: str = "not_run"
    llm_judge_model: str = None
    llm_judge_score: float = None
    llm_judge_decision: str = None
    llm_judge_reasons: list = field(default_factory=list)
    llm_judge_prompt_version: str = None
    llm_judge_latency_ms: int = None
    llm_judge_detected_risks: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

class ToolAuthorizationService:
    def __init__(self, registry: AgentRegistry, store: ControlPlaneStore, primitives: PrimitiveCatalog, policies_config: dict, guardrails, llm_judge: LLMRiskJudge = None, authorization: AuthorizationService = None):
        self.registry = registry
        self.store = store
        self.primitives = primitives
        self.policies = policies_config.get("policies", {})
        self.guardrails = guardrails
        self.llm_judge = llm_judge
        self.authorization = authorization

    def authorize(self, request: ToolInvocationRequest) -> ToolAuthorizationResponse:
        trace_id = request.trace_id or str(uuid.uuid4())
        
        decision = "ALLOW"
        reason = "Tool and action authorized"
        matched_policy = "default_allow"
        risk_level = "LOW"
        required_approval = False
        approval_satisfied = False
        violations = []
        guardrail_events = []
        lifecycle_status = "unknown"

        # 1. Unknown agent -> BLOCK
        if not self.registry.exists(request.agent_id):
            return self._finalize(request, "BLOCK", "Unknown agent", "unknown_agent", "HIGH", "unknown", False, False, [], ["unknown_agent"], trace_id)

        contract = self.registry.get_contract(request.agent_id)
        lifecycle_status = contract.status.value

        if self.authorization:
            try:
                self.authorization.enforce(AuthorizationRequest(
                    agent_id=request.agent_id,
                    principal_id=self.authorization.principal_id_for_agent(request.agent_id),
                    invocation_id=trace_id,
                    trace_id=trace_id,
                    action=request.action if request.action == "invoke" else "invoke",
                    resource_type=request.resource_type or "tool",
                    resource_id=request.resource_id or request.tool_id,
                    context={
                        "data_scope": request.data_scope,
                        "lifecycle_status": lifecycle_status,
                        "human_override": request.human_override,
                        "required_human_approval_for": contract.policy_permissions.get("requires_human_approval_for", []),
                    },
                ))
            except PermissionDenied as exc:
                return self._finalize(request, "BLOCK", exc.decision.reason_code, "rbac_denied", "HIGH", lifecycle_status, False, False, [], [exc.decision.reason_code], trace_id)

        # 2. Agent quarantined/disabled -> BLOCK
        if lifecycle_status in {"quarantined", "disabled"}:
            return self._finalize(request, "BLOCK", f"Agent is {lifecycle_status}", f"agent_{lifecycle_status}", "HIGH", lifecycle_status, False, False, [], [f"agent_{lifecycle_status}"], trace_id)

        # 3. Unknown tool -> BLOCK
        tool_definition = self.primitives.tools.get(request.tool_id)
        if not tool_definition:
            return self._finalize(request, "BLOCK", f"Unknown tool: {request.tool_id}", "unknown_tool", "HIGH", lifecycle_status, False, False, [], ["unknown_tool"], trace_id)

        # 4. Tool not allowed by agent -> BLOCK
        agent_tools = contract.policy_permissions.get("allowed_tools", contract.tools)
        if request.tool_id not in agent_tools and "*" not in agent_tools:
            return self._finalize(request, "BLOCK", f"Tool not allowed for agent: {request.tool_id}", "tool_not_allowed", "HIGH", lifecycle_status, False, False, [], ["tool_not_allowed"], trace_id)

        # 5. Unknown action -> BLOCK
        if not request.action:
            return self._finalize(request, "BLOCK", "Unknown action", "unknown_action", "HIGH", lifecycle_status, False, False, [], ["unknown_action"], trace_id)
            
        # 6. Action not allowed by tool -> BLOCK
        allowed_actions = tool_definition.get("allowed_actions", [])
        if allowed_actions and request.action not in allowed_actions and "*" not in allowed_actions:
            return self._finalize(request, "BLOCK", f"Action not allowed by tool: {request.action}", "action_not_allowed_by_tool", "HIGH", lifecycle_status, False, False, [], ["action_not_allowed_by_tool"], trace_id)

        # 7. Action not allowed by agent manifest -> BLOCK
        agent_allowed_actions = contract.policy_permissions.get("allowed_actions", [])
        if agent_allowed_actions and request.action not in agent_allowed_actions and "*" not in agent_allowed_actions:
            return self._finalize(request, "BLOCK", f"Action not allowed by agent manifest: {request.action}", "action_not_allowed_by_agent", "HIGH", lifecycle_status, False, False, [], ["action_not_allowed_by_agent"], trace_id)

        # 8. Data scope not allowed by tool or agent -> BLOCK
        tool_scopes = tool_definition.get("data_scopes", [])
        agent_scopes = contract.policy_permissions.get("allowed_data_scopes", [])
        if request.data_scope:
            if tool_scopes and request.data_scope not in tool_scopes and "*" not in tool_scopes:
                return self._finalize(request, "BLOCK", f"Data scope not allowed by tool: {request.data_scope}", "scope_not_allowed_by_tool", "HIGH", lifecycle_status, False, False, [], ["scope_not_allowed_by_tool"], trace_id)
            if agent_scopes and request.data_scope not in agent_scopes and "*" not in agent_scopes:
                return self._finalize(request, "BLOCK", f"Data scope not allowed by agent: {request.data_scope}", "scope_not_allowed_by_agent", "HIGH", lifecycle_status, False, False, [], ["scope_not_allowed_by_agent"], trace_id)

        # 9. Critical regex/business violation -> BLOCK
        guardrail_context = {
            "input_text": request.payload_summary,
            "action_input": request.payload_summary,
            "sql": request.payload_summary,
            "permissions": contract.policy_permissions,
            "data_scope": request.data_scope,
            "business_function": contract.business_function
        }
        guardrail_results = self.guardrails.evaluate(request.agent_id, request.action, guardrail_context, trace_id)
        guardrail_events = [event.to_dict() for event in guardrail_results]
        
        for event in guardrail_events:
            if event["decision"] == "BLOCK":
                return self._finalize(request, "BLOCK", event["reason"], "guardrail_violation", event["severity"], lifecycle_status, False, False, guardrail_events, [event["reason"]], trace_id)

        # Human override check
        human_override = request.human_override or {}
        override_valid = bool(human_override.get("approved") and human_override.get("approved_by") and human_override.get("reason"))

        # 10. Agent in review + sensitive action without human override -> REVIEW
        # We define any action other than simple invoke as sensitive for a review agent
        if lifecycle_status == "review" and request.action != "invoke":
            if not override_valid:
                return self._finalize(request, "REVIEW", "Agent in review requires human override for sensitive action", "agent_in_review", "MEDIUM", lifecycle_status, True, False, guardrail_events, [], trace_id)

        # Banking policy evaluation (11, 12, 13)
        policy_decision, policy_reason, policy_matched, policy_risk, policy_requires_approval = self._evaluate_banking_policies(request)
        
        # 11. Banking policy says BLOCK -> BLOCK
        if policy_decision == "BLOCK":
            return self._finalize(request, "BLOCK", policy_reason, policy_matched, policy_risk, lifecycle_status, policy_requires_approval, False, guardrail_events, [policy_reason], trace_id)
        
        # 12 & 13. Banking policy says REVIEW
        if policy_decision == "REVIEW":
            if override_valid:
                non_overridable = ["autonomous_waiver_approval", "autonomous_settlement_approval", "autonomous_charge_reversal"]
                if policy_matched in non_overridable:
                    return self._finalize(request, "BLOCK", "Action requires strict system override and cannot be manually overridden", "non_overridable_action", "CRITICAL", lifecycle_status, True, False, guardrail_events, ["Cannot override strictly blocked action"], trace_id)
                decision = "ALLOW"
                reason = f"Human override accepted for: {policy_reason}"
                matched_policy = "human_override_accepted"
                approval_satisfied = True
                required_approval = True
            else:
                return self._finalize(request, "REVIEW", policy_reason, policy_matched, policy_risk, lifecycle_status, True, False, guardrail_events, [], trace_id)

        # 14. Optional LLM Judge for soft risks
        llm_judge_result = None
        if self.llm_judge and self.llm_judge.enabled:
            judge_req = LLMRiskJudgeRequest(
                task_type=None,
                agent_id=request.agent_id,
                tool_id=request.tool_id,
                action=request.action,
                payload_summary=request.payload_summary,
                risk_context=request.risk_context,
                trace_id=trace_id
            )
            llm_judge_result = self.llm_judge.evaluate(judge_req)
            
            if llm_judge_result.judge_status == "success":
                judge_decision = llm_judge_result.recommended_decision
                if judge_decision == "BLOCK":
                    decision = "BLOCK"
                    reason = f"LLM Judge blocked action: {', '.join(llm_judge_result.reasons)}"
                    matched_policy = "llm_judge_blocked"
                    risk_level = "HIGH"
                elif judge_decision == "REVIEW" and decision != "BLOCK":
                    decision = "REVIEW"
                    reason = f"LLM Judge flagged action for review: {', '.join(llm_judge_result.reasons)}"
                    matched_policy = "llm_judge_review"
                    risk_level = "MEDIUM"

        # 15. Otherwise -> ALLOW
        if tool_definition.get("requires_human_approval", False) and decision == "ALLOW":
            if not override_valid:
                return self._finalize(request, "REVIEW", "Tool requires human approval", "tool_requires_approval", "MEDIUM", lifecycle_status, True, False, guardrail_events, [], trace_id)
            else:
                required_approval = True
                approval_satisfied = True
                reason = "Tool human approval satisfied"

        return self._finalize(request, decision, reason, matched_policy, risk_level, lifecycle_status, required_approval, approval_satisfied, guardrail_events, violations, trace_id, llm_judge_result)

    def _evaluate_banking_policies(self, request: ToolInvocationRequest):
        action = request.action
        
        if action in ["approve_waiver", "offer_settlement", "reverse_charge"]:
            return "REVIEW", f"{action} requires human approval", action, "HIGH", True
        if action == "legal_escalation":
            return "REVIEW", "Legal escalation requires human approval", "legal_escalation", "HIGH", True
        if action == "create_payment_link":
            return "REVIEW", "Payment link creation requires review depending on context", "create_payment_link", "MEDIUM", True
            
        if action in ["execute_sql", "write_sql"]:
            lower_sql = (request.payload_summary or "").lower()
            if any(kw in lower_sql for kw in ["drop ", "delete ", "truncate ", "alter "]):
                return "BLOCK", "Destructive SQL not allowed", "destructive_sql", "CRITICAL", False
            if "update " in lower_sql:
                return "REVIEW", "SQL update requires approval", "update_sql", "HIGH", True
            if "union " in lower_sql:
                return "BLOCK", "UNION SELECT injection pattern detected", "union_select_injection", "CRITICAL", False

        if action in ["read_bureau_summary", "read_sensitive_history"]:
            return "REVIEW", f"Sensitive data read ({action}) requires review", action, "MEDIUM", True
        if request.data_scope == "customer_pii" and "raw" in (request.payload_summary or "").lower():
            return "REVIEW", "Raw PII access requires review", "full_raw_pii_access", "HIGH", True
            
        if action in ["external_api_call", "vendor_agent_invoke"]:
            if re.search(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b", request.payload_summary):
                return "REVIEW", "External call may contain sensitive PII", "external_api_call_with_sensitive_data", "HIGH", True

        return "ALLOW", "", "", "LOW", False

    def _finalize(self, request, decision, reason, matched_policy, risk_level, lifecycle_status, required_approval, approval_satisfied, guardrail_events, violations, trace_id, llm_judge_result=None):
        response = ToolAuthorizationResponse(
            decision=decision,
            agent_id=request.agent_id,
            tool_id=request.tool_id,
            action=request.action,
            data_scope=request.data_scope,
            reason=reason,
            matched_policy=matched_policy,
            required_approval=required_approval,
            approval_satisfied=approval_satisfied,
            risk_level=risk_level,
            lifecycle_status=lifecycle_status,
            guardrails_evaluated=guardrail_events,
            violations=violations,
            runtime_enforced=True,
            authorization_status="runtime_enforced",
            audit_event_id="",
            trace_id=trace_id,
            source=request.source,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        if llm_judge_result:
            response.llm_judge_status = llm_judge_result.judge_status
            response.llm_judge_model = llm_judge_result.model
            response.llm_judge_score = llm_judge_result.risk_score
            response.llm_judge_decision = llm_judge_result.recommended_decision
            response.llm_judge_reasons = llm_judge_result.reasons
            response.llm_judge_prompt_version = llm_judge_result.prompt_version
            response.llm_judge_latency_ms = llm_judge_result.latency_ms
            response.llm_judge_detected_risks = llm_judge_result.detected_risks
        
        event_dict = response.to_dict()
        event_dict["payload_summary"] = request.payload_summary
        
        cursor = self.store.execute(
            "INSERT INTO tool_authorization_events(timestamp, trace_id, agent_id, tool_id, action, data_scope, decision, reason, matched_policy, risk_level, required_approval, approval_satisfied, lifecycle_status, guardrails_evaluated, violations, runtime_enforced, authorization_status, source, payload_summary, llm_judge_status, llm_judge_model, llm_judge_score, llm_judge_decision, llm_judge_reasons, llm_judge_prompt_version, llm_judge_latency_ms, llm_judge_detected_risks) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                response.timestamp, response.trace_id, response.agent_id, response.tool_id, response.action, response.data_scope, response.decision, response.reason, response.matched_policy, response.risk_level, 1 if response.required_approval else 0, 1 if response.approval_satisfied else 0, response.lifecycle_status, json.dumps(response.guardrails_evaluated), json.dumps(response.violations), 1 if response.runtime_enforced else 0, response.authorization_status, response.source, request.payload_summary,
                response.llm_judge_status, response.llm_judge_model, response.llm_judge_score, response.llm_judge_decision, json.dumps(response.llm_judge_reasons), response.llm_judge_prompt_version, response.llm_judge_latency_ms, json.dumps(response.llm_judge_detected_risks)
            )
        )
        response.audit_event_id = str(cursor.lastrowid)
        
        # Structure for API return and observability
        api_event_dict = response.to_dict()
        api_event_dict["llm_judge"] = {
            "status": response.llm_judge_status,
            "model": response.llm_judge_model,
            "risk_score": response.llm_judge_score,
            "recommended_decision": response.llm_judge_decision,
            "detected_risks": response.llm_judge_detected_risks,
            "reasons": response.llm_judge_reasons,
            "prompt_version": response.llm_judge_prompt_version,
            "latency_ms": response.llm_judge_latency_ms
        }
        
        self.store.add_event("TOOL_AUTHORIZATION_DECISION", trace_id, request.agent_id, api_event_dict)
        
        return response
