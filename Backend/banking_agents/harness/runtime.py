"""Thin bank-specific bootstrap for the reusable control-plane framework."""
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import os
import uuid
import logging

from agent_harness.config_loader import load_named_config
from agent_harness.contract_validator import ContractValidator
from agent_harness.degradation_monitor import DegradationMonitor
from agent_harness.exceptions import (
    AdapterError,
    AdapterTimeoutError,
    AgentNotFoundError,
    ContractValidationError,
)
from agent_harness.invocation import (
    InvocationContext,
    InvocationRequest,
    InvocationResult,
    RuntimeErrorCode,
    RuntimeInvocationError,
)
from agent_harness.authorization import (
    AuthorizationRequest,
    AuthorizationService,
    PermissionDenied,
    reset_current_authorization_context,
    set_current_authorization_context,
)
from agent_harness.registry import AgentRegistry, agent_registry as legacy_registry
from agent_harness.store import ControlPlaneStore
from agent_harness.redaction import contract_summary, safe_summary
from agent_harness.trace_provider import LangSmithTraceProvider, LocalTraceProvider
from agent_harness.tracing import get_tracer
from agent_harness.budget import BudgetManager
from agent_harness.usage import UsageMeter, configure_budget_manager, configure_usage_meter, usage_context
from agent_harness.primitives import HookDispatcher, PrimitiveCatalog
from agent_harness.mcp_governance import GovernedMCPService
from banking_agents.policy.control_plane import BankKillSwitchService, BankPolicyEngine
from banking_agents.policy.tool_authorization import ToolAuthorizationService


BANKING_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = BANKING_ROOT / "config"
DATA_DIR = BANKING_ROOT.parent / "data"
logger = logging.getLogger(__name__)


class Services: pass


