# Document 2: Feature Inventory + Code Truth
### Agent Harness — What is Real, What is Seeded, What is Demo-Only
---

## 0. Sales Story Feature Map - What the Demo Proves

### What EY Is Selling
EY is selling a governed agent platform accelerator for banks, not a generic AI demo. The feature set proves that a bank can move from isolated experiments to a controlled agent estate where every agent has an owner, contract, permission set, lifecycle state, audit trail, quality signal, and operating dashboard.

### Bank Buyer Lens
Use this lens when explaining each feature:

| Bank Stakeholder | What They Care About | Feature Evidence in This Demo |
|---|---|---|
| Business Head | Faster policy, lending, and collections operations | Policy Assistant, Loan Assessment, Collections Workspace |
| CIO / CTO | Reusable architecture, integration readiness, cost control | Agent Registry, Adapter Model, Usage and Cost Tracking |
| CRO / Compliance | Explainability, evidence, review, policy enforcement | RAG Quality, Guardrails, Audit Trail, Agent Contracts |
| Operations | Run-state visibility and ability to intervene | Control Tower, Kill Switch, Lifecycle Status |
| Vendor Management | Ability to govern third-party agents | REST/Webhook/GitHub/plugin adapter patterns |
| CISO | Access control, tool authorization, data scope boundaries | Policy Permissions, MCP Governance, Security/RBAC controls |

### Feature Narrative for the Video
When recording the walkthrough, do not present the UI as "screens." Present it as a bank operating model:

1. **Register the workforce:** show Agent Catalog and Agent Contracts.
2. **Constrain the workforce:** show tools, skills, policies, guardrails, RBAC, and MCP controls.
3. **Run business work:** show Policy Assistant, Loan Assessment, and Collections.
4. **Prove the work:** show RAG quality, citations, audit events, traces, and usage.
5. **Control the risk:** show kill switch, review state, degradation, and lifecycle events.

### What Must Be Clear in the PPT
The PPT should make these claims, and the demo should back each one with a real screen or code file:

- Agent Harness is reusable across banking domains.
- Agents are onboarded through formal YAML contracts, not hidden code paths.
- Every invocation can be audited and traced.
- Guardrails are layered: input, business policy, retrieval quality, output, and lifecycle.
- The bank can govern internal and external agents through the same adapter boundary.
- A2A support is implemented as a governed gateway: Agent Cards, message/task endpoints, SQLite task state, and an outbound A2A adapter.
- The current build is a working reference implementation with clear labels for live, seeded, fallback, static, and demo-only areas.

---

> **Legend:**
> - 🟢 **LIVE** — backend logic runs in real-time, data written to SQLite or ChromaDB
> - 🟡 **SEEDED** — data was pre-ingested or pre-seeded but logic is real
> - 🔵 **FALLBACK** — fallback code path runs when primary is unavailable
> - 🟠 **STATIC** — read from YAML/config, no runtime computation
> - 🔴 **DEMO-ONLY** — endpoint or UI exists for demo purposes; real production path not yet wired

---

## Feature 1: Agent Catalog

### What Exists in Backend
The `AgentRegistry` loads 7 agent manifests from `banking_agents/config/agents/*.yaml` at startup. Each manifest is parsed into an `AgentContract` dataclass, validated by `ContractValidator`, and stored in `agent_contracts` SQLite table. The registry maintains runtime metrics (runs, failures, policy_blocks) per agent in memory.

### Endpoint(s) Used
```
GET  /api/v1/control/agents                    → List all agents + metrics
GET  /api/v1/control/agents/{id}               → Single agent detail
GET  /api/v1/control/agents/{id}/contract      → Full contract with primitives
GET  /api/v1/control/agents/{id}/status        → Current lifecycle status
GET  /api/v1/control/agents/{id}/health        → Adapter health check
```

### Frontend Page / Component
- **Page:** `/control/agents` → `AgentRegistry.jsx`
- **Components:** `ContractDrawer`, `StatusChip`, `HealthChip`, `ExecModeChip`
- **Data source:** `controlPlaneApi.listAgents()`, `controlPlaneApi.getContract(id)`

### Database / Table / Store
- `agent_contracts` table (SQLite, ControlPlaneStore)
- `agents` table (SQLite, ControlPlaneStore) — status + name
- In-memory `_metrics` dict on `AgentRegistry`

