# Document 1: Technical Architecture — Agent Harness
### Client-Facing Technical Reference | Bandhan Bank Agentic Platform Demo

---

## 0. Agent Harness Story - What EY Is Selling to a Bank

### Executive Proposition
EY is not selling a single chatbot or a one-off banking use case. EY is selling a governed agent operating model for the bank: a reusable technology control plane that lets the bank onboard, run, monitor, stop, audit, and continuously improve many AI agents across regulated business functions.

The story to tell the bank is:

> "Your bank will not win with isolated AI pilots. You will win by industrializing AI agents safely. Agent Harness is the enterprise layer that turns AI agents from experiments into controlled digital workers that can operate inside banking governance, risk, compliance, technology, and operations standards."

### Business Problem for the Bank
Banks want AI agents for policy support, loan operations, collections, service, risk, compliance, and operations. The blocker is not only model accuracy. The blocker is enterprise control:

- Who approved this agent?
- What policies and tools is it allowed to use?
- What evidence did it use for an answer or recommendation?
- Can the bank stop the agent instantly if it behaves incorrectly?
- Can audit, compliance, risk, and technology teams review every decision path?
- Can third-party or vendor agents be onboarded without giving up governance?
- Can usage, cost, performance, and quality be tracked centrally?

Agent Harness answers those questions with architecture, not slideware.

### EY Consulting Offer
EY can position this as a packaged consulting and implementation offer:

1. **Agentic AI Strategy for Banking:** identify high-value agent use cases and classify them by risk, data sensitivity, and operational impact.
2. **Agent Harness Foundation:** deploy the reusable control plane, registry, contracts, guardrails, audit, observability, lifecycle states, and cost tracking.
3. **Banking Agent Factory:** onboard first agents such as Policy Assistant, Loan Assessment, and Collections Workflow using a repeatable contract and adapter model.
4. **Risk and Compliance Operating Model:** define approval workflows, guardrail thresholds, review triggers, evidence rules, kill-switch responsibilities, and audit reporting.
5. **Scale and Integration Roadmap:** integrate with bank identity, data platforms, model gateways, ticketing, SIEM, vendor tools, and production observability.

### Technical Thesis
The architecture separates the **agent logic** from the **enterprise control layer**:

- Domain agents remain focused on business work: retrieve policy, assess eligibility, analyze collections calls, recommend next action.
- Agent Harness governs the agent: contract, adapter, policy permissions, lifecycle status, guardrails, usage, audit, trace, and quality gates.
- The control plane makes agents interchangeable: internal Python agents, LangGraph agents, REST agents, webhook agents, and vendor workflows can all be managed through the same operating model.

### Bank Value Narrative
For business stakeholders, the value is faster AI adoption with lower operational risk. For technology stakeholders, the value is a reusable, modular architecture. For risk and compliance stakeholders, the value is evidence, traceability, lifecycle control, and policy enforcement.

The demo proves the story through three banking scenarios:

- **Policy Assistant:** reduces policy search time while preserving evidence and citation quality.
- **Loan Assessment:** supports consistent preliminary eligibility reasoning with policy grounding and disclaimers.
- **Collections Workflow:** shows that even a separately-developed or vendor-style workflow can be onboarded into the same governance layer.
- **A2A Gateway:** exposes governed agents through Agent2Agent discovery and message/task endpoints, while allowing vendor A2A agents to be onboarded behind the same control plane.

---

## 1. Agent Harness Purpose

The **Agent Harness** is a reusable, domain-blind control-plane framework built to govern, observe, and lifecycle-manage enterprise AI agents. It provides the infrastructure layer that sits **between** a domain-specific banking application (e.g., Policy Assistant, Loan Assessment, Collections) and the underlying LLM providers (Groq) and vector stores (ChromaDB).

