import os
import uuid
import yaml
import logging
import asyncio
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from banking_agents.agents.reusable.orchestrator import OrchestratorAgent
from banking_agents.communication.message import CustomerLoanProfile
from banking_agents.guardrails.output_validator import OutputValidator
from banking_agents.observability.logger import harness_logger
import sys

# Add Backend root to sys.path to allow importing agent_harness
backend_root = os.path.dirname(os.path.dirname(__file__))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from agent_harness import HarnessOrchestrator, AgentFleet, AgentCatalog
from agent_harness.registry import agent_registry
from agent_harness.audit import audit_store
from banking_agents.harness.governance import governance_reader
from banking_agents.harness.runtime import control_plane
from agent_harness.invocation import InvocationRequest
from banking_agents.a2a_routes import router as a2a_router
from banking_agents.control_routes import router as control_plane_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Policy Bot Navigator",
    description="Multi-agent banking system powered by Groq",
    version="1.0.0"
)

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Additive, YAML-driven control-plane APIs. Existing routes below remain unchanged.
app.include_router(control_plane_router)
app.include_router(a2a_router)

# Load Configurations
intents_path = os.path.join(os.path.dirname(__file__), "config", "intents.yaml")
with open(intents_path, "r") as f:
    intents_data = yaml.safe_load(f)

orchestrator_path = os.path.join(os.path.dirname(__file__), "config", "orchestrator.yaml")
with open(orchestrator_path, "r") as f:
    orchestrator_data = yaml.safe_load(f)

# Load Guardrail Configuration (Constraint Handling Repository)
guardrails_path = os.path.join(os.path.dirname(__file__), "config", "guardrails.yaml")
with open(guardrails_path, "r") as f:
    guardrails_config = yaml.safe_load(f)

# Constraint Handling: Initialize Output Validator
# Input validation is now owned by the governed control-plane runtime.
output_validator = OutputValidator(guardrails_config["output"])

# Loading the local sentence-transformer can take a while (and may download the
# model on a fresh machine). Keep that work off FastAPI's import path so Uvicorn
# can bind port 8000 immediately and the control-plane endpoints stay available.
orchestrator = None
loan_agent = None
harness_orchestrator = None
_runtime_error = None
_runtime_lock = threading.Lock()
_runtime_task = None


def _initialize_runtime():
    global orchestrator, loan_agent, harness_orchestrator, _runtime_error
    if harness_orchestrator is not None:
        return
    with _runtime_lock:
        if harness_orchestrator is not None:
            return
        try:
            runtime_orchestrator = OrchestratorAgent(
                intents_config=intents_data,
                orchestrator_config=orchestrator_data,
                guardrails_config=guardrails_config,
            )
            runtime_loan_agent = runtime_orchestrator.tool_instances["consult_loan_expert"]
            runtime_fleet = AgentFleet({
                "chat_orchestrator": lambda payload: runtime_orchestrator.run(
                    payload["user_query"], payload["context"]
                ),
                "loan_agent": lambda payload: runtime_loan_agent.answer(
                    task=payload["task"],
                    loan_profile=payload["loan_profile"],
                    session_id=payload["session_id"],
                ),
            })
            runtime_catalog = AgentCatalog({
                "chat_orchestrator": {
                    "name": "chat_orchestrator", "role": "Banking chat flow",
                    "capabilities": ["intent_classification", "rag_routing"],
                    "enabled": True, "state": "ACTIVE",
                },
                "loan_agent": {
                    "name": "loan_agent", "role": "Loan eligibility assessment",
                    "capabilities": ["structured_assessment", "rag_loan_policies"],
                    "enabled": True, "state": "ACTIVE",
                },
            })
            orchestrator = runtime_orchestrator
            loan_agent = runtime_loan_agent
            harness_orchestrator = HarnessOrchestrator(
                fleet=runtime_fleet,
                catalog=runtime_catalog,
            )
            _runtime_error = None
        except Exception as exc:
            _runtime_error = str(exc)
            logger.exception("Agent runtime initialization failed")


def _require_runtime():
    if harness_orchestrator is None:
        detail = "Agent runtime is still initializing. Please retry shortly."
        if _runtime_error:
            detail = f"Agent runtime failed to initialize: {_runtime_error}"
        raise HTTPException(status_code=503, detail=detail)
    return harness_orchestrator


@app.on_event("startup")
async def warm_agent_runtime():
    global _runtime_task
    _runtime_task = asyncio.create_task(asyncio.to_thread(_initialize_runtime))
    for server in control_plane.store.list_mcp_servers():
        asyncio.create_task(control_plane.mcp.refresh_server(server["server_id"]))

# In-memory store for contexts (in a real app, use Redis or a database)
session_contexts = {}

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    final: str
    session_id: str
    intent: str
    audit_trail: Optional[List[Dict[str, Any]]] = None

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    try:
        result = await control_plane.invoke_result(InvocationRequest(
            agent_id="policy_assistant_agent",
            action="invoke",
            payload={"query": request.query, "session_id": session_id},
            session_id=session_id,
            metadata={"trace_name": "Policy Assistant Chat Compatibility Run", "request_source": "legacy_chat_endpoint"},
        ))
        if result.status != "completed":
            code = (result.error or {}).get("code")
            status_code = 503 if code == "AGENT_NOT_ACTIVE" else 403 if result.status == "blocked" else 500
            raise HTTPException(status_code=status_code, detail=result.error or {"message": "Invocation failed"})
        output = result.output or {}
        final_response_text = output_validator.validate(output.get("answer", ""), intent="POLICY", session_id=session_id)
        audit_store.save_session(
            session_id=session_id,
            query=request.query,
            intent="POLICY",
            final_resp=final_response_text,
            audit_trail=output.get("audit_trail", []),
            total_ms=result.duration_ms,
        )
        harness_logger.log_session("session_end", session_id=session_id)
        
        return ChatResponse(
            final=final_response_text,
            session_id=session_id,
            intent="POLICY",
            audit_trail=output.get("audit_trail", []),
        )
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled error in chat endpoint")
        raise HTTPException(status_code=500, detail="Internal server error.")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Agentic Banking Backend is running."}


