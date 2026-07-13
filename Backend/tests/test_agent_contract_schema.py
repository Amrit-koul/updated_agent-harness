import json
import tempfile
import unittest
from pathlib import Path

import yaml

from agent_harness.config_loader import load_agent_contracts
from agent_harness.contract_validator import ContractValidator
from agent_harness.contracts import AgentContract
from agent_harness.exceptions import ContractValidationError
from agent_harness.registry import AgentRegistry
from agent_harness.store import ControlPlaneStore


def _catalog():
    return {
        "skills": {"skill_a"},
        "tools": {"tool_a"},
        "memory_contracts": {"run"},
        "prompts": {"prompt_a"},
        "evaluators": {"eval_a"},
        "hooks": {"hook_a"},
        "mcp_servers": {"server_a"},
        "mcp_tools": {"server_a.tool_a"},
    }


def _complete_contract(**overrides):
    raw = {
        "identity": {
            "agent_id": "agent_a",
            "display_name": "Agent A",
            "owner": "Tests",
            "business_function": "Testing",
            "risk_tier": "medium",
            "agent_type": "internal",
            "contract_version": "2.0.0",
        },
        "runtime": {
            "runtime_type": "internal",
            "adapter_type": "python_function",
            "execution_mode": "workflow",
            "entrypoint": "tests.fake.invoke",
            "timeout_seconds": 10,
            "retry_policy": {"max_attempts": 1},
            "health_check": {"enabled": False},
        },
        "schemas": {
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "state_schema": {"type": "object"},
            "memory_schema": {"type": "object"},
        },
        "capabilities": {
            "skills": ["skill_a"],
            "tools": ["tool_a"],
            "memory_contracts": ["run"],
            "prompts": ["prompt_a:v1"],
            "evaluators": ["eval_a"],
            "hooks": ["hook_a"],
        },
        "model_policy": {"provider": "groq", "deployment": "llama-3.1-8b-instant"},
        "permissions": {
            "allowed_actions": ["invoke"],
            "allowed_tools": ["tool_a"],
            "allowed_data_scopes": ["scope_a"],
            "denied_actions": [],
            "human_approval_required_for": [],
            "mcp_servers": ["server_a"],
            "mcp_tools": ["server_a.tool_a"],
        },
        "budget_policy": {"period": "invocation", "max_input_tokens": 10, "max_output_tokens": 10, "max_total_tokens": 25, "warning_threshold_pct": 80, "enforcement_mode": "warn"},
        "observability": {"trace_enabled": True, "audit_enabled": True, "usage_enabled": True, "event_schema_version": "1.0"},
        "lifecycle": {"initial_status": "active", "degradation_policy": {"target_status": "review"}, "recovery_policy": {"target_status": "active"}},
    }
    raw.update(overrides)
    return raw