Its core responsibility is not to be an agent itself, but to **host, govern, route, and audit agents** through a well-defined contract system, adapter boundary, and policy engine. This distinguishes it from raw agentic pipelines where agents call tools without any oversight layer.

**In this repository**, the Agent Harness is instantiated as:
- A generic control-plane framework (`Backend/agent_harness/`)
- Applied to a banking domain (`Backend/banking_agents/`)
- Exposed through a React/Vite dashboard (`Frontend/src/`)

---

## 2. Backend Architecture

```
Backend/
├── agent_harness/             ← Generic reusable control-plane framework
│   ├── registry.py            ← AgentRegistry: loads contracts, manages adapters
│   ├── contracts.py           ← AgentContract dataclass + AgentStatus enum
│   ├── adapters.py            ← PythonFunction, LangGraph, RestAPI, ExternalWebhook adapters
│   ├── base_adapter.py        ← BaseAgentAdapter abstract class
│   ├── primitives.py          ← PrimitiveCatalog: skills, tools, hooks, evaluators
│   ├── kill_switch.py         ← KillSwitchService: lifecycle state transitions
│   ├── governance.py          ← GovernanceReader: YAML-driven rule reader
│   ├── observability.py       ← ObservabilityHook + LangSmith integration
│   ├── audit.py               ← AuditStore (SQLite): sessions + guardrail events
│   ├── store.py               ← ControlPlaneStore (SQLite): all control-plane tables
│   ├── graph.py               ← Parent LangGraph runtime wrapper
│   ├── usage.py               ← UsageMeter: token + cost tracking
│   ├── tracing.py             ← Tracer: local span recording
│   ├── policy.py              ← Policy abstraction
│   ├── orchestrator.py        ← HarnessOrchestrator
│   ├── fleet.py               ← AgentFleet
│   ├── catalog.py             ← AgentCatalog
│   ├── degradation_monitor.py ← Degradation detection
│   ├── memory.py              ← Agent memory management
│   ├── redaction.py           ← PII/sensitive data redaction
│   └── prompt_registry.py     ← Versioned prompt registry
│
└── banking_agents/            ← Domain application (banking context)
    ├── main.py                ← FastAPI app, all routes
    ├── control_routes.py      ← Control Plane API router (~820 lines)
    ├── agents/
    │   ├── domain/            ← PolicyRAGAgent, LoanEligibilityRAGAgent
    │   ├── reusable/          ← OrchestratorAgent, IntentClassifier, TaskDecomposer
    │   └── control_plane_plugins/ ← Adapter wrappers for control-plane invoke
    ├── collections_domain/    ← Collections workflow plugin system
    ├── guardrails/            ← InputValidator, OutputValidator, RAGGuard, BusinessGuardrail
    ├── rag/                   ← BaseRAG (ChromaDB + SentenceTransformer)
    ├── evaluation/            ← RAG evaluator (groundedness, semantic similarity, LLM judge)
    ├── config/                ← All YAML configs (agents, tools, skills, guardrails, etc.)
    ├── prompts/               ← Versioned prompt packages
    ├── observability/         ← harness_logger ring buffer
    ├── policy/                ← ToolAuthorization service
    └── harness/               ← runtime.py: control_plane singleton
```

**Runtime entry point:** `banking_agents/main.py` — FastAPI application with Uvicorn  
**Port:** 8000  
**Framework:** FastAPI + LangGraph + Groq SDK + ChromaDB

---

## 3. Frontend Architecture