### Status
🟢 **LIVE** — agents are loaded from real YAML at startup, contracts stored in SQLite, metrics updated on every real invocation

### Important Code Files
- `agent_harness/registry.py` — `AgentRegistry.load()`, `list_agents()`
- `agent_harness/contracts.py` — `AgentContract` dataclass
- `agent_harness/config_loader.py` — reads YAML manifests
- `banking_agents/control_routes.py` (lines 1–200) — API routes
- `Frontend/src/pages/control/AgentRegistry.jsx`

### Key Code Snippet
```python
# agent_harness/registry.py — AgentRegistry.load()
def load(self, config_dir):
    validator = ContractValidator()
    contracts = load_agent_contracts(config_dir)
    for contract in contracts:
        validator.validate_or_raise(contract)
        # Restore persisted lifecycle state from DB
        persisted = self.services.store.query(
            "SELECT status FROM agents WHERE agent_id=?", (contract.agent_id,))
        if persisted and persisted[0].get("status"):
            contract.status = AgentStatus(persisted[0]["status"])
        self._contracts[contract.agent_id] = contract
```

### What is Real vs Mocked
- **Real:** Contract loading from YAML, SQLite persistence, lifecycle state restoration
- **Real:** Runtime metrics (runs/failures/policy_blocks) tracked on every call
- **Not mocked:** The 7 agents listed are actual registered agents with real configurations

---

## Feature 2: Agent Contract Viewer

### What Exists in Backend
Each agent contract is the serialized `AgentContract.to_dict()`, enriched with:
- Agent primitives (skills, tools, hooks, prompts, evaluators) from `PrimitiveCatalog`
- Runtime metrics from `AgentRegistry`
- Latest kill_switch_event, rag_evaluation, guardrail_event, policy_decision, usage_event from SQLite

### Endpoint(s) Used
```
GET /api/v1/control/agents/{id}/contract
  → Returns: contract fields + primitives + metrics + latest events from each table
```

### Frontend Page / Component
- **Page:** `/control/onboarding` → `AgentContract.jsx`
- **Also:** Drawer in `AgentRegistry.jsx` → `ContractDrawer` component
- **Sections shown:** agent_id, owner, business_function, adapter_type, entrypoint, skills, tools, prompts, guardrails, observability_hooks, model_preferences, policy_permissions, input/output/state/memory schemas

### Database / Table / Store
- `agent_contracts`, `agents`, `kill_switch_events`, `rag_evaluations`, `guardrail_events`, `policy_decisions`, `usage_events` (all SQLite, ControlPlaneStore)

### Status
🟢 **LIVE** for core contract fields  
🟡 **SEEDED** for latest event enrichment (depends on prior real invocations)

### Important Code Files
- `banking_agents/control_routes.py` — `_agent_with_primitives()` function (lines 38–52)
- `agent_harness/primitives.py` — `PrimitiveCatalog.agent_primitives()`
- `Frontend/src/pages/control/Agentcontract.jsx`
- `Frontend/src/pages/control/AgenticPrimitives.jsx`

### Key Code Snippet
```python
# control_routes.py — _agent_with_primitives()
def _agent_with_primitives(agent_id: str):
    contract = control_plane.registry.get_contract(agent_id).to_dict()
    contract["primitives"] = control_plane.primitives.agent_primitives(agent_id)
    contract["metrics"] = control_plane.registry.metrics(agent_id)
    for key, sql in {
        "latest_rag_evaluation": "SELECT * FROM rag_evaluations WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
        "latest_guardrail_event": "SELECT * FROM guardrail_events WHERE agent_id=? ...",
        "latest_policy_decision": "SELECT * FROM policy_decisions WHERE agent_id=? ...",
        "latest_usage_event": "SELECT * FROM usage_events WHERE agent_id=? ...",
    }.items():
        contract[key] = control_plane.store.query(sql, (agent_id,))[0] or None
    return contract
```

---

## Feature 3: Policy Assistant (RAG Chat)

### What Exists in Backend
Fully real RAG pipeline using ChromaDB for retrieval and Groq for generation. The agent:
1. Validates input (injection patterns, length)
2. Detects small-talk (regex patterns) and short-circuits
3. Queries `policy_docs` ChromaDB collection (top-5 nearest neighbors)
4. Applies RAGGuard (hard/soft distance thresholds)
5. Loads versioned prompt from `prompt_registry`
6. Calls Groq API (llama-3.1-8b-instant)
7. Escalates to llama-3.3-70b-versatile if low confidence detected
8. Appends disclaimer if soft threshold triggered
9. Runs RAG evaluation (groundedness, semantic similarity, citation coverage)
10. Records usage (tokens, cost)
11. Persists audit trail to SQLite