class AgentContractSchemaTests(unittest.TestCase):
    def validate(self, raw):
        contract = AgentContract.from_dict(raw)
        ContractValidator(_catalog()).validate_or_raise(contract)
        return contract

    def test_valid_complete_contract(self):
        contract = self.validate(_complete_contract())
        self.assertEqual(contract.contract_version, "2.0.0")
        self.assertEqual(contract.effective_contract()["permissions"]["mcp_servers"], ["server_a"])

    def test_valid_legacy_contract(self):
        contract = self.validate({
            "agent_id": "agent_a",
            "name": "Agent A",
            "owner": "Tests",
            "business_function": "Testing",
            "agent_type": "internal",
            "execution_mode": "workflow",
            "adapter_type": "python_function",
            "entrypoint": "tests.fake.invoke",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "state_schema": {"type": "object"},
            "memory_schema": {"type": "object"},
            "skills": ["skill_a"],
            "tools": ["tool_a"],
            "memory_contracts": ["run"],
            "prompts": ["prompt_a:v1"],
            "evaluators": ["eval_a"],
            "hooks": ["hook_a"],
            "policy_permissions": {"allowed_actions": ["invoke"], "allowed_tools": ["tool_a"], "allowed_data_scopes": [], "denied_actions": []},
        })
        self.assertEqual(contract.original_contract_version, "1.0.0")
        self.assertEqual(contract.contract_version, "2.0.0")

    def test_invalid_adapter(self):
        raw = _complete_contract()
        raw["runtime"]["adapter_type"] = "bad_adapter"
        with self.assertRaises(ValueError):
            AgentContract.from_dict(raw)

    def test_missing_referenced_tool(self):
        raw = _complete_contract()
        raw["capabilities"]["tools"] = ["missing_tool"]
        with self.assertRaisesRegex(ContractValidationError, "Unresolved tools"):
            self.validate(raw)

    def test_invalid_model_provider(self):
        raw = _complete_contract()
        raw["model_policy"]["provider"] = "not_a_provider"
        with self.assertRaisesRegex(ContractValidationError, "Unsupported model provider"):
            self.validate(raw)

    def test_invalid_budget_values(self):
        raw = _complete_contract()
        raw["budget_policy"]["warning_threshold_pct"] = 150
        with self.assertRaisesRegex(ContractValidationError, "warning_threshold_pct"):
            self.validate(raw)

    def test_conflicting_allow_deny_permissions(self):
        raw = _complete_contract()
        raw["permissions"]["denied_actions"] = ["invoke"]
        with self.assertRaisesRegex(ContractValidationError, "Conflicting allow/deny"):
            self.validate(raw)

    def test_invalid_mcp_reference(self):
        raw = _complete_contract()
        raw["permissions"]["mcp_tools"] = ["server_a.missing"]
        with self.assertRaisesRegex(ContractValidationError, "Unresolved mcp_tools"):
            self.validate(raw)

    def test_invalid_lifecycle_state(self):
        raw = _complete_contract()
        raw["lifecycle"]["recovery_policy"] = {"target_status": "resurrected"}
        with self.assertRaisesRegex(ContractValidationError, "recovery_policy"):
            self.validate(raw)

    def test_contract_round_trip_serialization(self):
        contract = self.validate(_complete_contract())
        restored = AgentContract.from_dict(json.loads(json.dumps(contract.to_dict())))
        self.assertEqual(restored.effective_contract(), contract.effective_contract())

    def test_registry_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            agents = config / "agents"
            prompts = root / "prompts"
            agents.mkdir(parents=True)
            prompts.mkdir()
            for name, key in (("skills.yaml", "skills"), ("tools.yaml", "tools"), ("memory_contracts.yaml", "memory_contracts"), ("evaluators.yaml", "evaluators"), ("hooks.yaml", "hooks")):
                (config / name).write_text(yaml.safe_dump({key: {next(iter(_catalog()[key])): {}}}), encoding="utf-8")
            (config / "mcp_servers.yaml").write_text(yaml.safe_dump({"mcp_servers": {"server_a": {}}}), encoding="utf-8")
            (config / "mcp_tools.yaml").write_text(yaml.safe_dump({"mcp_tools": {"server_a.tool_a": {}}}), encoding="utf-8")
            (prompts / "prompt.yaml").write_text("prompt_id: prompt_a\n", encoding="utf-8")
            (agents / "agent.yaml").write_text(yaml.safe_dump(_complete_contract()), encoding="utf-8")

            class Services:
                pass

            services = Services()
            services.store = ControlPlaneStore(root / "control_plane.db")
            first = AgentRegistry(services)
            self.assertEqual(first.load(agents), 1)
            first.set_status("agent_a", "review")

            second = AgentRegistry(services)
            self.assertEqual(second.load(agents), 1)
            self.assertEqual(second.get_contract("agent_a").status.value, "review")
            rows = services.store.query("SELECT contract_json FROM agent_contracts WHERE agent_id=?", ("agent_a",))
            self.assertIn("identity", json.loads(rows[0]["contract_json"]))
            services.store.conn.close()

    def test_unknown_property_rejected_by_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "bad.yaml").write_text(yaml.safe_dump({"agent_id": "a", "unknown": True}), encoding="utf-8")
            with self.assertRaises(ContractValidationError):
                load_agent_contracts(path)


if __name__ == "__main__":
    unittest.main()
