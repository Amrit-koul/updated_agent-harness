"""A2A protocol gateway routes for governed banking agents."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from agent_harness.a2a import A2AGatewayService, A2AJsonRpcRequest, A2ASendMessageRequest
from agent_harness.exceptions import AgentNotFoundError

from .harness.runtime import control_plane


router = APIRouter(tags=["A2A Agent Gateway"])
gateway = A2AGatewayService(control_plane)


@router.get("/.well-known/agent-card.json")
async def well_known_agent_card():
    return gateway.gateway_card()


@router.get("/api/v1/a2a")
async def a2a_overview():
    return {
        "name": "EY Agent Harness A2A Gateway",
        "status": "enabled",
        "positioning": "Production-grade A2A gateway for governed banking agents.",
        "endpoints": {
            "gateway_card": "/.well-known/agent-card.json",
            "agent_card": "/api/v1/a2a/agents/{agent_id}/card",
            "send_message": "/api/v1/a2a/message/send",
            "json_rpc": "/api/v1/a2a/rpc",
            "get_task": "/api/v1/a2a/tasks/{task_id}",
            "cancel_task": "/api/v1/a2a/tasks/{task_id}/cancel",
        },
        "bank_controls": ["contracts", "rbac", "lifecycle", "guardrails", "audit", "observability", "usage_cost"],
    }


@router.get("/api/v1/a2a/agents")
async def a2a_agents():
    return {"agents": [gateway.agent_card(item["agent_id"]) for item in control_plane.registry.list_agents()]}


@router.get("/api/v1/a2a/agents/{agent_id}/card")
async def a2a_agent_card(agent_id: str):
    try:
        return gateway.agent_card(agent_id)
    except (AgentNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc))


@router.post("/api/v1/a2a/message/send")
async def a2a_send_message(request: A2ASendMessageRequest):
    try:
        return await gateway.send_message(request)
    except (AgentNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"A2A task failed: {exc}")


@router.get("/api/v1/a2a/tasks")
async def a2a_list_tasks(limit: int = 100, agent_id: str | None = None, state: str | None = None):
    limit = max(1, min(limit, 500))
    tasks = []
    for row in control_plane.store.list_a2a_tasks(limit=limit, agent_id=agent_id, state=state):
        item = dict(row)
        item["task"] = json.loads(item.pop("task_json"))
        tasks.append(item)
    return {"tasks": tasks}


@router.get("/api/v1/a2a/tasks/{task_id}")
async def a2a_get_task(task_id: str):
    task = gateway.get_task(task_id)
    if not task:
        raise HTTPException(404, f"A2A task '{task_id}' was not found")
    return task


@router.post("/api/v1/a2a/tasks/{task_id}/cancel")
async def a2a_cancel_task(task_id: str):
    task = gateway.cancel_task(task_id)
    if not task:
        raise HTTPException(404, f"A2A task '{task_id}' was not found")
    return task


@router.post("/api/v1/a2a/rpc")
async def a2a_json_rpc(request: A2AJsonRpcRequest):
    try:
        if request.method == "message/send":
            task = await gateway.send_message(A2ASendMessageRequest(**request.params))
            return {"jsonrpc": "2.0", "id": request.id, "result": task.model_dump()}
        if request.method == "tasks/get":
            task = gateway.get_task(request.params.get("id") or request.params.get("task_id"))
            if not task:
                return {"jsonrpc": "2.0", "id": request.id, "error": {"code": -32004, "message": "Task not found"}}
            return {"jsonrpc": "2.0", "id": request.id, "result": task.model_dump()}
        if request.method == "tasks/cancel":
            task = gateway.cancel_task(request.params.get("id") or request.params.get("task_id"))
            if not task:
                return {"jsonrpc": "2.0", "id": request.id, "error": {"code": -32004, "message": "Task not found"}}
            return {"jsonrpc": "2.0", "id": request.id, "result": task.model_dump()}
        if request.method == "agent/getAuthenticatedExtendedCard":
            agent_id = request.params.get("agent_id")
            card = gateway.agent_card(agent_id) if agent_id else gateway.gateway_card()
            return {"jsonrpc": "2.0", "id": request.id, "result": card}
        return {"jsonrpc": "2.0", "id": request.id, "error": {"code": -32601, "message": f"Unsupported A2A method: {request.method}"}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request.id, "error": {"code": -32000, "message": str(exc)}}