### Endpoint(s) Used
```
POST /api/v1/chat
  Body: { query: string, session_id?: string }
  Response: { final: string, session_id, intent, audit_trail[] }

POST /api/v1/control/demo/run-policy-agent
  Body: { query: string, session_id?: string }
  Response: { answer, citations[], rag_evaluation{}, prompt_metadata{}, usage{} }
```

### Frontend Page / Component
- **Page:** `/chat` → `ChatPage.jsx` — legacy chat UI
- **Page:** `/control/tower` → `ControlTower.jsx` — has inline policy demo panel
- **Page:** `/control/rag-quality` → `RagQuality.jsx` — shows evaluation scores

### Database / Table / Store
- `audit_sessions` (audit.db) — every session stored with full audit_trail JSON
- `guardrail_events` (audit.db) — guardrail violations logged
- `rag_evaluations` (ControlPlaneStore) — RAG scores persisted per invocation
- `usage_events` (ControlPlaneStore) — token/cost per call
- ChromaDB `policy_docs` collection — source documents

### Status
🟢 **LIVE** — real ChromaDB retrieval, real Groq API call, real evaluation, real SQLite persistence  
🟡 **SEEDED** — ChromaDB must be pre-ingested from `data_ingestion/` scripts before demo

### Important Code Files
- `banking_agents/agents/domain/policy_rag_agent.py` — `PolicyRAGAgent.answer_with_evaluation()`
- `banking_agents/rag/base_rag.py` — `BaseRAG.query()`
- `banking_agents/evaluation/rag.py` — `evaluate_rag_response()`
- `banking_agents/guardrails/input_validator.py` — `InputValidator.validate()`
- `banking_agents/guardrails/rag_guard.py` — `RAGGuard.check()`
- `agent_harness/usage.py` — `UsageMeter.record_llm_response()`

### Key Code Snippet — RAG Pipeline
```python
# policy_rag_agent.py — _answer_impl()
with tracer.span("rag_retrieval", run_type="retriever") as span:
    retrieved_results = self.rag.query(task, n_results=5)
    retrieved_count = len(retrieved_results.get("documents", [[]])[0])

if self.rag_guard:
    proceed, message = self.rag_guard.check(retrieved_results, session_id=session_id)
    if not proceed:
        return {"answer": message, "context": "", "citations": [], "prompt_metadata": {}}

# Groq generation
response = self.client.chat.completions.create(
    model=self.model_id,
    messages=[{"role": "system", "content": system_prompt},
              {"role": "user", "content": user_message}],
    temperature=0.1
)

# Low confidence fallback
if any(marker in output_text.lower() for marker in 
       ("not established", "does not clearly state", "conflicting policy")):
    # Escalate to llama-3.3-70b-versatile fallback
```

### What is Real vs Mocked
- **Real:** ChromaDB retrieval (requires data ingestion)
- **Real:** Groq API call (requires GROQ_API_KEY)
- **Real:** RAG evaluation (deterministic groundedness/semantic scores)
- **Real:** SQLite audit persistence
- **Not mocked:** The fallback escalation, RAGGuard blocking, disclaimer injection
- **Demo-only:** The `/demo/run-policy-agent` endpoint wraps the real agent for control-plane test invocation

---

## Feature 4: Loan Assessment Agent

### What Exists in Backend
Structured loan eligibility assessment with pre-computed financial metrics (FOIR, LTV, loan-to-income), RAG retrieval from `loan_docs` ChromaDB collection, Groq generation, output guardrail (mandatory regulatory disclaimer).

### Endpoint(s) Used
```
POST /api/v1/loan/assess
  Body: { session_id?, query?, profile: CustomerLoanProfile }
  CustomerLoanProfile: { loan_type, employment_type, monthly_income, cibil_score,
                         loan_amount_requested, loan_tenure_months, existing_emi?, ... }

POST /api/v1/control/demo/run-loan-assessment
  Body: same as above
  Response: assessment string + audit_trail
```

### Frontend Page / Component
- **Page:** `/loan-assessment` → `LoanAssessmentPage.jsx` — structured form UI
- **Sections:** employment type, income, CIBIL score, loan amount, tenure, loan type