```
Frontend/src/
├── main.jsx                ← React Router, all page routes
├── api.js                  ← Base API helper (legacy dashboard)
├── globals.css             ← Global design system
├── services/
│   └── controlPlaneApi.js  ← All /api/v1/control/ API calls (~89 functions)
├── hooks/
│   ├── useControlData.js   ← Generic data-fetching hook
│   ├── useBackendHealth.js ← Backend health polling
│   └── usePoll.js          ← Polling hook
├── pages/
│   ├── ChatPage.jsx               ← Policy Assistant chat UI
│   ├── LoanAssessmentPage.jsx     ← Structured loan assessment form
│   ├── CollectionsAgentPage.jsx   ← Collections workspace UI
│   ├── DashboardPage.jsx          ← Legacy metrics dashboard
│   └── control/                   ← Control Plane pages
│       ├── ControlTower.jsx       ← Overview dashboard
│       ├── AgentRegistry.jsx      ← Catalog + contract drawer
│       ├── AgentContract.jsx      ← Contract deep-dive
│       ├── AgenticPrimitives.jsx  ← Skills/tools/hooks viewer
│       ├── KillSwitchDegradation.jsx ← Lifecycle management
│       ├── PolicyGuardrails.jsx   ← Policy + guardrail events
│       ├── Observability.jsx      ← Trace events
│       ├── RagQuality.jsx         ← RAG evaluation scores
│       ├── AuditLogs.jsx          ← Audit trail viewer
│       ├── UsageCost.jsx          ← Token + cost tracking
│       └── Runconsole.jsx         ← Agent invocation console
└── components/
    ├── Primitives.jsx     ← Shared UI components
    ├── AuditTrail.jsx     ← Audit session component
    ├── RagQualityGate.jsx ← RAG score badge
    └── control/           ← Control plane UI components
```

**Technology stack:** React 18 + Vite + React Router v6 + vanilla CSS  
**Port:** 5173 (dev)  
**API base:** `VITE_API_BASE` env variable (default: `http://localhost:8000`)

---

## 4. Control Plane Runtime

The control plane is instantiated as a singleton object via `banking_agents/harness/runtime.py`. On startup, the `control_plane` object is built by loading all agent YAML manifests from `banking_agents/config/agents/`, initializing the `AgentRegistry`, `ControlPlaneStore` (SQLite), `KillSwitchService`, `UsageMeter`, and `PrimitiveCatalog`.

```python
# agent_harness/graph.py — Parent LangGraph runtime graph
START
  → registry_check           # Identify agent from endpoint/catalog
  → runtime_control_check    # Read ACTIVE/DISABLED lifecycle state
  → execute_existing_runtime # Delegate to HarnessOrchestrator.execute()
  → finalize_response        # Emit trace, preserve response shape
  → END
```

Every agent invocation (chat, loan, collections) passes through this graph. Nodes are decorated with `@traceable_node(name)` which applies `langsmith.traceable` if LangSmith is configured.

**Key runtime mechanism:** `HarnessOrchestrator.execute()` → `AgentFleet.invoke()` → `AgentRegistry.get_adapter()` → appropriate `BaseAgentAdapter.invoke()`

---

## 5. Agent Registry and Catalog

**Registry** (`agent_harness/registry.py`):
- `AgentRegistry` loads all manifests from YAML via `load_agent_contracts(config_dir)`
- Validates each manifest via `ContractValidator`
- Persists agent status to SQLite (`agents` table) — status survives restarts
- Tracks runtime metrics per agent: runs, failures, policy_blocks, recent latencies
- `get_adapter()` lazily builds the appropriate adapter (cached)

**Catalog** (`agent_harness/catalog.py`):
- `AgentCatalog` is a simpler runtime catalog for `HarnessOrchestrator`
- Stores agents with display metadata, capabilities, enabled/disabled state

**Current registered agents (from YAML):**

| agent_id | Name | Adapter Type | Execution Mode |
|---|---|---|---|
| `policy_assistant_agent` | Policy Assistant Agent | python_function | workflow |
| `loan_assessment_agent` | Loan Assessment Agent | python_function | workflow |
| `collections_workflow_agent` | Collections Workflow Agent | python_function | workflow |
| `sample_external_agent` | Sample External Agent | rest_api | async |
| `sample_external_rest_agent` | Sample External REST Agent | rest_api | sync |
| `sample_github_wrapped_agent` | Sample GitHub Wrapped Agent | python_function | workflow |
| `demo_vendor_rest_agent` | Demo Vendor REST Agent | rest_api | sync |

