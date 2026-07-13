import asyncio
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from agent_harness.authorization import AuthorizationService
from agent_harness.contracts import AgentContract
from agent_harness.mcp_governance import (
    GovernedMCPService,
    MCPGovernanceError,
    MCPInvocationRequest,
)
from agent_harness.store import ControlPlaneStore


@dataclass
class FakeTool:
    name: str
    description: str
    inputSchema: dict
    outputSchema: dict | None = None


@dataclass
class FakeText:
    type: str
    text: str


@dataclass
class FakeResult:
    content: list
    isError: bool = False


class FakeTransport:
    def __init__(self):
        self.tools = [
            FakeTool("get_policy_metadata", "untrusted description", {"type": "object", "properties": {}}),
            FakeTool("get_mock_customer_summary", "customer summary", {"type": "object", "required": ["account_id"], "properties": {"account_id": {"type": "string"}}}),
        ]
        self.result = FakeResult([FakeText("text", '{"ok": true, "customer_id": "CUST-1"}')])
        self.timeout = False

    async def list_tools(self, _server):
        return self.tools

    async def call_tool(self, _server, _tool_name, _arguments):
        if self.timeout:
            raise asyncio.TimeoutError()
        return self.result


class FakeRegistry:
    def __init__(self, contract):
        self.contract = contract

    def get_contract(self, agent_id):
        if agent_id != self.contract.agent_id:
            raise KeyError(agent_id)
        return self.contract


class MCPGovernanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ControlPlaneStore(Path(self.tmp.name) / "control_plane.db")
        self.contract = AgentContract(
            agent_id="agent_mcp",
            name="MCP Agent",
            owner="Tests",
            business_function="Test",
            agent_type="internal",
            execution_mode="workflow",
            adapter_type="python_function",
            entrypoint="tests.fake",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            state_schema={"type": "object"},
            memory_schema={"type": "object"},
            policy_permissions={
                "allowed_actions": ["invoke"],
                "mcp_servers": ["demo_mcp"],
                "mcp_tools": ["demo_mcp.get_policy_metadata", "demo_mcp.get_mock_customer_summary"],
            },
        )
        self.registry = FakeRegistry(self.contract)
        self.auth = AuthorizationService(self.store, self.registry)
        self.auth.ensure_principal_for_contract(self.contract)
        self.transport = FakeTransport()
        self.service = GovernedMCPService(self.store, self.registry, self.auth, self.transport)
        self.service.register_server({
            "server_id": "demo_mcp",
            "name": "Demo MCP",
            "transport": "stdio",
            "command_reference": {"command": "{python}", "args": ["-m", "fake"]},
            "status": "registered",
            "owner": "Tests",
            "risk_tier": "high",
            "auth_type": "none",
        })

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    async def discover(self):
        return await self.service.refresh_server("demo_mcp")

    async def test_discovery_persists_schemas_and_health(self):
        result = await self.discover()
        self.assertEqual(result["server"]["status"], "active")
        tools = self.store.list_mcp_tools("demo_mcp")
        self.assertEqual({tool["tool_name"] for tool in tools}, {"get_policy_metadata", "get_mock_customer_summary"})
        self.assertTrue(all(tool["schema_hash"] for tool in tools))

    async def test_allowed_invocation_records_audit_and_trace(self):
        await self.discover()
        result = await self.service.invoke_tool(MCPInvocationRequest(
            agent_id="agent_mcp",
            server_id="demo_mcp",
            tool_name="get_policy_metadata",
            arguments={},
            trace_id="trace-mcp",
        ))
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.store.query("SELECT COUNT(*) AS n FROM mcp_invocations")[0]["n"], 1)
        self.assertEqual(self.store.query("SELECT COUNT(*) AS n FROM observability_events WHERE event_type='MCP_TOOL_INVOKED'")[0]["n"], 1)
        self.assertEqual(result["result"]["content"][0]["json"]["customer_id"], "[REDACTED]")

    async def test_undeclared_tool_blocked(self):
        await self.discover()
        with self.assertRaises(MCPGovernanceError) as ctx:
            await self.service.invoke_tool(MCPInvocationRequest("agent_mcp", "demo_mcp", "unknown", {}))
        self.assertEqual(ctx.exception.code, "MCP_TOOLSET_CHANGED")

    async def test_rbac_blocked_when_role_revoked(self):
        await self.discover()
        principal = self.auth.principal_id_for_agent("agent_mcp")
        self.store.execute("DELETE FROM principal_roles WHERE principal_id=?", (principal,))
        self.auth.invalidate(principal)
        with self.assertRaises(MCPGovernanceError) as ctx:
            await self.service.invoke_tool(MCPInvocationRequest("agent_mcp", "demo_mcp", "get_policy_metadata", {}))
        self.assertEqual(ctx.exception.code, "MCP_PERMISSION_DENIED")

    async def test_approval_required(self):
        await self.discover()
        with self.assertRaises(MCPGovernanceError) as ctx:
            await self.service.invoke_tool(MCPInvocationRequest("agent_mcp", "demo_mcp", "get_mock_customer_summary", {"account_id": "ACC-DEMO-01"}))
        self.assertEqual(ctx.exception.code, "MCP_PERMISSION_DENIED")
        allowed = await self.service.invoke_tool(MCPInvocationRequest(
            "agent_mcp", "demo_mcp", "get_mock_customer_summary", {"account_id": "ACC-DEMO-01"},
            human_override={"approved": True, "approved_by": "risk", "reason": "test approval"},
        ))
        self.assertEqual(allowed["status"], "success")

    async def test_schema_changed_requires_review_for_high_risk_tool(self):
        await self.discover()
        self.transport.tools[1] = FakeTool("get_mock_customer_summary", "changed", {"type": "object", "required": ["account_id", "reason"], "properties": {"account_id": {"type": "string"}, "reason": {"type": "string"}}})
        result = await self.discover()
        changed = next(tool for tool in result["tools"] if tool["tool_name"] == "get_mock_customer_summary")
        self.assertTrue(changed["review_required"])
        self.assertEqual(result["server"]["status"], "review")

    async def test_timeout_and_malformed_response(self):
        await self.discover()
        self.transport.timeout = True
        with self.assertRaises(MCPGovernanceError) as timeout_ctx:
            await self.service.invoke_tool(MCPInvocationRequest("agent_mcp", "demo_mcp", "get_policy_metadata", {}))
        self.assertEqual(timeout_ctx.exception.code, "MCP_TIMEOUT")
        self.transport.timeout = False
        self.transport.result = object()
        with self.assertRaises(MCPGovernanceError) as malformed_ctx:
            await self.service.invoke_tool(MCPInvocationRequest("agent_mcp", "demo_mcp", "get_policy_metadata", {}))
        self.assertEqual(malformed_ctx.exception.code, "MCP_MALFORMED_RESULT")

    async def test_arbitrary_url_rejected_by_contract_boundary(self):
        with self.assertRaises(MCPGovernanceError):
            self.service.register_server({"server_id": "bad", "name": "Bad", "transport": "websocket", "endpoint": "https://example.invalid"})

    async def test_direct_mcp_bypass_forbidden(self):
        with self.assertRaises(MCPGovernanceError) as ctx:
            self.service.direct_sdk_call_forbidden()
        self.assertEqual(ctx.exception.code, "MCP_DIRECT_BYPASS_PREVENTED")


if __name__ == "__main__":
    unittest.main()