### Database / Table / Store
- `audit_sessions` (audit.db) — persisted with intent=LOAN_ELIGIBILITY
- ChromaDB `loan_docs` collection
- `usage_events` (ControlPlaneStore)

### Status
🟢 **LIVE** — real Groq call, real ChromaDB retrieval (if ingested), real audit  
🟡 **SEEDED** — loan_docs ChromaDB collection requires prior ingestion

### Important Code Files
- `banking_agents/agents/domain/loan_eligibility_rag_agent.py`
- `banking_agents/main.py` — `/api/v1/loan/assess` route (lines 250–348)
- `Frontend/src/pages/LoanAssessmentPage.jsx`

### Key Code Snippet
```python
# main.py — loan_assess_endpoint
# Pre-compute structured financial ratios before RAG
task = (f"{request.profile.loan_type} loan eligibility assessment for a "
        f"{request.profile.employment_type.lower()} applicant: "
        f"monthly income ₹{request.profile.monthly_income:,.0f}, "
        f"CIBIL {request.profile.cibil_score}, ...")

# OutputValidator appends mandatory disclaimer
result = output_validator.validate(result, intent="LOAN_ELIGIBILITY", session_id=session_id)
# This appends: "This assessment is indicative only. Final loan eligibility
# is subject to bank verification and approval."
```

### What is Real vs Mocked
- **Real:** Input validation, Groq generation, output disclaimer, audit persistence
- **Real:** Pre-computed FOIR/LTV math (deterministic)
- **Seeded:** Loan ChromaDB docs must be ingested

---

## Feature 5: Collections Agent Workspace

### What Exists in Backend
The Collections workflow plugin is onboarded as an `external_plugin` with `adapter_type: python_function`. The harness invokes it via `banking_agents.external_plugins.collections_working_demo.wrapper.invoke`.

**What actually runs:**
- Pre-call mode: deterministic 5-score engine (account risk, payment propensity, contact probability, settlement likelihood, escalation risk) — evidence-based, no LLM required
- Post-call mode: Groq LLaMA transcript analysis with keyword fallback
- Full lifecycle: Pre-call + transcript analysis + post-call updates
- Voice modes: Groq Whisper STT backend is migrated; browser wiring pending
- Captured transcripts: library of sample transcripts available for demo

### Endpoint(s) Used
```
POST /api/v1/control/demo/run-collections
  Body: { mode: pre_call|post_call|full_lifecycle|voice_greet|voice_analyze,
          account_id: string, transcript?: string, captured_transcript_id?: string }

GET  /api/v1/control/demo/collections/accounts
GET  /api/v1/control/collections/transcripts
GET  /api/v1/control/collections/{account_id}/history
POST /api/v1/control/collections/voice/start
POST /api/v1/control/collections/voice/turn
POST /api/v1/control/collections/voice/finalize
```

### Frontend Page / Component
- **Page:** `/collections` → `CollectionsAgentPage.jsx` — multi-panel workspace

### Database / Table / Store
- Collections SQLite DB (`banking_agents/collections_domain/db/`)
- `agent_runs` + `observability_events` (ControlPlaneStore)
- `kill_switch_events` — lifecycle tracked

### Status
🟢 **LIVE** — pre-call deterministic scoring, post-call Groq extraction, audit persistence  
🟡 **SEEDED** — sample accounts in collections DB, sample transcripts in transcript library  
🔴 **DEMO-ONLY (voice frontend)** — voice pipeline backend exists but browser microphone wiring is pending per agent contract metadata

### Important Code Files
- `banking_agents/collections_domain/` — all collections domain logic
- `banking_agents/config/agents/collections_workflow.yaml` — contract + safe_demo_claims
- `banking_agents/external_plugins/collections_working_demo/wrapper.py`
- `Frontend/src/pages/CollectionsAgentPage.jsx`

### What is Real vs Mocked
- **Real:** Pre-call 5-score scoring engine (deterministic evidence)
- **Real:** Groq post-call extraction (when LLM model configured)
- **Real:** Harness lifecycle, guardrail enforcement, kill switch
- **Seeded:** Sample accounts and transcript data
- **Demo-labeled:** Voice pipeline (per contract `avoid_claiming` field)

---

## Feature 6: RAG Quality Gate

