import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent_harness.authorization import AuthorizationRequest, AuthorizationService, authorize_current_resource
from agent_harness.store import ControlPlaneStore


class AuthorizationRbacTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ControlPlaneStore(Path(self.tmp.name) / "control_plane.db")
        self.auth = AuthorizationService(self.store)
        self.principal_id = "principal-test-agent"
        self.store.execute(
            "INSERT INTO agent_principals(principal_id,agent_id,principal_type,display_name,status) VALUES(?,?,?,?,?)",
            (self.principal_id, "agent_a", "agent", "Agent A", "active"),
        )
        self.store.execute("INSERT INTO roles(role_id,role_name,description,system_role) VALUES(?,?,?,?)", ("role_reader", "reader", "Read role", 0))
        self.store.execute("INSERT INTO permissions(permission_id,resource_type,action,description) VALUES(?,?,?,?)", ("data:policy_docs:read", "data:policy_docs", "read", "Read policy docs"))
        self.store.execute("INSERT INTO role_permissions(role_id,permission_id) VALUES(?,?)", ("role_reader", "data:policy_docs:read"))
        self.store.execute("INSERT INTO principal_roles(principal_id,role_id,scope_type,scope_value,valid_from,granted_by) VALUES(?,?,?,?,CURRENT_TIMESTAMP,?)", (self.principal_id, "role_reader", "data", "policy_docs", "test"))

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def request(self, **overrides):
        payload = {
            "agent_id": "agent_a",
            "principal_id": self.principal_id,
            "invocation_id": "inv-1",
            "action": "read",
            "resource_type": "data",
            "resource_id": "policy_docs",
            "context": {"lifecycle_status": "active", "approval_state": "not_required"},
        }
        payload.update(overrides)
        return AuthorizationRequest(**payload)

    def test_principal_active_allowed(self):
        decision = self.auth.evaluate(self.request())
        self.assertEqual(decision.decision, "ALLOW")

    def test_principal_inactive_denied(self):
        self.store.execute("UPDATE agent_principals SET status='disabled' WHERE principal_id=?", (self.principal_id,))
        self.auth.invalidate(self.principal_id)
        decision = self.auth.evaluate(self.request())
        self.assertEqual((decision.decision, decision.reason_code), ("DENY", "principal_inactive"))

    def test_missing_role_denied(self):
        self.store.execute("DELETE FROM principal_roles WHERE principal_id=?", (self.principal_id,))
        self.auth.invalidate(self.principal_id)
        decision = self.auth.evaluate(self.request())
        self.assertEqual((decision.decision, decision.reason_code), ("DENY", "missing_valid_role"))

    def test_expired_binding_denied(self):
        self.store.execute("UPDATE principal_roles SET valid_until='2000-01-01T00:00:00+00:00' WHERE principal_id=?", (self.principal_id,))
        self.auth.invalidate(self.principal_id)
        decision = self.auth.evaluate(self.request())
        self.assertEqual(decision.decision, "DENY")

    def test_scoped_data_permission(self):
        allowed = self.auth.evaluate(self.request(resource_id="policy_docs"))
        denied = self.auth.evaluate(self.request(resource_id="loan_records"))
        self.assertEqual(allowed.decision, "ALLOW")
        self.assertEqual(denied.decision, "DENY")

    def test_explicit_deny_wins(self):
        self.store.execute("INSERT INTO roles(role_id,role_name,description,system_role) VALUES(?,?,?,?)", ("role_deny", "deny", "Deny role", 0))
        self.store.execute("INSERT INTO permissions(permission_id,resource_type,action,description) VALUES(?,?,?,?)", ("deny:data:policy_docs:read", "data:policy_docs", "deny:read", "Deny read"))
        self.store.execute("INSERT INTO role_permissions(role_id,permission_id) VALUES(?,?)", ("role_deny", "deny:data:policy_docs:read"))
        self.store.execute("INSERT INTO principal_roles(principal_id,role_id,scope_type,scope_value,valid_from,granted_by) VALUES(?,?,?,?,CURRENT_TIMESTAMP,?)", (self.principal_id, "role_deny", "global", "*", "test"))
        self.auth.invalidate(self.principal_id)
        decision = self.auth.evaluate(self.request())
        self.assertEqual((decision.decision, decision.reason_code), ("DENY", "explicit_deny"))

    def test_contract_denied_actions_validate_but_still_deny(self):
        contract = SimpleNamespace(
            agent_id="collections_workflow_agent",
            name="Collections Workflow Agent",
            tools=[],
            model_preferences={},
            status=SimpleNamespace(value="active"),
            policy_permissions={
                "allowed_actions": ["invoke"],
                "allowed_data_scopes": [],
                "denied_actions": ["approve_waiver"],
            },
        )
        principal_id = self.auth.ensure_principal_for_contract(contract)

        self.assertEqual(self.auth.validate_contract_permissions(contract), [])
        decision = self.auth.evaluate(AuthorizationRequest(
            agent_id=contract.agent_id,
            principal_id=principal_id,
            invocation_id="inv-deny",
            action="approve_waiver",
            resource_type="agent",
            resource_id=contract.agent_id,
            context={"lifecycle_status": "active", "approval_state": "not_required"},
        ))
        self.assertEqual((decision.decision, decision.reason_code), ("DENY", "explicit_deny"))

    def test_role_revocation_invalidates_cache(self):
        self.assertEqual(self.auth.evaluate(self.request()).decision, "ALLOW")
        self.store.execute("DELETE FROM principal_roles WHERE principal_id=?", (self.principal_id,))
        self.auth.invalidate(self.principal_id)
        self.assertEqual(self.auth.evaluate(self.request()).decision, "DENY")

    def test_every_decision_audited(self):
        self.auth.evaluate(self.request(invocation_id="inv-audit"))
        rows = self.store.query("SELECT * FROM authorization_decisions WHERE invocation_id=?", ("inv-audit",))
        self.assertEqual(len(rows), 1)

    def test_agent_to_agent_call_requires_calling_agent_role(self):
        decision = self.auth.evaluate(self.request(action="invoke", resource_type="agent", resource_id="target_agent"))
        self.assertEqual(decision.decision, "DENY")
        self.store.execute("INSERT INTO permissions(permission_id,resource_type,action,description) VALUES(?,?,?,?)", ("agent:target_agent:invoke", "agent:target_agent", "invoke", "Invoke target"))
        self.store.execute("INSERT INTO role_permissions(role_id,permission_id) VALUES(?,?)", ("role_reader", "agent:target_agent:invoke"))
        self.auth.invalidate(self.principal_id)
        allowed = self.auth.evaluate(self.request(action="invoke", resource_type="agent", resource_id="target_agent"))
        self.assertEqual(allowed.decision, "ALLOW")

    def test_direct_resource_bypass_prevented_without_context(self):
        with self.assertRaises(PermissionError):
            authorize_current_resource("data", "policy_docs", "read")


if __name__ == "__main__":
    unittest.main()