class ControlPlaneRuntime:
    def __init__(self):
        self.store = ControlPlaneStore(DATA_DIR / "control_plane.db")
        self.services = Services(); self.services.store = self.store; self.services.tracer = get_tracer(); self.services.trace_provider = LangSmithTraceProvider(LocalTraceProvider(self.store), self.services.tracer)
        self.services.usage_meter = UsageMeter(self.store, CONFIG_DIR / "model_pricing.yaml")
        self.services.budget_manager = BudgetManager(self.store, self.services.usage_meter)
        configure_usage_meter(self.services.usage_meter)
        configure_budget_manager(self.services.budget_manager)
        self.contract_validator = ContractValidator()
        self.registry = AgentRegistry(self.services); self.registry.load(CONFIG_DIR / "agents")
        self.authorization = AuthorizationService(self.store, self.registry)
        for item in self.registry.list_agents():
            contract = self.registry.get_contract(item["agent_id"])
            self.authorization.ensure_principal_for_contract(contract)
            errors = self.authorization.validate_contract_permissions(contract)
            if errors:
                raise RuntimeInvocationError(RuntimeErrorCode.CONTRACT_INVALID, "; ".join(errors))
        self.mcp = GovernedMCPService(self.store, self.registry, self.authorization)
        self.mcp.load_config(CONFIG_DIR)
        self.primitives = PrimitiveCatalog(CONFIG_DIR, BANKING_ROOT / "prompts", self.registry)
        self.hooks = HookDispatcher(self.store, self.primitives)
        guardrail_config = load_named_config(CONFIG_DIR, "guardrails.yaml", {}) or {}
        self.policy = BankPolicyEngine(self.registry, self.store, guardrail_config.get("business_guardrails", {}))
        self.kill_switch = BankKillSwitchService(self.registry, self.store)
        degradation_rules = load_named_config(CONFIG_DIR, "degradation_rules.yaml", {}) or {}
        self.degradation = DegradationMonitor(self.registry, self.store, self.kill_switch, degradation_rules)
        self.services.policy = self.policy
        action_policies = load_named_config(CONFIG_DIR, "banking_action_policies.yaml", {}) or {}
        
        # Initialize LLM Risk Judge lazily without failing if not configured
        from banking_agents.policy.llm_risk_judge import LLMRiskJudge
        self.llm_judge = LLMRiskJudge(CONFIG_DIR, BANKING_ROOT / "prompts")
        
        self.tool_authorization = ToolAuthorizationService(
            self.registry, self.store, self.primitives, action_policies, self.policy.guardrails, self.llm_judge, self.authorization
        )
        self.services.tool_authorization = self.tool_authorization

    async def invoke(self, agent_id, payload, action="invoke", trace_id=None, *, trace_name=None, request_source="generic_invoke"):
        request = InvocationRequest(
            agent_id=agent_id,
            action=action,
            payload=payload or {},
            session_id=(payload or {}).get("session_id") or (payload or {}).get("user_id"),
            correlation_id=trace_id,
            requested_tools=(payload or {}).get("requested_tools"),
            metadata={"trace_name": trace_name, "request_source": request_source},
        )
        result = await self.invoke_result(request)
        return result.to_legacy_response()

    async def invoke_result(self, request: InvocationRequest | dict):
        request = request if isinstance(request, InvocationRequest) else InvocationRequest(**request)
        invocation_id = str(uuid.uuid4())
        trace_id = request.correlation_id or str(uuid.uuid4())
        started = perf_counter()
        start_timestamp = datetime.now(timezone.utc).isoformat()
        policy_decisions, guardrail_results, evaluator_results = [], [], []
        contract, context = None, None
        agent_id = request.agent_id
        run_started = False
        adapter_invoked = False
        output = None
        tracer = self.services.tracer
        principal_id = request.invoking_user_id or request.invoking_agent_id or "anonymous"
        request_source = request.metadata.get("request_source", "generic_invoke")
        trace_name = request.metadata.get("trace_name")
        run_name = trace_name or f"Agent Control Plane Run - {agent_id}"

        self._phase(invocation_id, trace_id, agent_id, "accept_invocation_request", "started", {"action": request.action, "request_source": request_source})
        self.store.start_invocation(invocation_id, trace_id, agent_id, principal_id, request.action, "unknown", start_timestamp, request.model_dump())
        try:
            contract = self._resolve_contract(agent_id, invocation_id, trace_id)
            status_before = contract.status.value
            authorization = self._ensure_authorization_service()
            subject_agent_id = request.invoking_agent_id or contract.agent_id
            principal_id = authorization.principal_id_for_agent(subject_agent_id)
            context = InvocationContext(
                invocation_id=invocation_id,
                trace_id=trace_id,
                contract_version=contract.version,
                agent_principal_id=principal_id,
                resolved_permissions={},
                lifecycle_status=status_before,
                runtime_type=contract.execution_mode,
                adapter_type=contract.adapter_type,
                model_policy=contract.model_preferences or {},
                budget_policy=self._budget_policy(contract, request),
                start_timestamp=start_timestamp,
            )
            self.store.start_invocation(invocation_id, trace_id, agent_id, principal_id, request.action, status_before, start_timestamp, request.model_dump())
            self._phase(invocation_id, trace_id, agent_id, "resolve_agent_contract", "completed", contract_summary(contract))
            self._validate_contract(contract, invocation_id, trace_id)
            adapter = self._resolve_adapter(agent_id, invocation_id, trace_id)
            validated = self._validate_input(adapter, request.payload, invocation_id, trace_id)
            self._verify_lifecycle(contract, invocation_id, trace_id)
            self._phase(invocation_id, trace_id, agent_id, "resolve_security_context", "completed", {"principal_id": principal_id, "subject_agent_id": subject_agent_id})
            self._authorize_resource(
                contract, request, invocation_id, trace_id, "agent", contract.agent_id, request.action,
                {"lifecycle_status": status_before, "human_override": request.payload.get("human_override", {}), "required_human_approval_for": contract.policy_permissions.get("requires_human_approval_for", [])},
            )
            self._authorize_model_if_configured(contract, request, invocation_id, trace_id, status_before)

            metadata = {
                **contract_summary(contract), "trace_id": trace_id, "invocation_id": invocation_id,
                "status_before": status_before, "status_after": status_before,
                "request_source": request_source, "environment": os.getenv("APP_ENV", "local_demo"),
                "client": "Bandhan Bank", "session_id": request.session_id or validated.get("session_id"),
                "backend_version": os.getenv("BACKEND_VERSION", "local"),
            }
            tags = ["agent_harness", "control_plane", "banking", agent_id, contract.business_function, contract.adapter_type]
            if request_source == "demo_endpoint": tags.append("demo")

            with tracer.trace(run_name, inputs=safe_summary(validated), metadata=metadata, tags=tags) as root:
                try:
                    self.hooks.emit("pre_invoke", {"trace_id": trace_id, "agent_id": agent_id, "request_source": request_source})
                    with tracer.span("load_agent_contract", inputs={"agent_id": agent_id}, metadata={"trace_id": trace_id, "invocation_id": invocation_id}) as span:
                        span.set_output(contract_summary(contract))
                    with tracer.span("check_agent_status", inputs={"agent_id": agent_id}) as span:
                        span.set_output({"status": contract.status.value})

                    policy = self._evaluate_policy(contract, request, validated, trace_id, invocation_id, tracer)
                    policy_decisions.append(policy.to_dict())
                    guardrail_results.extend(policy.guardrail_events)
                    if policy.decision != "ALLOW":
                        result = self._blocked_result(request, context, policy, invocation_id, trace_id, started, policy_decisions, guardrail_results)
                        root.set_output(result.model_dump())
                        return result

                    for tool_id in request.requested_tools or []:
                        tool_decision = self._authorize_requested_tool(contract, request, tool_id, trace_id, invocation_id)
                        policy_decisions.append(tool_decision)
                        guardrail_results.extend(tool_decision.get("guardrails_evaluated", []))
                        if tool_decision.get("decision") != "ALLOW":
                            raise RuntimeInvocationError(RuntimeErrorCode.PERMISSION_DENIED, tool_decision.get("reason", "Tool authorization denied"))

                    self._enforce_budget(context, validated, invocation_id, trace_id)
                    if contract.status.value == "review" and validated.get("human_override", {}).get("approved"):
                        self.store.add_event("HUMAN_OVERRIDE_USED", trace_id, agent_id, {"approved_by": validated["human_override"].get("approved_by"), "reason": validated["human_override"].get("reason"), "status": "review"})

                    self._phase(invocation_id, trace_id, agent_id, "create_trace_and_audit_context", "completed", {"run_name": run_name})
                    self._phase(invocation_id, trace_id, agent_id, "invoke_adapter", "started", {"adapter_type": contract.adapter_type})
                    with tracer.span("audit_persist", inputs={"event": "RUN_STARTED", "trace_id": trace_id}) as span:
                        self.store.start_run(trace_id, agent_id, validated, start_timestamp)
                        run_started = True
                        self.services.trace_provider.emit("RUN_STARTED", trace_id, agent_id, {"trace_id": trace_id, "invocation_id": invocation_id})
                        span.set_output({"stored": True, "trace_id": trace_id})

                    with tracer.span("adapter_invoke", inputs={"adapter_type": contract.adapter_type, "payload": safe_summary(validated)}, metadata={"entrypoint": contract.entrypoint}) as span:
                        with usage_context(trace_id=trace_id, run_id=trace_id, agent_id=agent_id, agent_name=contract.name, business_function=contract.business_function, invocation_id=invocation_id, budget_policy=context.budget_policy, model_policy=contract.effective_contract()["model_policy"], risk_tier=contract.risk_tier):
                            auth_token = set_current_authorization_context({
                                "authorization": self._ensure_authorization_service(),
                                "agent_id": request.invoking_agent_id or agent_id,
                                "principal_id": principal_id,
                                "invocation_id": invocation_id,
                                "trace_id": trace_id,
                                "context": {
                                    "lifecycle_status": contract.status.value,
                                    "human_override": validated.get("human_override", {}),
                                    "required_human_approval_for": contract.policy_permissions.get("requires_human_approval_for", []),
                                },
                            })
                            try:
                                output = await adapter.invoke_async(validated, trace_id)
                            finally:
                                reset_current_authorization_context(auth_token)
                        adapter_invoked = True
                        span.set_output({"success": True, "response": safe_summary(output)})
                    self._phase(invocation_id, trace_id, agent_id, "invoke_adapter", "completed", {"adapter_invoked": True})

                    post_policy = self._output_guardrails(contract, output, trace_id, invocation_id, tracer)
                    policy_decisions.append(post_policy.to_dict())
                    guardrail_results.extend(post_policy.guardrail_events)
                    if post_policy.decision == "BLOCK":
                        raise RuntimeInvocationError(RuntimeErrorCode.OUTPUT_INVALID, post_policy.reason)

                    evaluator_results = self._collect_evaluators(output, trace_id, agent_id, invocation_id)
                    duration_ms = int((perf_counter() - started) * 1000)
                    usage = self._record_usage_if_needed(contract, trace_id, invocation_id, duration_ms, "success")
                    self.hooks.emit("on_cost_record", {"trace_id": trace_id, "agent_id": agent_id})
                    confidence = output.get("confidence") if isinstance(output, dict) else None
                    with tracer.span("audit_persist", inputs={"event": "RUN_COMPLETED", "trace_id": trace_id}) as span:
                        self.store.finish_run(trace_id, "completed", datetime.now(timezone.utc).isoformat(), duration_ms, output, confidence=confidence)
                        self.registry.record_run(agent_id, True, duration_ms, confidence)
                        self.services.trace_provider.emit("RUN_COMPLETED", trace_id, agent_id, {"latency_ms": duration_ms})
                        span.set_output({"stored": True, "status": "completed"})
                    with tracer.span("degradation_evaluation", inputs={"agent_id": agent_id, "latency_ms": duration_ms, "confidence": confidence}) as span:
                        degradation = self.degradation.evaluate(agent_id, trace_id)
                        span.set_output({"status_change": degradation or "no_change"})
                    with tracer.span("kill_switch_evaluation", inputs={"critical_events": []}) as span:
                        span.set_output({"action": "no_action"})
                    self.hooks.emit("post_invoke", {"trace_id": trace_id, "agent_id": agent_id, "status": "completed"})
                    result = InvocationResult(
                        status="completed", output=output, policy_decisions=policy_decisions,
                        guardrail_results=guardrail_results, evaluator_results=evaluator_results,
                        usage=usage, audit_reference=invocation_id, trace_id=trace_id,
                        duration_ms=duration_ms, invocation_id=invocation_id, agent_id=agent_id,
                        context=context,
                    )
                    self._finish_invocation(result, None)
                    root.add_metadata({"status_after": self.registry.get_contract(agent_id).status.value})
                    root.set_output(result.model_dump())
                    return result
                except Exception as exc:
                    error = self._classify_exception(exc)
                    error.pop("_original", None)
                    duration_ms = int((perf_counter() - started) * 1000)
                    usage = self._record_usage_if_needed(contract, trace_id, invocation_id, duration_ms, "failed") if contract else []
                    if run_started:
                        with tracer.span("audit_persist", inputs={"event": "RUN_FAILED", "trace_id": trace_id}) as span:
                            self.store.finish_run(trace_id, "failed", datetime.now(timezone.utc).isoformat(), duration_ms, error=error["message"])
                            self.registry.record_run(agent_id, False, duration_ms)
                            self.services.trace_provider.emit("RUN_FAILED", trace_id, agent_id, {"error": error["message"], "error_code": error["code"]})
                            span.set_output({"stored": True, "status": "failed"})
                        with tracer.span("degradation_evaluation", inputs={"agent_id": agent_id, "failed": True}) as span:
                            span.set_output({"status_change": self.degradation.evaluate(agent_id, trace_id) or "no_change"})
                    result = InvocationResult(
                        status="blocked" if error["code"] in {RuntimeErrorCode.AGENT_NOT_ACTIVE.value, RuntimeErrorCode.PERMISSION_DENIED.value, RuntimeErrorCode.GUARDRAIL_BLOCKED.value, RuntimeErrorCode.BUDGET_EXCEEDED.value} else "failed",
                        output=None, policy_decisions=policy_decisions, guardrail_results=guardrail_results,
                        evaluator_results=evaluator_results, usage=usage, audit_reference=invocation_id,
                        trace_id=trace_id, duration_ms=duration_ms, error=error,
                        invocation_id=invocation_id, agent_id=agent_id, context=context,
                    )
                    self._phase(invocation_id, trace_id, agent_id, "runtime_error", "failed", error)
                    self._finish_invocation(result, error["code"])
                    root.add_metadata({"status_after": self.registry.get_contract(agent_id).status.value if self.registry.exists(agent_id) else "unknown"})
                    root.set_output(result.model_dump())
                    logger.exception("Control-plane invocation failed: %s", error["code"])
                    return result
        except Exception as exc:
            error = self._classify_exception(exc)
            error.pop("_original", None)
            duration_ms = int((perf_counter() - started) * 1000)
            result = InvocationResult(
                status="blocked" if error["code"] in {RuntimeErrorCode.AGENT_NOT_FOUND.value, RuntimeErrorCode.CONTRACT_INVALID.value, RuntimeErrorCode.INPUT_SCHEMA_INVALID.value, RuntimeErrorCode.AGENT_NOT_ACTIVE.value, RuntimeErrorCode.BUDGET_EXCEEDED.value} else "failed",
                output=None, policy_decisions=policy_decisions, guardrail_results=guardrail_results,
                evaluator_results=evaluator_results, usage=[], audit_reference=invocation_id,
                trace_id=trace_id, duration_ms=duration_ms, error=error,
                invocation_id=invocation_id, agent_id=agent_id, context=context,
            )
            self._phase(invocation_id, trace_id, agent_id, "runtime_error", "failed", error)
            self._finish_invocation(result, error["code"])
            logger.exception("Control-plane invocation failed before adapter invocation: %s", error["code"])
            return result

    def _resolve_contract(self, agent_id, invocation_id, trace_id):
        try:
            return self.registry.get_contract(agent_id)
        except AgentNotFoundError as exc:
            self._phase(invocation_id, trace_id, agent_id, "resolve_agent_contract", "failed", {"error_code": RuntimeErrorCode.AGENT_NOT_FOUND.value})
            raise RuntimeInvocationError(RuntimeErrorCode.AGENT_NOT_FOUND, str(exc), original=exc) from exc

    def _validate_contract(self, contract, invocation_id, trace_id):
        try:
            self.contract_validator.validate_or_raise(contract)
            self._phase(invocation_id, trace_id, contract.agent_id, "validate_contract", "completed", {"version": contract.version})
        except ContractValidationError as exc:
            self._phase(invocation_id, trace_id, contract.agent_id, "validate_contract", "failed", {"error": str(exc)})
            raise RuntimeInvocationError(RuntimeErrorCode.CONTRACT_INVALID, str(exc), original=exc) from exc

    def _resolve_adapter(self, agent_id, invocation_id, trace_id):
        try:
            adapter = self.registry.get_adapter(agent_id)
            self._phase(invocation_id, trace_id, agent_id, "resolve_runtime_and_adapter", "completed", {"adapter_type": adapter.manifest.adapter_type})
            return adapter
        except Exception as exc:
            self._phase(invocation_id, trace_id, agent_id, "resolve_runtime_and_adapter", "failed", {"error": str(exc)})
            raise RuntimeInvocationError(RuntimeErrorCode.CONTRACT_INVALID, str(exc), original=exc) from exc

    def _validate_input(self, adapter, payload, invocation_id, trace_id):
        try:
            validated = adapter.validate_input(payload)
            self._phase(invocation_id, trace_id, adapter.manifest.agent_id, "validate_input_schema", "completed", {"required": adapter.manifest.input_schema.get("required", [])})
            return validated
        except ValueError as exc:
            self._phase(invocation_id, trace_id, adapter.manifest.agent_id, "validate_input_schema", "failed", {"error": str(exc)})
            raise RuntimeInvocationError(RuntimeErrorCode.INPUT_SCHEMA_INVALID, str(exc), original=exc) from exc

    def _verify_lifecycle(self, contract, invocation_id, trace_id):
        if contract.status.value in {"disabled", "quarantined"}:
            self._phase(invocation_id, trace_id, contract.agent_id, "verify_lifecycle_status", "failed", {"status": contract.status.value})
            raise RuntimeInvocationError(RuntimeErrorCode.AGENT_NOT_ACTIVE, f"Agent status is {contract.status.value}")
        self._phase(invocation_id, trace_id, contract.agent_id, "verify_lifecycle_status", "completed", {"status": contract.status.value})

    def _evaluate_policy(self, contract, request, payload, trace_id, invocation_id, tracer):
        policy_context = {**payload, "input_text": str(safe_summary(payload))}
        with tracer.span("pre_policy_check", inputs={"agent_id": contract.agent_id, "action": request.action, "data_scope": payload.get("data_scope")}) as span:
            policy = self.policy.check(contract.agent_id, request.action, policy_context, trace_id)
            span.set_output({"decision": policy.decision, "reason": policy.reason, "human_approval_required": policy.human_approval_required})
        self._phase(invocation_id, trace_id, contract.agent_id, "evaluate_action_permissions", "completed", {"decision": policy.decision, "reason": policy.reason})
        self._phase(invocation_id, trace_id, contract.agent_id, "run_input_guardrails", "completed", {"guardrail_count": len(policy.guardrail_events)})
        return policy

    def _authorize_requested_tool(self, contract, request, tool_id, trace_id, invocation_id):
        from banking_agents.policy.tool_authorization import ToolInvocationRequest
        body = ToolInvocationRequest(
            agent_id=contract.agent_id,
            tool_id=tool_id,
            action=request.action,
            data_scope=(request.payload or {}).get("data_scope", ""),
            payload_summary=str(safe_summary(request.payload)),
            trace_id=trace_id,
            requested_by=request.invoking_user_id,
            source=request.metadata.get("request_source", "runtime"),
            human_override=(request.payload or {}).get("human_override", {}),
        )
        self._authorize_resource(
            contract,
            request,
            invocation_id,
            trace_id,
            "tool",
            tool_id,
            "invoke",
            {
                "data_scope": (request.payload or {}).get("data_scope", ""),
                "lifecycle_status": contract.status.value,
                "human_override": (request.payload or {}).get("human_override", {}),
                "required_human_approval_for": contract.policy_permissions.get("requires_human_approval_for", []),
            },
        )
        response = self.tool_authorization.authorize(body).to_dict()
        self._phase(invocation_id, trace_id, contract.agent_id, "authorize_requested_tool", "completed", {"tool_id": tool_id, "decision": response["decision"]})
        return response

    def _budget_policy(self, contract, request):
        policy = {}
        for source in (contract.budget_policy, contract.policy_permissions.get("budget_policy", {}), request.metadata.get("budget_policy", {})):
            if isinstance(source, dict):
                policy.update(source)
        return policy

    def _enforce_budget(self, context, payload, invocation_id, trace_id):
        estimated = self.services.usage_meter.estimate_tokens(str(safe_summary(payload)))
        self._phase(invocation_id, trace_id, context.agent_principal_id, "enforce_model_token_policy", "completed", {"estimated_input_tokens": estimated, "budget_policy": context.budget_policy, "model_policy": context.model_policy})

    def _output_guardrails(self, contract, output, trace_id, invocation_id, tracer):
        with tracer.span("post_guardrail_check", inputs={"output": safe_summary(output)}) as span:
            post_policy = self.policy.check(contract.agent_id, "output_review", {"output_text": str(safe_summary(output))}, trace_id)
            span.set_output({"decision": post_policy.decision, "reason": post_policy.reason, "guardrails": post_policy.guardrail_events})
        self._phase(invocation_id, trace_id, contract.agent_id, "run_output_guardrails", "completed", {"decision": post_policy.decision, "guardrail_count": len(post_policy.guardrail_events)})
        return post_policy

    def _collect_evaluators(self, output, trace_id, agent_id, invocation_id):
        results = []
        if isinstance(output, dict) and isinstance(output.get("rag_evaluation"), dict):
            results.append(output["rag_evaluation"])
        for row in self.store.list_rag_evaluations(trace_id=trace_id, limit=20):
            results.append(row)
        self._phase(invocation_id, trace_id, agent_id, "run_relevant_evaluators", "completed", {"evaluator_count": len(results)})
        return results

    def _record_usage_if_needed(self, contract, trace_id, invocation_id, latency_ms, status):
        rows = self.store.query("SELECT * FROM usage_events WHERE trace_id=? ORDER BY created_at DESC", (trace_id,))
        if not rows:
            model_policy = contract.effective_contract()["model_policy"]
            provider = model_policy.get("provider") or ("external" if contract.adapter_type in {"rest_api", "external_webhook"} else "unknown")
            model = model_policy.get("deployment") or "unknown"
            self.services.usage_meter.record_usage({"trace_id": trace_id, "run_id": trace_id, "agent_id": contract.agent_id, "agent_name": contract.name, "business_function": contract.business_function, "provider": provider, "model": model, "usage_source": "unknown", "estimated_method": "unavailable", "latency_ms": latency_ms, "status": status, "metadata": {"adapter_type": contract.adapter_type}})
            rows = self.store.query("SELECT * FROM usage_events WHERE trace_id=? ORDER BY created_at DESC", (trace_id,))
        self._phase(invocation_id, trace_id, contract.agent_id, "record_usage", "completed", {"usage_event_count": len(rows), "status": status})
        return rows

    def _blocked_result(self, request, context, policy, invocation_id, trace_id, started, policy_decisions, guardrail_results):
        injection = any(event["guardrail_id"] == "GRD-INJECT-001" for event in policy.guardrail_events)
        if not injection:
            self.registry.record_block(request.agent_id)
        actions = [result for event in policy.guardrail_events if (result := self.kill_switch.apply_guardrail(request.agent_id, event))]
        self._phase(invocation_id, trace_id, request.agent_id, "kill_switch_evaluation", "completed", {"action": actions or "no_action"})
        degradation = None if injection else self.degradation.evaluate(request.agent_id, trace_id)
        self._phase(invocation_id, trace_id, request.agent_id, "degradation_evaluation", "completed", {"status_change": degradation or "no_change"})
        status = self.registry.get_contract(request.agent_id).status.value
        reason = "agent_quarantined" if status == "quarantined" else "agent_disabled" if status == "disabled" else policy.reason
        error_code = RuntimeErrorCode.GUARDRAIL_BLOCKED.value if policy.guardrail_events else RuntimeErrorCode.PERMISSION_DENIED.value
        if status in {"disabled", "quarantined"}:
            error_code = RuntimeErrorCode.AGENT_NOT_ACTIVE.value
        error = {"code": error_code, "message": reason}
        evidence = {"decision": policy.decision, "reason": reason, "agent_id": request.agent_id, "status": status, "adapter_invoked": False, "trace_id": trace_id, "policy_decision": policy.to_dict(), "invocation_id": invocation_id}
        self.store.add_event("INVOCATION_BLOCKED", trace_id, request.agent_id, evidence)
        self.hooks.emit("on_policy_block", {**evidence, "reason": policy.reason})
        duration_ms = int((perf_counter() - started) * 1000)
        result = InvocationResult(
            status="blocked", output=None, policy_decisions=policy_decisions,
            guardrail_results=guardrail_results, evaluator_results=[], usage=[],
            audit_reference=invocation_id, trace_id=trace_id, duration_ms=duration_ms,
            error=error, invocation_id=invocation_id, agent_id=request.agent_id, context=context,
        )
        self._finish_invocation(result, error_code)
        return result

    def _classify_exception(self, exc):
        if isinstance(exc, PermissionDenied):
            return {"code": RuntimeErrorCode.PERMISSION_DENIED.value, "message": exc.decision.reason_code, "_original": exc}
        if isinstance(exc, RuntimeInvocationError):
            return {"code": exc.code.value, "message": exc.message, "_original": exc.original}
        if isinstance(exc, AdapterTimeoutError):
            return {"code": RuntimeErrorCode.AGENT_TIMEOUT.value, "message": str(exc), "_original": exc}
        if isinstance(exc, AdapterError):
            return {"code": RuntimeErrorCode.ADAPTER_FAILURE.value, "message": str(exc), "_original": exc}
        if isinstance(exc, PermissionError):
            return {"code": RuntimeErrorCode.PERMISSION_DENIED.value, "message": str(exc), "_original": exc}
        return {"code": RuntimeErrorCode.INTERNAL_RUNTIME_ERROR.value, "message": str(exc), "_original": exc}

    def _phase(self, invocation_id, trace_id, agent_id, phase, status, payload=None):
        self.store.add_runtime_phase_event(invocation_id, trace_id, agent_id, phase, status, payload or {})

    def _finish_invocation(self, result, error_code):
        decision = result.status
        self.store.finish_invocation(result.invocation_id, decision, datetime.now(timezone.utc).isoformat(), result.duration_ms, error_code, result.model_dump())
        self._phase(result.invocation_id, result.trace_id, result.agent_id, "persist_observability_events", "completed", {"decision": decision})
        self._phase(result.invocation_id, result.trace_id, result.agent_id, "persist_audit_evidence", "completed", {"decision": decision, "error_code": error_code})

    def _ensure_authorization_service(self):
        service = getattr(self, "authorization", None)
        if service is None:
            service = AuthorizationService(self.store, self.registry)
            for agent_id in getattr(self.registry, "contracts", getattr(self.registry, "_contracts", {})):
                service.ensure_principal_for_contract(self.registry.get_contract(agent_id))
            self.authorization = service
        return service

    def _authorize_resource(self, contract, request, invocation_id, trace_id, resource_type, resource_id, action, context=None):
        service = self._ensure_authorization_service()
        subject_agent_id = request.invoking_agent_id or contract.agent_id
        principal_id = service.principal_id_for_agent(subject_agent_id)
        decision = service.enforce(AuthorizationRequest(
            agent_id=subject_agent_id,
            principal_id=principal_id,
            invocation_id=invocation_id,
            trace_id=trace_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            context=context or {},
        ))
        self._phase(invocation_id, trace_id, contract.agent_id, "authorize_resource", "completed", {"resource_type": resource_type, "resource_id": resource_id, "action": action, "decision": decision.decision})
        return decision

    def _authorize_model_if_configured(self, contract, request, invocation_id, trace_id, lifecycle_status):
        deployment = (contract.model_preferences or {}).get("deployment") or (contract.model_preferences or {}).get("primary") or (contract.model_preferences or {}).get("llm_model")
        if not deployment:
            return None
        return self._authorize_resource(
            contract,
            request,
            invocation_id,
            trace_id,
            "model",
            deployment,
            "invoke",
            {"lifecycle_status": lifecycle_status, "human_override": request.payload.get("human_override", {}), "approval_state": "not_required"},
        )


def _register_existing_runtime_agents():
    definitions = {
        "orchestrator": ("Orchestrator Agent", "reusable", False), "classify_intent": ("Intent Classifier", "reusable", False), "decompose_task": ("Task Decomposer", "reusable", False),
        "consult_policy_expert": ("Policy RAG Agent", "domain", True), "consult_loan_expert": ("Loan Eligibility Agent", "domain", True),
    }
    for name, (display, kind, killable) in definitions.items(): legacy_registry.register_runtime_agent(name, {"display_name": display, "type": kind, "model": "configured-by-banking-app", "description": display, "killable": killable, "enabled": True})


_register_existing_runtime_agents()
control_plane = ControlPlaneRuntime()