### What Exists in Backend
After every RAG agent response, `evaluate_rag_response()` runs:
1. **Groundedness score** — lexical overlap between answer tokens and context tokens
2. **Semantic similarity score** — cosine similarity using SentenceTransformer embeddings (falls back to Jaccard if embedding fails)
3. **Answer relevance score** — similarity of answer to query
4. **Citation coverage** — ratio of cited to retrieved chunks
5. **Unsupported claims detection** — sentences in answer with <25% token overlap to context
6. **LLM judge** — optional, if `RAG_EVALUATOR_MODEL` env var set, uses Groq to score faithfulness

Results are stored in `rag_evaluations` table in ControlPlaneStore.

### Endpoint(s) Used
```
GET /api/v1/control/evaluations
  → Returns: list of rag_evaluation rows from SQLite

GET /api/v1/control/evaluations/{evaluation_id}
  → Returns: single evaluation detail
```

### Frontend Page / Component
- **Page:** `/control/rag-quality` → `RagQuality.jsx`
- **Component:** `RagQualityGate.jsx` — inline score badge
- **Also shown in:** `KillSwitchDegradation.jsx` — groundedness drives lifecycle signal

### Database / Table / Store
- `rag_evaluations` table (ControlPlaneStore SQLite)
- Columns: groundedness_score, semantic_similarity_score, llm_judge_score, answer_relevance_score, citation_coverage, retrieved_chunk_count, evaluator_method, metadata_json

### Status
🟢 **LIVE** — runs automatically after every Policy Assistant query  
🔵 **FALLBACK** — LLM judge is optional (null if not configured); deterministic scores always run

### Important Code Files
- `banking_agents/evaluation/rag.py` — `evaluate_rag_response()`
- `agent_harness/store.py` — `rag_evaluations` table schema
- `banking_agents/control_routes.py` — `/evaluations` routes
- `Frontend/src/pages/control/RagQuality.jsx`

### Key Code Snippet
```python
# evaluation/rag.py
result = {
    "groundedness_score": round(groundedness, 4),   # lexical token overlap
    "semantic_similarity_score": round(semantic, 4), # embedding cosine sim
    "llm_judge_score": None,                         # only if configured
    "answer_relevance_score": round(relevance, 4),
    "citation_coverage": round(len(citations)/max(1,len(citations)), 4),
    "evaluator_method": "embedding_similarity" or "heuristic",
    "is_simulated": False,
    "source": "runtime",
}
```

---

## Feature 7: Policy & Guardrails

### What Exists in Backend
Three active guardrail layers + YAML-driven business rules:

**InputValidator** — blocks injection patterns, length violations  
**RAGGuard** — blocks low-confidence retrieval before generation  
**OutputValidator** — appends mandatory disclaimers by intent  
**BusinessGuardrail** — tool authorization enforcement

Guardrail events are persisted to `guardrail_events` tables in both `audit.db` and `control_plane.db`.

### Endpoint(s) Used
```
GET  /api/v1/control/guardrails              → List active guardrail rules
GET  /api/v1/control/guardrails/events       → Recent guardrail trigger log
GET  /api/v1/control/policy/decisions        → Policy engine decision log
GET  /api/v1/control/tools/authorization-events → Tool authorization events
POST /api/v1/control/tools/authorize         → Evaluate a tool invocation request
POST /api/v1/control/demo/run-unsafe-sql     → Demo: trigger SQL injection guardrail
```

### Frontend Page / Component
- **Page:** `/control/policy-guardrails` → `PolicyGuardrails.jsx`
- **Sections:** Active guardrail rules table, Recent events log, Policy decisions, Tool authorization events
- **Filter:** time filter (last 24h / today), exclude test/simulation events

### Database / Table / Store
- `guardrail_events` (both `audit.db` and `control_plane.db`)
- `policy_decisions` (ControlPlaneStore)
- `tool_authorization_events` (ControlPlaneStore)
- `banking_agents/config/guardrails.yaml` — rule definitions
- `banking_agents/config/banking_action_policies.yaml` — action-level policies

### Status
🟢 **LIVE** — input/output/RAG guardrails run on every real request  
🟠 **STATIC** — guardrail rules read from YAML  
🔴 **DEMO-ONLY** — `/demo/run-unsafe-sql` triggers a simulated SQL injection guardrail event for demo purposes