---

## 6. Agent Contract System

**File:** `agent_harness/contracts.py`

The `AgentContract` is a typed Python dataclass that serves as the single source of truth for everything the harness needs to know about an agent:

```python
@dataclass
class AgentContract:
    agent_id: str
    name: str
    owner: str
    business_function: str
    agent_type: str               # internal | external_plugin | vendor
    execution_mode: str           # workflow | async | sync
    adapter_type: str             # python_function | rest_api | langgraph | external_webhook
    entrypoint: str               # Python dotted path
    endpoint: str                 # For REST adapters
    version: str
    description: str
    input_schema: dict            # JSON Schema for input validation
    output_schema: dict           # JSON Schema for output shape
    state_schema: dict
    memory_schema: dict
    skills: list[str]             # References to skills.yaml
    tools: list[str]              # References to tools.yaml
    prompts: list[str]            # Versioned prompt references
    model_preferences: dict       # Primary/fallback LLM config
    policy_permissions: dict      # Allowed tools, actions, data scopes
    guardrails: list[str]         # Active guardrail IDs
    observability_hooks: dict     # execution_trace, agent_run, step_trace, etc.
    status: AgentStatus           # ACTIVE | REVIEW | DISABLED | QUARANTINED
    metadata: dict                # Adapter-specific metadata
```

Contracts are stored in SQLite as JSON (`agent_contracts` table) and served through `/api/v1/control/agents/{id}/contract`.

---

## 7. Adapter Boundary

**File:** `agent_harness/adapters.py`

The adapter boundary is the single interface through which the harness invokes any agent, regardless of whether it is a local Python function, a LangGraph workflow, or an external REST API:

```
Agent Contract (manifest)
       ↓
  AgentRegistry.get_adapter(agent_id)
       ↓
  ┌──────────────────────────────────────┐
  │ Adapter Selection (adapter_type)     │
  │  python_function → PythonFunctionAgentAdapter  │
  │  langgraph       → LangGraphAgentAdapter       │
  │  rest_api        → RestApiAgentAdapter         │
  │  external_webhook→ ExternalWebhookAgentAdapter │
  └──────────────────────────────────────┘
       ↓
  BaseAgentAdapter.invoke(payload, trace_id)
```

**Key adapter properties:**
- All adapters enforce `timeout_seconds` from contract metadata
- `PythonFunctionAgentAdapter` uses `ThreadPoolExecutor` with context propagation
- `LangGraphAgentAdapter` calls `.invoke()` or `.ainvoke()` on the graph
- `RestApiAgentAdapter` handles retry with `max_attempts`, auth headers, health checks
- `ExternalWebhookAgentAdapter` extends REST with heartbeat-based staleness detection
- `A2AAgentAdapter` invokes external Agent2Agent-compatible agents through JSON-RPC `message/send`
- All adapters record spans via the local `Tracer` for observability

### A2A Adapter and Gateway

The harness now includes a production-grade A2A slice for bank interoperability:

- **Inbound A2A gateway:** `Backend/banking_agents/a2a_routes.py`
- **A2A protocol models:** `Backend/agent_harness/a2a/schemas.py`
- **A2A gateway service:** `Backend/agent_harness/a2a/service.py`
- **Outbound A2A adapter:** `A2AAgentAdapter` in `Backend/agent_harness/adapters.py`
- **Sample external A2A contract:** `Backend/banking_agents/config/agents/sample_external_a2a_agent.yaml`
- **Durable task state:** `a2a_tasks` SQLite table

Demo endpoints:

```text
GET  /.well-known/agent-card.json
GET  /api/v1/a2a
GET  /api/v1/a2a/agents/{agent_id}/card
POST /api/v1/a2a/message/send
POST /api/v1/a2a/rpc
GET  /api/v1/a2a/tasks/{task_id}
POST /api/v1/a2a/tasks/{task_id}/cancel
```

