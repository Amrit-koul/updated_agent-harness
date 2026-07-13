import tempfile
import unittest
from pathlib import Path

from agent_harness.a2a import A2AGatewayService, A2ATask, TaskStatus
from agent_harness.contracts import AgentContract
from agent_harness.store import ControlPlaneStore


class FakeRegistry:
    def __init__(self, contract):
        self.contract = contract

    def list_agents(self):
        return [self.contract.to_dict()]

    def get_contract(self, agent_id):
        if agent_id != self.contract.agent_id:
            raise KeyError(agent_id)
        return self.contract


class FakeControlPlane:
    def __init__(self, contract, store):
        self.registry = FakeRegistry(contract)
        self.store = store


def contract():
    return AgentContract.from_dict({
        "agent_id": "policy_assistant_agent",
        "name": "Policy Assistant Agent",
        "owner": "Retail Banking Policy",
        "business_function": "Policy Assistance",
        "agent_type": "internal",
        "execution_mode": "workflow",
        "adapter_type": "python_function",
        "entrypoint": "tests.fake.invoke",
        "description": "Policy RAG agent exposed through A2A.",
        "input_schema": {"type": "object", "required": ["query"]},
        "output_schema": {"type": "object", "required": ["answer"]},
        "state_schema": {"type": "object"},
        "memory_schema": {"type": "object"},
        "skills": ["policy_retrieval"],
        "tools": ["document_search"],
        "policy_permissions": {"allowed_actions": ["invoke"], "allowed_data_scopes": ["policy_documents"]},
        "guardrails": ["prompt_injection", "pii_leakage"],
    })


class A2AGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ControlPlaneStore(Path(self.tmp.name) / "control_plane.db")
        self.control = FakeControlPlane(contract(), self.store)
        self.gateway = A2AGatewayService(self.control, public_base_url="http://bank.local")

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_agent_card_contains_bank_governance_metadata(self):
        card = self.gateway.agent_card("policy_assistant_agent")
        self.assertEqual(card["url"], "http://bank.local/api/v1/a2a/message/send")
        self.assertTrue(card["metadata"]["ey_bank_grade_controls"])
        self.assertIn("prompt_injection", card["metadata"]["guardrails"])
        self.assertEqual(card["skills"][0]["id"], "policy_assistant_agent.invoke")

    def test_gateway_card_lists_controls_and_agent_skills(self):
        card = self.gateway.gateway_card()
        self.assertEqual(card["provider"]["organization"], "EY")
        self.assertIn("kill_switch", card["metadata"]["banking_controls"])
        self.assertEqual(card["metadata"]["agent_count"], 1)
        self.assertEqual(card["skills"][0]["id"], "policy_assistant_agent.invoke")

    def test_a2a_task_persistence_round_trip(self):
        task = A2ATask(agent_id="policy_assistant_agent", context_id="ctx-1", status=TaskStatus(state="working"), metadata={"trace_id": "trace-1"})
        self.store.save_a2a_task(task.model_dump())
        restored = self.gateway.get_task(task.id)
        self.assertEqual(restored.id, task.id)
        self.assertEqual(restored.status.state, "working")
        self.assertEqual(self.store.list_a2a_tasks(agent_id="policy_assistant_agent")[0]["trace_id"], "trace-1")


if __name__ == "__main__":
    unittest.main()
