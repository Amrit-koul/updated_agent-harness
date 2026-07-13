"""A2A gateway service that keeps protocol traffic inside harness governance."""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from agent_harness.invocation import InvocationRequest

from .schemas import A2AMessage, A2APart, A2ASendMessageRequest, A2ATask, TaskStatus


class A2AGatewayService:
    """Maps A2A discovery and messages to governed Agent Harness invocations."""

    def __init__(self, control_plane, public_base_url: str | None = None):
        self.control_plane = control_plane
        base = public_base_url or os.getenv("PUBLIC_BASE_URL") or "http://localhost:8000"
        self.public_base_url = base.rstrip("/")

    def gateway_card(self) -> dict[str, Any]:
        agents = [self.agent_card(item["agent_id"]) for item in self.control_plane.registry.list_agents()]
        skills = []
        for card in agents:
            skills.extend(card.get("skills", []))
        return {
            "protocolVersion": "1.0",
            "name": "EY Agent Harness Banking Gateway",
            "description": "Production-grade A2A gateway exposing governed banking agents through Agent Harness controls.",
            "url": f"{self.public_base_url}/api/v1/a2a/rpc",
            "provider": {"organization": "EY", "url": "https://www.ey.com"},
            "version": "1.0.0",
            "documentationUrl": f"{self.public_base_url}/api/v1/a2a",
            "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": skills,
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer", "description": "Use enterprise-issued service token in production."}
            },
            "security": [{"bearer": []}],
            "metadata": {
                "banking_controls": ["agent_contracts", "rbac", "kill_switch", "guardrails", "audit", "observability", "usage_cost"],
                "agent_count": len(agents),
                "demo_client": "Bandhan Bank",
            },
        }

    def agent_card(self, agent_id: str) -> dict[str, Any]:
        contract = self.control_plane.registry.get_contract(agent_id)
        endpoint = f"{self.public_base_url}/api/v1/a2a/message/send"
        return {
            "protocolVersion": "1.0",
            "name": contract.name,
            "description": contract.description or f"Governed banking agent for {contract.business_function}.",
            "url": endpoint,
            "provider": {"organization": "EY", "url": "https://www.ey.com"},
            "version": contract.version,
            "documentationUrl": f"{self.public_base_url}/api/v1/control/agents/{agent_id}/contract",
            "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": [{
                "id": f"{contract.agent_id}.invoke",
                "name": f"Invoke {contract.name}",
                "description": contract.description or contract.business_function,
                "tags": [contract.business_function, contract.risk_tier, contract.adapter_type],
                "examples": self._examples_for(contract),
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["text/plain", "application/json"],
            }],
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer", "description": "Use bank service identity or EY demo bearer token."}
            },
            "security": [{"bearer": []}],
            "metadata": {
                "agent_id": contract.agent_id,
                "owner": contract.owner,
                "business_function": contract.business_function,
                "risk_tier": contract.risk_tier,
                "lifecycle_status": contract.status.value,
                "adapter_type": contract.adapter_type,
                "execution_mode": contract.execution_mode,
                "input_schema": contract.input_schema,
                "output_schema": contract.output_schema,
                "guardrails": contract.guardrails,
                "policy_permissions": contract.policy_permissions,
                "ey_bank_grade_controls": True,
            },
        }

    async def send_message(self, request: A2ASendMessageRequest) -> A2ATask:
        task_id = request.message.task_id or str(uuid4())
        context_id = request.context_id or request.message.context_id or task_id
        self._save_task(A2ATask(
            id=task_id,
            context_id=context_id,
            agent_id=request.agent_id,
            status=TaskStatus(state="working"),
            metadata={"source": "a2a", "invoking_agent_id": request.invoking_agent_id},
        ))
        payload = self._payload_from_message(request)
        result = await self.control_plane.invoke_result(InvocationRequest(
            agent_id=request.agent_id,
            action="invoke",
            payload=payload,
            invoking_agent_id=request.invoking_agent_id,
            correlation_id=request.metadata.get("trace_id"),
            session_id=context_id,
            metadata={"trace_name": f"A2A Message - {request.agent_id}", "request_source": "a2a_gateway", **request.metadata},
        ))
        if result.status == "completed":
            text = self._text_from_output(result.output)
            task = A2ATask(
                id=task_id,
                context_id=context_id,
                agent_id=request.agent_id,
                status=TaskStatus(state="completed", message=A2AMessage(role="agent", parts=[A2APart(text=text)], context_id=context_id, task_id=task_id)),
                artifacts=[{"artifact_id": f"{task_id}:output", "name": "agent_result", "parts": [{"type": "data", "data": result.output}]}],
                metadata={"trace_id": result.trace_id, "invocation_id": result.invocation_id, "request_source": "a2a_gateway"},
            )
        else:
            state = "rejected" if result.status == "blocked" else "failed"
            error_text = (result.error or {}).get("message") or (result.error or {}).get("code") or "A2A task failed"
            task = A2ATask(
                id=task_id,
                context_id=context_id,
                agent_id=request.agent_id,
                status=TaskStatus(state=state, message=A2AMessage(role="agent", parts=[A2APart(text=error_text)], context_id=context_id, task_id=task_id)),
                metadata={"trace_id": result.trace_id, "invocation_id": result.invocation_id, "error": result.error},
            )
        self._save_task(task)
        self.control_plane.store.add_event("A2A_TASK_UPDATED", task.metadata.get("trace_id") or task_id, request.agent_id, task.model_dump())
        return task

    def get_task(self, task_id: str) -> A2ATask | None:
        row = self.control_plane.store.get_a2a_task(task_id)
        if not row:
            return None
        return A2ATask(**json.loads(row["task_json"]))

    def cancel_task(self, task_id: str) -> A2ATask | None:
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = TaskStatus(state="canceled", message=A2AMessage(role="agent", parts=[A2APart(text="Task canceled by client.")], context_id=task.context_id, task_id=task.id))
        self._save_task(task)
        self.control_plane.store.add_event("A2A_TASK_CANCELED", task.metadata.get("trace_id") or task_id, task.agent_id, task.model_dump())
        return task

    def _save_task(self, task: A2ATask):
        self.control_plane.store.save_a2a_task(task.model_dump())

    def _payload_from_message(self, request: A2ASendMessageRequest) -> dict[str, Any]:
        explicit = request.metadata.get("payload") or request.message.metadata.get("payload")
        if isinstance(explicit, dict):
            return explicit
        text = " ".join(part.text for part in request.message.parts if part.type == "text" and part.text).strip()
        data = {}
        for part in request.message.parts:
            if part.type == "data" and isinstance(part.data, dict):
                data.update(part.data)
        payload = {**data}
        if text and "query" not in payload:
            payload["query"] = text
        payload.setdefault("session_id", request.context_id or request.message.context_id or request.message.task_id or str(uuid4()))
        return payload

    def _text_from_output(self, output: Any) -> str:
        if isinstance(output, dict):
            for key in ("answer", "eligibility_assessment", "final", "result", "summary"):
                if output.get(key):
                    return str(output[key])
            return json.dumps(output, default=str)
        return str(output)

    def _examples_for(self, contract) -> list[str]:
        if contract.agent_id == "policy_assistant_agent":
            return ["What are the KYC requirements for opening a savings account?"]
        if contract.agent_id == "loan_assessment_agent":
            return ["Assess this home loan profile against bank policy."]
        if contract.agent_id == "collections_workflow_agent":
            return ["Analyze this collections call transcript and recommend next best action."]
        return [f"Invoke {contract.name}"]