The important architecture point: A2A is not a bypass path. Incoming A2A calls are converted into `InvocationRequest` objects and executed by the same `ControlPlaneRuntime`, so lifecycle state, RBAC, guardrails, policy decisions, audit, observability, budget, and usage controls still apply.

---

## 8. Policy Engine

**Files:** `banking_agents/policy/`, `banking_agents/config/banking_action_policies.yaml`, `banking_agents/config/policies.yaml`

The policy engine evaluates **tool authorization** before any tool is invoked:

1. **ToolInvocationRequest** is submitted (agent_id, tool_id, action, data_scope)
2. Policy engine checks:
   - Is the tool in the agent's `policy_permissions.allowed_tools`?
   - Is the action in `allowed_actions`?
   - Is the data scope in `allowed_data_scopes`?
   - Does the tool's `risk_tier` require human approval?
   - Is the agent in an `ACTIVE` lifecycle state?
3. Returns: `ALLOW`, `BLOCK`, or `REVIEW`
4. All decisions are persisted to `policy_decisions` table in SQLite

**Tool risk tiers defined in `tools.yaml`:**

| Tool | Risk Tier | Requires Human Approval |
|---|---|---|
| `document_search` | low | false |
| `eligibility_checker` | medium | false |
| `collections_account_store` | high | false |
| `transcript_ingestion` | high | false |
| `external_rest_endpoint` | medium | false |

**Business guardrails defined in `guardrails.yaml`:**
- `GRD-CUST-DATA-001` — customer_data_access
- `GRD-PII-001` — pii_leakage
- `GRD-PAY-001` — payment_authorization
- `GRD-SQL-001` — unsafe_sql
- `GRD-CONDUCT-001` — collections_conduct
- `GRD-REG-001` — regulatory_advice
- `GRD-INJECT-001` — prompt_injection
- `GRD-SCOPE-001` — business_scope

---

## 9. Guardrails System

**Files:** `banking_agents/guardrails/`

Guardrails operate at three layers:

### Layer 1: Input Guardrail — `InputValidator`
```python
# banking_agents/guardrails/input_validator.py
# Triggered on EVERY query before processing
- min_length: 5 chars
- max_length: 2000 chars
- injection_patterns: ["ignore previous instructions", "act as", "jailbreak", ...]
# Raises HTTP 400 and emits guardrail_event on violation
```

### Layer 2: RAG Guardrail — `RAGGuard`
```python
# banking_agents/guardrails/rag_guard.py
# Triggered AFTER retrieval, BEFORE generation
- hard_distance_threshold: 1.2  → BLOCK if all docs too distant
- soft_distance_threshold: 0.9  → Add disclaimer if partial match
- no_result_message: fallback text when retrieval returns nothing
```

### Layer 3: Output Guardrail — `OutputValidator`
```python
# banking_agents/guardrails/output_validator.py
# Triggered AFTER generation, BEFORE response
- empty_response_fallback: replace empty outputs
- intent_disclaimers: append mandatory disclaimers by intent
  e.g., LOAN_ELIGIBILITY always appends regulatory disclaimer
```

### Layer 4: Business Guardrails — `BusinessGuardrail`
```python
# banking_agents/guardrails/business.py
# Applied during tool authorization checks
- Evaluates guardrail_id from contract against registered rules
- Persists to guardrail_events table
```

All guardrail violations are emitted to `audit_store.save_guardrail_event()` and the `guardrail_events` SQLite table.

---

## 10. Kill Switch and Lifecycle Management

**File:** `agent_harness/kill_switch.py`

The `KillSwitchService` manages **four lifecycle states**:

```
AgentStatus:
  ACTIVE      → agent runs normally
  REVIEW      → agent is under investigation (runs may be blocked)
  DISABLED    → agent is stopped completely
  QUARANTINED → agent is isolated pending remediation
```