class LoanAssessRequest(BaseModel):
    session_id: Optional[str] = None
    query: str = ""            # Optional natural language context
    profile: CustomerLoanProfile

class LoanAssessResponse(BaseModel):
    session_id: str
    eligibility_assessment: str
    profile_used: CustomerLoanProfile

@app.post("/api/v1/loan/assess", response_model=LoanAssessResponse)
async def loan_assess_endpoint(request: LoanAssessRequest):
    """
    Structured loan eligibility assessment endpoint.
    Accepts a CustomerLoanProfile with validated fields and returns
    a deterministic eligibility assessment with pre-computed FOIR, LTV, etc.
    """
    try:
        session_id = request.session_id or str(uuid.uuid4())
        profile_payload = request.profile.model_dump() if hasattr(request.profile, "model_dump") else request.profile.dict()
        runtime_result = await control_plane.invoke_result(InvocationRequest(
            agent_id="loan_assessment_agent",
            action="invoke",
            payload={"query": request.query, "profile": profile_payload, "session_id": session_id},
            session_id=session_id,
            metadata={"trace_name": "Loan Assessment Compatibility Run", "request_source": "legacy_loan_endpoint"},
        ))
        if runtime_result.status != "completed":
            code = (runtime_result.error or {}).get("code")
            status_code = 503 if code == "AGENT_NOT_ACTIVE" else 422 if code == "INPUT_SCHEMA_INVALID" else 403 if runtime_result.status == "blocked" else 500
            raise HTTPException(status_code=status_code, detail=runtime_result.error or {"message": "Invocation failed"})

        output = runtime_result.output or {}
        result = output.get("eligibility_assessment", "")
        latency_ms = runtime_result.duration_ms
        agent_registry.record_call("consult_loan_expert", latency_ms=latency_ms, error=False)
        harness_logger.log_agent_call(
            agent="LoanEligibilityRAGAgent",
            tool="consult_loan_expert",
            latency_ms=latency_ms,
            status="success",
            session_id=session_id,
            detail=f"Structured assessment ({len(result)} chars)",
        )
        result = output_validator.validate(result, intent="LOAN_ELIGIBILITY", session_id=session_id)
        audit_trail = [{
            "step": 1,
            "call_type": "model",
            "agent": "LoanEligibilityRAGAgent",
            "model": output.get("model") or "configured-by-control-plane",
            "action": "Structured Loan Assessment",
            "summary": f"Completed in {latency_ms} ms",
            "output": result,
        }]
        audit_store.save_session(
            session_id=session_id,
            query=request.query or "Assess this applicant against the bank loan eligibility policy.",
            intent="LOAN_ELIGIBILITY",
            final_resp=result,
            audit_trail=audit_trail,
            total_ms=latency_ms,
        )
        return LoanAssessResponse(
            session_id=session_id,
            eligibility_assessment=result,
            profile_used=request.profile
        )


    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid loan profile: {str(e)}")
    except Exception:
        logger.exception("Unhandled error in structured loan assessment")
        raise HTTPException(status_code=500, detail="Internal server error.")



# ---------------------------------------------------------------------------
#  AGENT HARNESS CONTROL PLANE API ENDPOINTS
# ---------------------------------------------------------------------------

def _legacy_harness_removed():
    raise HTTPException(
        status_code=410,
        detail=(
            "Legacy /api/v1/harness endpoints are retired. "
            "Use /api/v1/control for registry, lifecycle, audit, policy, "
            "observability, usage, and security operations."
        ),
    )

class AgentToggleRequest(BaseModel):
    enabled: bool
    triggered_by: str = "dashboard"


class HarnessHealth(BaseModel):
    status: str
    components: Dict[str, str]
    agent_count: int
    total_sessions: int


@app.get("/api/v1/harness/agents")
async def get_agents():
    """Returns all agents with current status, call counts, and kill switch state."""
    _legacy_harness_removed()


@app.post("/api/v1/harness/agents/{agent_name}/toggle")
async def toggle_agent(agent_name: str, request: AgentToggleRequest):
    """Enable or disable an agent via the kill switch."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/audit")
async def get_audit_sessions(limit: int = 50, offset: int = 0):
    """Returns paginated list of audit sessions."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/audit/{session_id}")
async def get_audit_session(session_id: str):
    """Returns full audit trail for a specific session."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/metrics")
async def get_metrics():
    """Returns per-agent call counts, latency, and aggregate session metrics."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/governance")
async def get_governance():
    """Returns active guardrail rules and recent trigger events."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/logs")
async def get_logs(n: int = 100):
    """Returns last n structured log entries from the ring buffer."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/kill-switch-log")
async def get_kill_switch_log(limit: int = 50):
    """Returns recent kill switch toggle events."""
    _legacy_harness_removed()


@app.get("/api/v1/harness/health")
async def get_harness_health():
    """Returns health status of all harness components."""
    _legacy_harness_removed()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("banking_agents.main:app", host="0.0.0.0", port=8000, reload=True)
