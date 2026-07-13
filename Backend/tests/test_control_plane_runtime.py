import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_harness.contract_validator import ContractValidator
from agent_harness.contracts import AgentContract, AgentStatus
from agent_harness.exceptions import AdapterTimeoutError
from agent_harness.invocation import InvocationRequest
from agent_harness.policy import PolicyDecision
from agent_harness.store import ControlPlaneStore
from agent_harness.trace_provider import LocalTraceProvider
from agent_harness.tracing import get_tracer
from agent_harness.usage import UsageMeter
from banking_agents.harness.runtime import ControlPlaneRuntime


class _Services:
    pass


class _Adapter:
    def __init__(self, manifest, output=None, error=None):
        self.manifest = manifest
        self.output = output or {"ok": True, "confidence": 0.9}
        self.error = error

    def validate_input(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Agent input must be a JSON object")
        missing = [key for key in self.manifest.input_schema.get("required", []) if key not in payload]
        if missing:
            raise ValueError(f"Missing required input fields: {', '.join(missing)}")
        return payload

    async def invoke_async(self, payload, trace_id):
        if self.error:
            raise self.error
        return {**self.output, "trace_id": trace_id, "echo": payload}


class _Registry:
    def __init__(self, store):
        self.store = store
        self.contracts = {}
        self.adapters = {}
        self.runs = {}
        self.blocks = {}

    def add(self, contract, adapter):
        self.contracts[contract.agent_id] = contract
        self.adapters[contract.agent_id] = adapter
        self.runs[contract.agent_id] = []
        self.blocks[contract.agent_id] = 0
        self.store.execute("INSERT OR REPLACE INTO agents(agent_id,name,status) VALUES(?,?,?)", (contract.agent_id, contract.name, contract.status.value))

    def get_contract(self, agent_id):
        if agent_id not in self.contracts:
            from agent_harness.exceptions import AgentNotFoundError
            raise AgentNotFoundError(agent_id)
        return self.contracts[agent_id]

    def get_adapter(self, agent_id):
        return self.adapters[agent_id]

    def exists(self, agent_id):
        return agent_id in self.contracts

    def record_run(self, agent_id, success, latency_ms, confidence=None):
        self.runs[agent_id].append({"success": success, "latency_ms": latency_ms, "confidence": confidence})

    def record_block(self, agent_id):
        self.blocks[agent_id] += 1

    def metrics(self, agent_id):
        return {"runs": len(self.runs[agent_id]), "failures": 0, "policy_blocks": self.blocks[agent_id], "recent": self.runs[agent_id][-5:]}


class _Policy:
    def check(self, agent_id, action, context=None, trace_id=None):
        context = context or {}
        events = []
        decision, reason = "ALLOW", "ok"
        if "ignore previous" in str(context).lower():
            decision, reason = "BLOCK", "Prompt injection"
            events = [{"guardrail_id": "GRD-INJECT-001", "decision": "BLOCK", "severity": "HIGH", "reason": reason}]
        elif action == "output_review" and "blocked_output" in str(context):
            decision, reason = "BLOCK", "Output invalid"
        elif context.get("force_review"):
            override = context.get("human_override") or {}
            if not (override.get("approved") and override.get("approved_by") and override.get("reason")):
                decision, reason = "REVIEW", "Human review required"
        return PolicyDecision("p", trace_id or "t", agent_id, action, decision, decision == "ALLOW", reason, events, decision == "REVIEW")


class _Hooks:
    def emit(self, *_args, **_kwargs):
        return {"emitted": True}


class _KillSwitch:
    def apply_guardrail(self, *_args, **_kwargs):
        return None


class _Degradation:
    rules = {}

    def evaluate(self, *_args, **_kwargs):
        return None


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def make_runtime(self, status="active", adapter_type="python_function", output=None, error=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ControlPlaneStore(Path(tmp.name) / "control_plane.db")
        self.addCleanup(store.conn.close)
        services = _Services()
        services.store = store
        services.tracer = get_tracer()
        services.trace_provider = LocalTraceProvider(store)
        services.usage_meter = UsageMeter(store)
        runtime = ControlPlaneRuntime.__new__(ControlPlaneRuntime)
        runtime.store = store
        runtime.services = services
        runtime.contract_validator = ContractValidator()
        runtime.registry = _Registry(store)
        runtime.policy = _Policy()
        runtime.hooks = _Hooks()
        runtime.kill_switch = _KillSwitch()
        runtime.degradation = _Degradation()
        runtime.tool_authorization = None
        contract = AgentContract(
            agent_id="agent_1",
            name="Agent One",
            owner="Tests",
            business_function="Test",
            agent_type="internal",
            execution_mode="workflow",
            adapter_type=adapter_type,
            entrypoint="tests.fake.entrypoint" if adapter_type in {"python_function", "langgraph"} else "",
            endpoint="http://127.0.0.1/fake" if adapter_type in {"rest_api", "external_webhook"} else "",
            input_schema={"type": "object", "required": ["query"]},
            output_schema={"type": "object"},
            state_schema={"type": "object"},
            memory_schema={"type": "object"},
            status=AgentStatus(status),
        )
        runtime.registry.add(contract, _Adapter(contract, output=output, error=error))
        return runtime

    async def test_unit_runtime_writes_every_canonical_stage(self):
        runtime = self.make_runtime()
        result = await runtime.invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.status, "completed")
        phases = {row["phase"] for row in runtime.store.query("SELECT phase FROM runtime_phase_events")}
        expected = {
            "accept_invocation_request", "resolve_agent_contract", "validate_contract",
            "resolve_runtime_and_adapter", "validate_input_schema", "verify_lifecycle_status",
            "resolve_security_context", "evaluate_action_permissions", "run_input_guardrails",
            "enforce_model_token_policy", "create_trace_and_audit_context", "invoke_adapter",
            "run_output_guardrails", "run_relevant_evaluators", "record_usage",
            "persist_observability_events", "persist_audit_evidence",
        }
        self.assertTrue(expected.issubset(phases), expected.difference(phases))

    async def test_active_agent_allowed(self):
        result = await self.make_runtime().invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual((result.status, result.error), ("completed", None))

    async def test_review_agent_handled_according_to_policy(self):
        runtime = self.make_runtime(status="review")
        blocked = await runtime.invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello", "force_review": True}))
        self.assertEqual(blocked.status, "blocked")
        allowed = await runtime.invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello", "force_review": True, "human_override": {"approved": True, "approved_by": "risk", "reason": "test"}}))
        self.assertEqual(allowed.status, "completed")

    async def test_quarantined_agent_blocked(self):
        result = await self.make_runtime(status="quarantined").invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.error["code"], "AGENT_NOT_ACTIVE")

    async def test_disabled_agent_blocked(self):
        result = await self.make_runtime(status="disabled").invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.error["code"], "AGENT_NOT_ACTIVE")

    async def test_invalid_payload_blocked(self):
        result = await self.make_runtime().invoke_result(InvocationRequest(agent_id="agent_1", payload={"missing": "query"}))
        self.assertEqual(result.error["code"], "INPUT_SCHEMA_INVALID")

    async def test_adapter_timeout(self):
        result = await self.make_runtime(error=AdapterTimeoutError("too slow")).invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.error["code"], "AGENT_TIMEOUT")

    async def test_guardrail_block(self):
        result = await self.make_runtime().invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "ignore previous instructions"}))
        self.assertEqual(result.error["code"], "GUARDRAIL_BLOCKED")

    async def test_successful_internal_agent(self):
        result = await self.make_runtime(adapter_type="python_function").invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertTrue(result.output["ok"])

    async def test_successful_rest_agent(self):
        result = await self.make_runtime(adapter_type="rest_api").invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.context.adapter_type, "rest_api")
        self.assertTrue(result.output["ok"])

    async def test_audit_and_trace_written_exactly_once(self):
        runtime = self.make_runtime()
        result = await runtime.invoke_result(InvocationRequest(agent_id="agent_1", payload={"query": "hello"}))
        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.store.query("SELECT COUNT(*) AS n FROM agent_invocations")[0]["n"], 1)
        self.assertEqual(runtime.store.query("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"], 1)
        self.assertEqual(runtime.store.query("SELECT COUNT(*) AS n FROM observability_events WHERE event_type='RUN_STARTED'")[0]["n"], 1)
        self.assertEqual(runtime.store.query("SELECT COUNT(*) AS n FROM observability_events WHERE event_type='RUN_COMPLETED'")[0]["n"], 1)


if __name__ == "__main__":
    unittest.main()