**Manual transition rules:**
```python
ALLOWED_MANUAL_TRANSITIONS = {
    ("review", "active"),
    ("quarantined", "review"),
    ("quarantined", "active"),
    ("disabled", "review"),
    ("disabled", "active"),
    ("active", "review"),
    ("active", "disabled"),
    ("active", "quarantined"),
}
```

**Every status change requires:**
- `reason` — non-empty string
- `source` — event source (manual/admin/runtime/degradation)
- `approved_by` — for manual transitions
- `override_type` — for manual transitions

**State is persisted** to `kill_switch_events` table and `agents` table. Status survives restarts (the registry restores it from DB on load).

**Degradation monitor** (`agent_harness/degradation_monitor.py`) can automatically trigger `REVIEW` when groundedness scores fall below threshold.

---

## 11. Observability System

**File:** `agent_harness/observability.py`

The observability layer is a **dual-track system**:

### Track 1: Local Ring Buffer + SQLite
- `harness_logger` — in-memory ring buffer (last N log events)
- `ControlPlaneStore.add_event()` → `observability_events` SQLite table
- `ControlPlaneStore.start_run()` / `finish_run()` → `agent_runs` table
- Exposed via `/api/v1/control/events`, `/api/v1/control/runs`

### Track 2: LangSmith Tracing (additive, optional)
```python
# Required env vars:
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<key>
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=aria-agent-harness-demo

# Implementation:
@traceable_node("registry_check")          # graph.py nodes
@traceable(name=..., run_type="chain")     # via observability.py
```

LangSmith is **purely additive** — all local logging/auditing remains independent of whether LangSmith is configured. If env vars are absent, `traceable` becomes a no-op decorator. LangSmith traces wrap the Parent LangGraph graph (4 nodes) and each RAG span within it.

### Observability event types stored:
- `HOOK_*` — hook dispatch events
- `KILL_SWITCH_EVENT` — lifecycle changes
- `LIFECYCLE_STATUS_CHANGED` — same payload, different event_type
- `HEARTBEAT` — used by ExternalWebhookAdapter health check

---

## 12. Audit Trail

**File:** `agent_harness/audit.py`

The `AuditStore` is a **singleton SQLite database** at `Backend/data/audit.db`:

```sql
-- audit_sessions: one row per agent invocation session
CREATE TABLE audit_sessions (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT,
    query       TEXT,
    intent      TEXT,
    final_resp  TEXT,
    step_count  INTEGER,
    total_ms    INTEGER,
    timestamp   TEXT,
    audit_trail TEXT    -- JSON array of step-level trace records
);

-- guardrail_events: one row per guardrail trigger
CREATE TABLE guardrail_events (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT,
    event_type  TEXT,
    detail      TEXT,
    timestamp   TEXT
);
```

Every `POST /api/v1/chat`, `POST /api/v1/loan/assess` call persists the full audit trail JSON into `audit_sessions`. This is the basis for the Audit Trail UI (`/control/audit-logs`).

---

## 13. ControlPlaneStore (SQLite Schema)

**File:** `agent_harness/store.py` — `ControlPlaneStore`

Located at `Backend/data/control_plane.db` (or configured path):

```
Tables:
  agents                    ← agent_id, name, status, updated_at
  agent_contracts           ← agent_id, contract_json, source_file
  agent_runs                ← trace_id, agent_id, status, latency, input/output
  observability_events      ← id, trace_id, agent_id, event_type, payload_json
  policy_decisions          ← id, trace_id, agent_id, action, decision, reason
  guardrail_events          ← id, trace_id, agent_id, guardrail_id, decision
  kill_switch_events        ← id, agent_id, old/new status, source, reason, approved_by
  degradation_events        ← id, agent_id, source, reason, metrics_json
  agent_memory              ← agent_id, entity_id, memory_json
  rag_evaluations           ← evaluation_id, trace_id, agent_id, scores...
  usage_events              ← usage_id, trace_id, agent_id, tokens, cost...
  tool_authorization_events ← id, timestamp, agent_id, tool_id, decision...
```