### Key Code Snippet
```python
# banking_agents/guardrails/input_validator.py
for pattern in self.injection_patterns:
    if pattern in query_lower:
        emit_guardrail_event("input.injection_guard",
            f"Blocked prompt-injection pattern: {pattern}", session_id)
        raise HTTPException(400, "Your request contains prohibited instructions.")

# guardrails.yaml injection patterns:
# - "ignore previous instructions"
# - "ignore all instructions"
# - "you are now"
# - "act as"
# - "pretend you are"
# - "jailbreak"
```

---

## Feature 8: Kill Switch / Review Flow

### What Exists in Backend
`KillSwitchService.change_status()` enforces lifecycle transitions with required metadata (reason, approved_by, override_type for manual transitions). State is persisted to SQLite and restored on restart. Degradation monitor can auto-trigger `REVIEW` status.

### Endpoint(s) Used
```
POST /api/v1/control/kill-switch/{agent_id}
  Body: { new_status, source, reason, triggered_by, approved_by?,
          override_type?, severity?, trace_id?, evidence? }

GET  /api/v1/control/kill-switch/events     → Recent lifecycle change events
GET  /api/v1/harness/agents/{name}/toggle   → Legacy toggle (enabled/disabled)
GET  /api/v1/control/degradation/events     → Degradation trigger log
POST /api/v1/control/demo/simulate-degradation → Demo: trigger degradation event
```

### Frontend Page / Component
- **Page:** `/control/kill-switch` → `KillSwitchDegradation.jsx`
- **Sections:** Agent lifecycle board, kill switch event log, degradation events, lifecycle signal per agent
- **Actions:** Status change buttons (Active→Review→Quarantined→Disabled→Active)

### Database / Table / Store
- `kill_switch_events` (ControlPlaneStore)
- `agents` table (status column, updated on change)
- `degradation_events` (ControlPlaneStore)

### Status
🟢 **LIVE** — lifecycle changes persist to SQLite, are reflected immediately in registry  
🔴 **DEMO trigger** — `simulate-degradation` is a demo-only endpoint that creates a test degradation event

### Key Code Snippet
```python
# agent_harness/kill_switch.py
ALLOWED_MANUAL_TRANSITIONS = {
    ("review", "active"), ("quarantined", "review"),
    ("quarantined", "active"), ("disabled", "review"),
    ("disabled", "active"), ("active", "review"),
    ("active", "disabled"), ("active", "quarantined"),
}

def change_status(self, agent_id, new_status, source, reason, ...):
    if not reason or not str(reason).strip():
        raise ValueError("reason is required for lifecycle transitions")
    # Validate manual transition rule
    if manual and (old, new_status) not in ALLOWED_MANUAL_TRANSITIONS:
        raise ValueError(f"manual lifecycle transition {old} → {new_status} not allowed")
    # Persist and emit event
    self.registry.set_status(agent_id, new_status)
    self.store.add_event("KILL_SWITCH_EVENT", trace_id, agent_id, payload)
```

---

## Feature 9: Audit Trail

### What Exists in Backend
Two-tier audit:
1. `AuditStore` (audit.db) — per-session audit trail JSON (step-level)
2. `ControlPlaneStore` (control_plane.db) — event-level observability

Every chat and loan session writes a complete `audit_trail` JSON array containing step-level records (step number, call_type, agent name, model used, action, timing, output).

### Endpoint(s) Used
```
GET /api/v1/harness/audit              → List sessions (limit, offset)
GET /api/v1/harness/audit/{session_id} → Full audit trail for session
GET /api/v1/control/events             → Control plane observability events
GET /api/v1/control/events/{trace_id}  → Events for specific trace
GET /api/v1/control/runs               → Agent run records
GET /api/v1/control/runs/{trace_id}    → Single run detail
```

### Frontend Page / Component
- **Page:** `/control/audit-logs` → `AuditLogs.jsx`
- **Component:** `AuditTrail.jsx` — inline audit step display
- **Also in:** `DashboardPage.jsx` — sessions table with audit links

### Database / Table / Store
- `audit_sessions` + `guardrail_events` (audit.db, AuditStore)
- `agent_runs` + `observability_events` (control_plane.db, ControlPlaneStore)

### Status
🟢 **LIVE** — all chat + loan sessions write real audit records  
🟡 **SEEDED** — no seed scripts needed; data accumulates on real use

### Key Code Snippet
```python
# main.py — after every chat response
audit_store.save_session(
    session_id=session_id,
    query=request.query,
    intent=agent_response.context.current_intent.value,
    final_resp=final_response_text,
    audit_trail=agent_response.audit_trail,   # step-level JSON array
    total_ms=_chat_ms,
)
```