---

## 14. LangSmith / Groq / RAG Integration

### Groq Integration
- **Client:** `groq.Groq(api_key=GROQ_API_KEY)` initialized in `banking_agents/config/settings.py`
- **Primary model:** `llama-3.1-8b-instant` (Policy + Loan agents)
- **Fallback model:** `llama-3.3-70b-versatile` (escalated when confidence is low)
- **Collections model:** `llama-3.1-8b-instant` for LLM extraction
- **Voice STT:** `groq_whisper_large_v3_turbo` (backend migrated, frontend pending)
- **Usage metered:** token counts from `response.usage`, cost estimated from `config/model_pricing.yaml`

### ChromaDB / RAG Integration
```python
# banking_agents/rag/base_rag.py
- Embedding model: all-MiniLM-L6-v2 (SentenceTransformer, local BERT)
- Vector store: ChromaDB PersistentClient at Backend/chroma_db/
- Collections:
    policy_docs   ← banking policy documents
    loan_docs     ← loan eligibility policy documents
- Query: top-5 nearest neighbors by cosine distance
- Distance thresholds: hard=1.2, soft=0.9 (from guardrails.yaml)
```

### LangSmith Integration
```python
# agent_harness/observability.py
from langsmith import traceable as _ls_traceable

def traceable_node(name: str):
    return _ls_traceable(name=name, run_type="chain",
                         project_name=LANGSMITH_PROJECT_NAME)

# Applied to:
# 1. Parent graph nodes (registry_check, runtime_control_check,
#    execute_existing_runtime, finalize_response)
# 2. RAG spans (policy_assistant_flow, rag_retrieval, generate_policy_answer)
# 3. Evaluation spans (rag_evaluation, groundedness_score)
```

---

## 15. Collections Agent as Vendored Workflow Plugin

**Config:** `banking_agents/config/agents/collections_workflow.yaml`
**Entrypoint:** `banking_agents.external_plugins.collections_working_demo.wrapper.invoke`

The Collections Agent is onboarded to the harness as an **external plugin** with `agent_type: external_plugin` and `plugin_source: github_wrapped_workflow`. This demonstrates the harness's ability to govern third-party or separately-developed workflows.

**What the plugin provides:**
- Pre-call 5-score intelligence (account risk, payment propensity, contact probability, settlement likelihood, escalation risk) — **deterministic, evidence-based**
- Post-call transcript analysis using Groq LLaMA (LLM extraction with keyword fallback)
- Promise-to-pay (PTP) extraction and validation
- Claim detection and review case creation
- Trust governance gate
- Persona classification and NBA (Next Best Action) recommendation
- Voice pipeline: Groq Whisper STT + LLaMA + Orpheus TTS — **backend migrated, browser wiring pending**

**Harness controls over it:**
- Contract validates all inputs before invocation
- Guardrails: customer_data_access, pii_leakage, payment_authorization, collections_conduct, prompt_injection, business_scope
- Kill switch controls: lifecycle state managed by harness
- Audit: all invocations logged to ControlPlaneStore
- Observability: full trace via hooks (execution_trace, agent_run, step_trace, policy_decision, usage_cost, audit)

---

## 16. Policy Assistant and Loan Assessment RAG Agents