---

## Feature 10: Observability

### What Exists in Backend
Local structured logging via `harness_logger` (in-memory ring buffer), plus SQLite persistence of all observability events through `ControlPlaneStore.add_event()`. Optionally extended with LangSmith traces.

### Endpoint(s) Used
```
GET /api/v1/harness/logs              → Last N structured logs from ring buffer
GET /api/v1/harness/metrics           → Per-agent call counts + latency
GET /api/v1/harness/health            → Component health (registry, audit, rag, etc.)
GET /api/v1/control/events            → SQLite observability events
GET /api/v1/control/observability/status → LangSmith status + local status
```

### Frontend Page / Component
- **Page:** `/control/observability` → `Observability.jsx`
- **Sections:** Event stream, run history, LangSmith status, trace detail

### Database / Table / Store
- `observability_events` (ControlPlaneStore) — HOOK_*, KILL_SWITCH_EVENT, etc.
- `agent_runs` (ControlPlaneStore) — start_time, latency_ms, status per run
- Ring buffer in `harness_logger`

### Status
🟢 **LIVE** — events write to SQLite on every real invocation  
🔵 **FALLBACK** — if LangSmith not configured, local logging is the sole source

---

## Feature 11: Usage / Cost Tracking

### What Exists in Backend
`UsageMeter.record_llm_response()` captures:
- Provider-reported token counts (from Groq API `response.usage`)
- Cost estimate based on `config/model_pricing.yaml` pricing table
- Fallback token estimation if provider doesn't report (len/4 heuristic)
- Stores per-call usage in `usage_events` SQLite table

### Endpoint(s) Used
```
GET /api/v1/control/usage/summary   → Aggregate token + cost totals
GET /api/v1/control/usage/events    → Per-call usage event log
```

### Frontend Page / Component
- **Page:** `/control/usage-cost` → `UsageCost.jsx`
- **Sections:** Total tokens, estimated cost, per-agent breakdown, recent events

### Database / Table / Store
- `usage_events` (ControlPlaneStore) — provider, model, prompt_tokens, completion_tokens, estimated_total_cost, currency, latency_ms, fallback_used

### Status
🟢 **LIVE** — real token counts from Groq API (provider_reported=true)  
🔵 **FALLBACK** — if Groq doesn't return usage, estimates from text length

### Key Code Snippet
```python
# agent_harness/usage.py — UsageMeter.record_llm_response()
usage = response.usage   # Groq SDK provides this
prompt_tokens = usage.prompt_tokens      # provider-reported
completion_tokens = usage.completion_tokens
input_cost, output_cost, total_cost, _ = self.estimate_cost(
    provider, model, prompt_tokens, completion_tokens)
# Persisted to usage_events table with usage_source="provider_reported"
```

---

## Feature 12: LangSmith Integration

### What Exists in Backend
LangSmith tracing is configured via env vars and applied via the `@traceable_node` decorator on Parent LangGraph nodes, and `langsmith.traceable` on RAG spans. It is **purely additive** — local logging is never replaced.

```python
# agent_harness/observability.py
def is_langsmith_enabled() -> bool:
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower()
    has_key = bool(os.environ.get("LANGSMITH_API_KEY"))
    return flag in ("true", "1", "yes") and has_key
```

### Endpoint(s) Used
```
GET /api/v1/control/observability/status
  → Returns: { sdk_available, tracing_enabled, project, endpoint }
```

### Status
🔵 **FALLBACK** — if env vars absent, `traceable` is a no-op decorator; no behavior change  
🟢 **LIVE** — if `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` set, all graph nodes and RAG spans visible in LangSmith dashboard

### What is Real vs Mocked
- **Real:** SDK integration is in the code via `from langsmith import traceable`
- **Conditional:** Only active if env vars are set in `.env`
- **Never mocked:** The status endpoint reflects the actual SDK/env state

---

## Feature 13: Groq Integration

### What Exists in Backend
Groq SDK is the sole LLM provider. `settings.py` initializes the client:

```python
# banking_agents/config/settings.py
from groq import Groq
MODEL_POLICY_RAG_DEFAULT = "llama-3.1-8b-instant"
MODEL_POLICY_RAG_FALLBACK = "llama-3.3-70b-versatile"

def get_groq_client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])
```