### Policy Assistant Agent
**Agent ID:** `policy_assistant_agent`  
**File:** `banking_agents/agents/domain/policy_rag_agent.py`  
**Flow:**
```
User Query
  → InputValidator (injection, length check)
  → Small-talk detection (regex pattern match — short-circuit, no RAG)
  → ChromaDB query (policy_docs collection, top-5)
  → Prompt template load (versioned from prompt_registry)
  → Groq API call (llama-3.1-8b-instant)
  → Low-confidence detection → escalate to llama-3.3-70b-versatile (fallback)
  → OutputValidator (intent disclaimer)
  → RAG Evaluation (groundedness, semantic similarity, citation coverage)
  → UsageMeter (token count, cost estimation)
  → AuditStore.save_session()
```

### Loan Assessment Agent
**Agent ID:** `loan_assessment_agent`  
**File:** `banking_agents/agents/domain/loan_eligibility_rag_agent.py`  
**Flow:**
```
CustomerLoanProfile (structured input)
  → Pre-compute: FOIR, LTV, loan-to-income ratio
  → InputValidator
  → ChromaDB query (loan_docs collection)
  → RAGGuard
  → Groq API call
  → OutputValidator (LOAN_ELIGIBILITY mandatory disclaimer appended)
  → AuditStore.save_session()
```

**Structured inputs validated:** monthly_income, cibil_score, loan_amount_requested, loan_tenure_months, employment_type, loan_type, existing_emi

---

## 17. Architecture Diagram (Text Form)

```
                    ┌─────────────────────────────────────────┐
                    │         FRONTEND (React + Vite)         │
                    │  Chat | Loan | Collections | Dashboard   │
                    │  ControlTower | Observability | Audit    │
                    └──────────────────┬──────────────────────┘
                                       │ HTTP / REST
                                       ▼
                    ┌─────────────────────────────────────────┐
                    │     FASTAPI APPLICATION (port 8000)      │
                    │         banking_agents/main.py           │
                    │   /api/v1/chat   /api/v1/loan/assess     │
                    │   /api/v1/control/*  (control plane)     │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │        PARENT LANGGRAPH RUNTIME          │
                    │  registry_check → runtime_control_check  │
                    │  → execute_existing_runtime → finalize   │
                    │  [LangSmith traceable nodes]             │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │         AGENT HARNESS CORE               │
                    │                                          │
                    │  ┌──────────┐   ┌───────────────────┐   │
                    │  │ Registry │   │ PrimitiveCatalog  │   │
                    │  │ (YAML →  │   │ Skills/Tools/Hooks│   │
                    │  │ SQLite)  │   │ Evaluators/Prompts│   │
                    │  └──────────┘   └───────────────────┘   │
                    │  ┌──────────────────────────────────┐    │
                    │  │        Adapter Boundary          │    │
                    │  │  PythonFunction | LangGraph      │    │
                    │  │  RestAPI | ExternalWebhook       │    │
                    │  └──────────────────────────────────┘    │
                    │  ┌──────────┐   ┌───────────────────┐   │
                    │  │ Policy   │   │   KillSwitch      │   │
                    │  │ Engine   │   │   Lifecycle       │   │
                    │  └──────────┘   └───────────────────┘   │
                    │  ┌──────────┐   ┌───────────────────┐   │
                    │  │Guardrails│   │  Observability    │   │
                    │  │In/Out/RAG│   │  + LangSmith      │   │
                    │  └──────────┘   └───────────────────┘   │
                    │  ┌──────────────────────────────────┐    │
                    │  │    SQLite ControlPlaneStore       │    │
                    │  │    + AuditStore                   │    │
                    │  └──────────────────────────────────┘    │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │            DOMAIN AGENTS                 │
                    │  Policy Assistant  | Loan Assessment     │
                    │  Collections Plugin (vendored workflow)  │
                    └──────────────────┬──────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │          EXTERNAL SERVICES               │
                    │  Groq API (llama-3.1-8b / 3.3-70b)      │
                    │  ChromaDB (local vector store)           │
                    │  LangSmith (optional trace platform)     │
                    └─────────────────────────────────────────┘
```

---

*Document prepared from source code inspection of `demo-agent-harness` repository.*  
*All architecture claims are backed by code evidence.*