**Models used:**
- `llama-3.1-8b-instant` — Policy Assistant (primary), Loan Assessment (primary), Collections post-call
- `llama-3.3-70b-versatile` — Policy + Loan fallback (low confidence escalation)
- `whisper-large-v3-turbo` — Collections voice STT (backend only)
- `orpheus-tts-v1-english` — Collections voice TTS (backend only)

### Status
🟢 **LIVE** — all agent responses go through real Groq API calls  
**Prerequisite:** `GROQ_API_KEY` must be set in `banking_agents/.env`

---

## Feature 14: ChromaDB / Vector Store

### What Exists in Backend
ChromaDB PersistentClient stores embeddings generated by `all-MiniLM-L6-v2` (SentenceTransformer, local BERT model):

```python
# banking_agents/rag/base_rag.py
self.chroma_client = chromadb.PersistentClient(path=self.db_path)
self.collection = self.chroma_client.get_or_create_collection(name=self.collection_name)
```

**Collections:**
- `policy_docs` — banking policy documents (KYC, payments, account servicing, lending)
- `loan_docs` — loan eligibility policy documents

**Persistence:** `Backend/chroma_db/` directory  
**Ingestion scripts:** `Backend/data_ingestion/`

### Health Check
```python
# main.py — /api/v1/harness/health
policy_count = orchestrator.tool_instances["consult_policy_expert"].rag.collection.count()
loan_count = loan_agent.rag.collection.count()
rag_status = "healthy" if policy_count > 0 and loan_count > 0 else "empty"
```

### Status
🟡 **SEEDED** — collections must be ingested before demo (run `data_ingestion/` scripts)  
🟢 **LIVE once seeded** — all queries go through real ChromaDB retrieval with real embeddings

---

## Feature 15: Agentic Primitives Viewer

### What Exists in Backend
`PrimitiveCatalog` loads from YAML and cross-references agent contracts:
- **Skills** (`skills.yaml`) — with allowed_agent_ids, risk_tier, input/output contracts
- **Tools** (`tools.yaml`) — with allowed_agent_ids, risk_tier, guardrails
- **Memory Contracts** (`memory_contracts.yaml`)
- **Hooks** (`hooks.yaml`) — with trigger_points and hook logic
- **Evaluators** (`evaluators.yaml`) — RAG evaluator definitions
- **Prompts** — loaded from `prompts/` directory (Markdown packages + YAML definitions)

### Endpoint(s) Used
```
GET /api/v1/control/skills
GET /api/v1/control/tools
GET /api/v1/control/memory/contracts
GET /api/v1/control/hooks
GET /api/v1/control/evaluators
GET /api/v1/control/prompts
GET /api/v1/control/primitives/validation
```

### Frontend Page / Component
- **Page:** `/control/primitives` → `AgenticPrimitives.jsx`

### Status
🟠 **STATIC** — read from YAML config; no runtime computation  
🟢 **LIVE cross-referencing** — agent contract links are dynamically resolved

---

## Feature 16: A2A Agent Interoperability Gateway

### What Exists in Backend
The harness exposes registered agents through A2A-style discovery and message/task endpoints. It also supports onboarding external A2A-compatible agents via a first-class `a2a` adapter type.

### Endpoint(s) Used
```text
GET  /.well-known/agent-card.json
GET  /api/v1/a2a
GET  /api/v1/a2a/agents
GET  /api/v1/a2a/agents/{agent_id}/card
POST /api/v1/a2a/message/send
POST /api/v1/a2a/rpc
GET  /api/v1/a2a/tasks
GET  /api/v1/a2a/tasks/{task_id}
POST /api/v1/a2a/tasks/{task_id}/cancel
```

### Important Code Files
- `Backend/banking_agents/a2a_routes.py`
- `Backend/agent_harness/a2a/schemas.py`
- `Backend/agent_harness/a2a/service.py`
- `Backend/agent_harness/adapters.py` - `A2AAgentAdapter`
- `Backend/banking_agents/config/agents/sample_external_a2a_agent.yaml`
- `Backend/agent_harness/migrations/003_a2a_gateway.sql`

### Status
LIVE for discovery, task persistence, internal governed invocation path, JSON-RPC wrapper, and outbound A2A adapter. Streaming and push notifications are explicitly marked unsupported in the Agent Card until hardened.

---

*This document is based on direct source code inspection. All features are documented with actual file paths and code evidence.*
