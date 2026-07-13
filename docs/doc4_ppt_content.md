# Document 4: Final PPT Content Document
### Agent Harness — Client-Facing Technical Deck
### Bandhan Bank | Agentic Platform Demo

---

## Executive Sales Story - EY to Bank

### What Exactly Are We Selling?
We are selling **Agent Harness for Banking**: an EY-led accelerator and implementation approach that gives the bank a reusable control plane for safely deploying and operating AI agents across business functions.

This is not positioned as "one chatbot." It is positioned as the foundation for a bank-wide agent factory:

- Build or onboard agents faster.
- Govern each agent through contracts, policies, tool permissions, and lifecycle states.
- Prove every answer or recommendation with evidence, audit, trace, and quality scores.
- Stop or degrade agents when risk thresholds are crossed.
- Scale from first use cases to enterprise operations without rebuilding governance each time.

### The Business Story
Banks are under pressure to improve productivity in policy operations, lending, collections, service, compliance, and risk. AI agents can help, but banks cannot adopt them like consumer chatbots. A bank needs governance-by-design: every agent must be approved, constrained, monitored, explainable, auditable, and stoppable.

EY's story:

> "We help the bank move from AI experiments to governed AI operations. Agent Harness is the technology foundation that lets business teams adopt agents while technology, risk, and compliance stay in control."

### The Technical Story
The technical differentiation is a control plane around agents:

- **Registry:** known inventory of agents and status.
- **Contracts:** typed YAML definition of owner, business function, tools, prompts, schemas, permissions, and guardrails.
- **Adapters:** same governance for Python, LangGraph, REST, webhook, and plugin/vendor agents.
- **A2A Interoperability:** Agent Cards and A2A message/task APIs expose governed agents to enterprise agent ecosystems.
- **Policy and guardrails:** checks before, during, and after invocation.
- **Evidence:** RAG citations, quality scores, audit logs, trace events, usage and cost.
- **Lifecycle:** active, review, quarantined, disabled, with reason and approver.
- **Control UI:** screens for operations, risk, technology, and audit stakeholders.

### Suggested Talk Track for the First 60 Seconds
"EY is not proposing another chatbot pilot. We are proposing a governed agent foundation for the bank. The bank can start with practical use cases like policy Q&A, loan assessment support, and collections intelligence, but the real asset is the harness around them: agent contracts, adapters, guardrails, audit, RAG quality, usage tracking, and kill switch. That is what lets a regulated bank scale AI agents responsibly."

### PPT Must Include
The deck should include these content blocks:

| Section | Required Content |
|---|---|
| Business context | Why banks need agents, why unmanaged agents are risky, why governance is the differentiator |
| EY proposition | Strategy + harness implementation + first use cases + operating model + scale roadmap |
| Architecture | Frontend, FastAPI, Agent Harness core, adapters, domain agents, RAG, LLM provider, SQLite, LangSmith |
| Features | Registry, contracts, primitives, guardrails, kill switch, audit, observability, RAG quality, usage/cost, RBAC, MCP, A2A |
| Demo | Policy Assistant, Loan Assessment, Collections, control tower, evidence trail, risk controls |
| Code proof | YAML contracts, registry, control routes, guardrails, RAG evaluator, frontend control pages |
| Roadmap | Bank identity, approvals, SIEM, enterprise model gateway, bank data integrations, production hardening |

---

> **Presenter Guide:**
> - 🟢 = Live backend, real data
> - 🟡 = Seeded data, real logic
> - 🔴 = Demo-only or static explanation
> - All code snippets are from actual source files
> - All architecture diagrams are text-form representations of the real codebase

---

## Slide 1: What We Built

### Title
**Agent Harness: An Enterprise-Grade Control Plane for Production AI Agents**

### Subtitle
*Bringing governance, observability, and lifecycle management to multi-agent banking workflows*

### Body Content

We built a full-stack, working system that demonstrates how AI agents can be deployed, governed, and operated at enterprise scale in a regulated banking environment.

**What is running today:**
- A **Policy Assistant** that answers banking policy questions using RAG (ChromaDB + Groq)
- A **Loan Assessment Agent** that evaluates structured loan profiles against policy evidence
- A **Collections Workflow** — a separately-developed agent onboarded as a governed plugin
- A **Control Plane Dashboard** with 10+ operational views: registry, contracts, guardrails, kill switch, audit, observability, RAG quality, usage

**Built with:**
| Layer | Technology |
|---|---|
| Backend | FastAPI + Python + LangGraph |
| LLM Provider | Groq (llama-3.1-8b-instant, llama-3.3-70b-versatile) |
| Vector Store | ChromaDB + all-MiniLM-L6-v2 (local BERT) |
| Frontend | React 18 + Vite |
| Persistence | SQLite (audit + control plane) |
| Observability | LangSmith (optional) + local ring buffer |
| Configuration | YAML-driven manifests |

### Screenshot Placeholder
`[Screenshot: ControlTower dashboard showing all agents ACTIVE with metrics]`

### Speaker Notes
"What you're looking at is not a mock-up. This is a running system — the backend is live at port 8000, agents are registered from YAML manifests, and every query you see go through that chat window hits a real ChromaDB collection and a real Groq API endpoint. The purpose of this session is to show you what 'enterprise-grade' actually means in an agentic context — and why the infrastructure around the agent matters as much as the agent itself."

---

## Slide 2: Why Agent Harness Is More Than a Normal Agentic System

### Title
**What Agent Harness Adds Beyond a Normal Agentic System**

### Comparison Table

| Capability | Normal Agentic System | Agent Harness |
|---|---|---|
| Agent invocation | Agent calls tools directly | All calls go through typed Adapter Boundary |
| Response generation | Produces answer | Answer gated by Input/RAG/Output guardrails |
| RAG | May use RAG | RAG quality evaluated (groundedness, semantic, citation) and persisted |
| Audit | Limited or none | Full step-level audit trail persisted to SQLite per session |
| Lifecycle control | No concept | 4-state lifecycle: ACTIVE → REVIEW → QUARANTINED → DISABLED |
| Agent definition | Code only | Formal typed contract (schema, skills, tools, guardrails, hooks) |
| Agent registration | None | YAML manifest → registry → SQLite — survives restarts |
| Tool authorization | None | Tool invocation checked against policy permissions + data scopes |
| Policy engine | None | YAML-driven business policies, evaluated per tool invocation |
| Guardrails | Maybe output filter | 3-layer: input injection guard + RAG threshold guard + output disclaimer |
| Observability | Print logs | Structured events → SQLite + optional LangSmith trace |
| Cost tracking | None | Token counts + cost estimates from provider API, persisted per call |
| Third-party plugin governance | None | External agents onboarded via formal contract + adapter, same governance |
| Kill switch | None | Status change with required reason + approver + immutable event log |
| Degradation detection | None | RAG groundedness threshold monitoring → auto-triggers REVIEW |

### Architecture Diagram (Text)

```
NORMAL AGENTIC SYSTEM:              AGENT HARNESS:
                                    
User → Agent → LLM → Response       User → [InputGuardrail] → [ParentGraph]
                                              → registry_check
                                              → runtime_control_check
                                              → execute (via Adapter)
                                                  → [Agent + RAG + LLM]
                                              → [RAGGuard] → [LLMGuard]
                                              → [OutputGuardrail + Disclaimer]
                                              → [RAGEvaluator]
                                              → [UsageMeter]
                                              → [AuditStore.save()]
                                              → Response
```

### Speaker Notes
"Every single item in the right column exists in this codebase. It's not a future roadmap — it's running today. The key insight is that an agent harness is not about making agents smarter. It's about making agent deployments safe, observable, and governable. In a bank, you don't just need an agent that gives good answers. You need to know *when* it gave an answer, *what documents* it used, *whether those documents were relevant*, *who could stop it if it misbehaved*, and *whether that stop event was approved by the right person*. That's what this system provides."

---

## Slide 3: Agent Harness Architecture

### Title
**System Architecture: A Layered Governance Stack**

### Architecture Diagram (Text — use as basis for visual)

```
┌─────────────────────────────────────────────────────────┐
│                   REACT FRONTEND (Vite)                  │
│  ┌──────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────┐ │
│  │  Chat UI │ │  Loan   │ │Coll'ns  │ │Control Tower │ │
│  └──────────┘ └─────────┘ └─────────┘ └──────────────┘ │
└───────────────────────┬─────────────────────────────────┘
                        │ REST API
┌───────────────────────▼─────────────────────────────────┐
│                 FastAPI Application                       │
│              banking_agents/main.py                       │
│   ┌──────────────────────────────────────────────────┐  │
│   │          Parent LangGraph Runtime                │  │
│   │  registry_check → control_check → execute → end │  │
│   │  [traceable nodes → LangSmith if configured]    │  │
│   └──────────────────────┬───────────────────────────┘  │
│   ┌──────────────────────▼───────────────────────────┐  │
│   │              AGENT HARNESS CORE                  │  │
│   │  ┌──────────┐ ┌─────────────┐ ┌──────────────┐  │  │
│   │  │ Registry │ │  Adapters   │ │  Guardrails  │  │  │
│   │  │ Contracts│ │  Py|Graph   │ │  In/RAG/Out  │  │  │
│   │  │  YAML    │ │  REST|Hook  │ │  Business    │  │  │
│   │  └──────────┘ └─────────────┘ └──────────────┘  │  │
│   │  ┌──────────┐ ┌─────────────┐ ┌──────────────┐  │  │
│   │  │  Policy  │ │  KillSwitch │ │Observability │  │  │
│   │  │  Engine  │ │  Lifecycle  │ │+ LangSmith   │  │  │
│   │  └──────────┘ └─────────────┘ └──────────────┘  │  │
│   │  ┌─────────────────────────────────────────────┐ │  │
│   │  │  SQLite: audit.db + control_plane.db        │ │  │
│   │  └─────────────────────────────────────────────┘ │  │
│   └──────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                    DOMAIN AGENTS                          │
│  Policy Assistant │ Loan Assessment │ Collections Plugin  │
│  (RAG + Groq)     │ (RAG + Groq)   │ (Vendored workflow) │
└──────────┬────────┴───────┬─────────┴────────────────────┘
           │                │
┌──────────▼────────────────▼─────────────────────────────┐
│                 EXTERNAL SERVICES                         │
│  Groq API (llama-3.1-8b / 3.3-70b / whisper)            │
│  ChromaDB local (policy_docs, loan_docs collections)     │
│  LangSmith (optional, additive)                          │
└─────────────────────────────────────────────────────────┘
```

### Screenshot Placeholder
`[Screenshot: ControlTower overview page with component health indicators]`

### Speaker Notes
"The architecture has a deliberate layering principle: the harness core is domain-blind — it doesn't know about banking, loans, or collections. The domain knowledge lives in the agents and their YAML configurations. This separation means the same control plane can govern a credit scoring agent, a compliance checker, or a collections workflow without any changes to the core framework."

---

## Slide 4: Agent Primitives and Contracts

### Title
**Agent Contract: The Foundation of Harness Governance**

### Body Content

Every agent in the harness is defined by a formal, typed contract (`AgentContract` dataclass). The contract is the single source of truth for everything the harness needs to know to invoke, govern, and audit an agent.

### Code Snippet — Policy Assistant Contract (YAML)
```yaml
# banking_agents/config/agents/policy_assistant.yaml
agent_id: policy_assistant_agent
name: Policy Assistant Agent
owner: Retail Banking Policy
business_function: Policy Assistance
agent_type: internal
execution_mode: workflow
adapter_type: python_function
entrypoint: banking_agents.agents.control_plane_plugins.internal.policy_assistant

input_schema:
  type: object
  required: [query]
  properties:
    query: { type: string }

skills: [policy_retrieval, grounded_answering]
tools: [document_search]
guardrails: [prompt_injection, pii_leakage, regulatory_advice, business_scope]
model_preferences:
  primary: llama-3.1-8b-instant
  fallback: llama-3.3-70b-versatile
observability_hooks:
  execution_trace: true
  agent_run: true
  policy_decision: true
status: active
```

### Primitives Available Per Agent
| Primitive | Description | YAML Source |
|---|---|---|
| Skills | Business capabilities the agent can perform | `skills.yaml` |
| Tools | External functions the agent can invoke | `tools.yaml` |
| Memory Contracts | Scope-bound memory access rules | `memory_contracts.yaml` |
| Hooks | Pre/post invocation event hooks | `hooks.yaml` |
| Evaluators | RAG quality evaluator definitions | `evaluators.yaml` |
| Prompts | Versioned, hashed prompt packages | `prompts/` directory |

### Screenshot Placeholder
`[Screenshot: Agent Contract drawer open for policy_assistant_agent showing all sections]`

### Speaker Notes
"Think of the agent contract as the 'service level agreement' between the harness and the agent. When this agent is invoked, the harness knows exactly what tools it is allowed to use, what guardrails must be applied, what hooks will fire, and what observability data to collect — all before a single LLM call is made. This is what makes the system auditable and governable."

---

## Slide 5: Agent Catalog + Adapter / Plugin Model

### Title
**Agent Catalog: Governed Registration of Internal and External Agents**

### Registered Agents Table
| Agent | Type | Adapter | Business Domain |
|---|---|---|---|
| policy_assistant_agent | internal | python_function | Policy Assistance |
| loan_assessment_agent | internal | python_function | Loan Eligibility |
| collections_workflow_agent | **external_plugin** | python_function | Collections Ops |
| sample_external_agent | external | rest_api | Integration (demo) |
| sample_external_rest_agent | external | rest_api | Integration (demo) |
| sample_external_a2a_agent | external | a2a | Agent Interoperability |
| sample_github_wrapped_agent | external | python_function | Integration (demo) |
| demo_vendor_rest_agent | vendor | rest_api | Vendor (demo) |

### Adapter Pattern Diagram
```
Any Agent Source:
  ├── Internal Python function  → PythonFunctionAgentAdapter
  ├── LangGraph workflow        → LangGraphAgentAdapter
  ├── External REST API         → RestApiAgentAdapter
  └── External Webhook          → ExternalWebhookAgentAdapter
         ↓
  All adapters implement: invoke(payload, trace_id) → result
  All adapters enforce: timeout, tracing, error classification
```

**A2A addition:** external Agent2Agent-compatible agents use `A2AAgentAdapter` and are registered through `adapter_type: a2a`.

### The Plugin Model — Collections as Example
```yaml
# collections_workflow.yaml
agent_type: external_plugin
plugin_source: github_wrapped_workflow
entrypoint: banking_agents.external_plugins.collections_working_demo.wrapper.invoke
# This is a separately-developed system onboarded into the harness
# The harness governs it via contract — the plugin code is unchanged
```

### Screenshot Placeholder
`[Screenshot: Agent Registry page showing all 7 agents with status chips and adapter type]`

### Speaker Notes
"The adapter boundary is the key engineering insight here. It doesn't matter whether the agent is a Python function, a LangGraph graph, or an external REST API — the harness interacts with all of them through the same interface. This means we can onboard a third-party or legacy system into our governance framework without rewriting it. The Collections agent is a perfect example — it was a standalone system, and we've wrapped it in a contract and brought it under the harness without touching its core logic."

---

## Slide 5A: A2A Interoperability for Bank-Grade Agent Ecosystems

### Title
**A2A Gateway: Governed Agent-to-Agent Interoperability**

### Body Content

Agent Harness now exposes agents through an A2A gateway:

- `/.well-known/agent-card.json` for gateway discovery
- `/api/v1/a2a/agents/{agent_id}/card` for per-agent Agent Cards
- `/api/v1/a2a/message/send` for A2A message execution
- `/api/v1/a2a/rpc` for JSON-RPC style A2A calls
- `/api/v1/a2a/tasks` for persisted task review
- `adapter_type: a2a` for external vendor agents

### Why It Matters to the Bank

A2A allows the bank to participate in a multi-agent ecosystem without allowing unmanaged agent calls. Every A2A call is still routed through Agent Harness controls: contract validation, lifecycle status, RBAC, policy guardrails, audit, observability, and usage tracking.

### Screenshot Placeholder
`[Screenshot: /.well-known/agent-card.json showing EY Agent Harness Banking Gateway]`

### Speaker Notes
"This is the interoperability layer. If the bank has vendor agents, partner agents, or agents built on another framework, A2A gives us a standard communication pattern. The important part is that we do not expose raw agents. We expose governed agents through the harness."

---

## Slide 6: Runtime Execution Flow

### Title
**How a Request Moves Through the Harness: End-to-End Execution**

### Flow Diagram (Text)
```
User sends: "What are the KYC requirements for account opening?"
│
▼ POST /api/v1/chat
│
├─ InputValidator.validate()
│     Check: length ≥ 5, ≤ 2000, no injection patterns
│     ✓ PASS
│
├─ run_harness_graph() — Parent LangGraph
│   ├─ registry_check: agent=chat_orchestrator, known=True
│   ├─ runtime_control_check: status=ACTIVE
│   └─ execute_existing_runtime: HarnessOrchestrator.execute()
│         → AgentFleet.invoke("chat_orchestrator", payload)
│         → OrchestratorAgent.run()
│               → IntentClassifier: intent=POLICY
│               → PolicyRAGAgent.answer_with_evaluation()
│                     → BaseRAG.query(policy_docs, top_k=5)
│                     → RAGGuard.check() → ALLOW
│                     → Groq API: llama-3.1-8b-instant
│                     → evaluate_rag_response()
│                           groundedness=0.74, semantic=0.81
│                     → UsageMeter.record_llm_response()
│                           prompt_tokens=892, cost=$0.00089
│
├─ OutputValidator.validate()
│     Validate response, append intent disclaimer if needed
│     ✓ PASS
│
├─ AuditStore.save_session()
│     Persist: session_id, query, intent, audit_trail[], total_ms
│
└─ Return ChatResponse
```

### Timing Breakdown (Typical)
| Step | Component | Typical Time |
|---|---|---|
| Input validation | InputValidator | < 5ms |
| Graph overhead | LangGraph + harness | ~20ms |
| Intent classification | OrchestratorAgent | ~50ms |
| RAG retrieval | ChromaDB + embedding | 150–300ms |
| RAG guard | RAGGuard | < 5ms |
| LLM generation | Groq API | 1000–3000ms |
| RAG evaluation | Deterministic scores | 50–120ms |
| Audit persistence | SQLite | < 10ms |
| **Total** | End to end | **~1.5–4s** |

### Screenshot Placeholder
`[Screenshot: Audit trail expanded showing 6 steps with timing]`

### Speaker Notes
"Every step in this flow has a trace record. You can see the exact timing breakdown in the audit trail for any session. The Groq API call is the longest step — which is expected for LLM generation. Everything else in the harness adds less than 500ms of overhead for governance, evaluation, and audit. That's the cost of enterprise-grade safety — and we think it's worth it."

---

## Slide 7: Policy, Guardrails, and Cyber Controls

### Title
**Multi-Layer Guardrail System: Defence in Depth for AI Agents**

### Three-Layer Guardrail Architecture
```
Layer 1: INPUT GUARDRAIL
  ├── Min/max length check (5–2000 chars)
  └── Injection pattern scan:
       ✗ "ignore previous instructions"
       ✗ "act as [different AI]"
       ✗ "jailbreak"
       ✗ "pretend you are"
       → Raises HTTP 400, emits audit event

Layer 2: RAG GUARDRAIL (for retrieval agents)
  ├── hard_threshold: 1.2 → BLOCK if all docs too distant
  ├── soft_threshold: 0.9 → ALLOW + append disclaimer
  └── no_result fallback: return safe message if empty

Layer 3: OUTPUT GUARDRAIL
  ├── Empty response fallback
  └── Intent-based mandatory disclaimers:
       LOAN_ELIGIBILITY → "This assessment is indicative only.
                          Final eligibility subject to bank approval."
```

### Business Guardrails (YAML-configured)
| ID | Name | Risk |
|---|---|---|
| GRD-INJECT-001 | Prompt Injection | Critical |
| GRD-PII-001 | PII Leakage | High |
| GRD-PAY-001 | Payment Authorization | High |
| GRD-CUST-DATA-001 | Customer Data Access | High |
| GRD-CONDUCT-001 | Collections Conduct | High |
| GRD-SQL-001 | Unsafe SQL | Critical |
| GRD-REG-001 | Regulatory Advice | Medium |
| GRD-SCOPE-001 | Business Scope | Medium |

### Code Snippet — Injection Guard
```python
# banking_agents/guardrails/input_validator.py
for pattern in self.injection_patterns:
    if pattern in query_lower:
        emit_guardrail_event("input.injection_guard",
            f"Blocked: {pattern}", session_id)
        raise HTTPException(400,
            "Your request contains prohibited instructions.")
```

### Screenshot Placeholder
`[Screenshot: Policy Guardrails page showing rules table + recent events]`
`[Screenshot: Chat showing "Your request contains prohibited instructions" error]`

### Speaker Notes
"These guardrails are not advisory — they are enforced. If a user sends a prompt injection attempt, the query never reaches the LLM. The guardrail fires, writes an audit event, and returns an error. The guardrail events are visible in the control plane dashboard, searchable by session ID, and time-filtered. This is the difference between a demo system and an enterprise system — in an enterprise system, the failure modes are as important to design as the success paths."

---

## Slide 8: RAG Quality and Evidence Grounding

### Title
**RAG Quality Gate: Every Answer Is Evaluated for Evidential Grounding**

### RAG Quality Evaluation System
After every Policy Assistant response, the system automatically runs:

| Score | Method | What It Measures |
|---|---|---|
| Groundedness | Lexical token overlap (answer ∩ context) | Did the answer come from the documents? |
| Semantic Similarity | Cosine similarity via BERT embeddings | Is the answer semantically aligned with context? |
| Answer Relevance | Similarity of answer to original query | Did the answer address the question? |
| Citation Coverage | Cited chunks / Retrieved chunks | Were retrieved documents cited? |
| LLM Judge Score | Optional: Groq judging its own answer | External faithfulness check |
| Unsupported Claims | Sentences with <25% context overlap | Claims not grounded in evidence |

### Code Snippet — RAG Evaluator
```python
# banking_agents/evaluation/rag.py — evaluate_rag_response()
groundedness = _overlap(answer_tokens, context_tokens)   # lexical
semantic, method = _similarity(rag, answer, context)     # embedding if available
result = {
    "groundedness_score": round(groundedness, 4),
    "semantic_similarity_score": round(semantic, 4),
    "citation_coverage": round(len(citations)/max(1,len(citations)), 4),
    "source": "runtime",
    "is_simulated": False,
}
```

### Degradation Gate
If `groundedness_score < 0.6`, the degradation monitor can automatically transition the agent to `REVIEW` status — triggering a lifecycle governance event.

### Screenshot Placeholder
`[Screenshot: RAG Quality page showing scores for recent evaluations]`

### What Is Real vs Demo-Labeled
🟢 **Groundedness, Semantic Similarity, Citation Coverage** — computed deterministically on every call  
🔵 **LLM Judge Score** — only computed if `RAG_EVALUATOR_MODEL` env var is set (optional)  
🟢 **All scores persisted to SQLite** — queryable via API

### Speaker Notes
"In most RAG systems, you trust that the model used the retrieved documents — but you can't verify it. We added a verification layer. After every answer, we compute a groundedness score by checking how much of the answer text actually came from the retrieved policy documents. If the score drops below 0.6, the system can automatically flag the agent for review. This is the kind of quality gate that a compliance team would require in a production deployment."

---

## Slide 9: Kill Switch and Lifecycle Governance

### Title
**Agent Lifecycle: Controlled, Audited, Reversible**

### Four Agent States
```
ACTIVE      → Agent runs normally, all invocations proceed
     ↓
REVIEW      → Agent flagged for investigation (may block invocations)
     ↓
QUARANTINED → Agent isolated, all invocations blocked
     ↓  ↑
DISABLED    → Agent completely stopped
```

### Transition Rules
- Every transition requires: `reason`, `source`, `approved_by`, `override_type`
- Manual transitions are validated against allowed pairs
- State persists in SQLite — survives server restart
- Every change creates an immutable event record

### Code Snippet — Kill Switch
```python
# agent_harness/kill_switch.py
def change_status(self, agent_id, new_status, source, reason,
                  approved_by=None, override_type=None, ...):
    if not reason or not str(reason).strip():
        raise ValueError("reason is required")
    # Validate transition is allowed
    if manual and (old, new_status) not in ALLOWED_MANUAL_TRANSITIONS:
        raise ValueError(f"transition {old} → {new_status} not allowed")
    # Persist state + emit event
    self.registry.set_status(agent_id, new_status)
    self.store.execute(
        "INSERT INTO kill_switch_events(...) VALUES(...)",
        (agent_id, old, new_status, source, reason, approved_by, ...))
```

### Screenshot Placeholder
`[Screenshot: Kill Switch page showing lifecycle board with status changes]`
`[Screenshot: Kill switch event log showing agent_id, reason, approved_by, timestamp]`

### Speaker Notes
"The kill switch is not just a toggle button. Every status change requires a reason, an approver, and an override type. These are persisted as immutable records in SQLite. If a regulator asks 'who stopped this agent, when, and why' — that information is queryable from the database. If they ask 'when was it restarted and by whose approval' — that's there too. This is the audit trail that turns a demo into a compliance-ready system."

---

## Slide 10: Observability, Audit, and LangSmith

### Title
**Three-Layer Observability: Local → SQLite → LangSmith**

### Observability Architecture
```
Layer 1: In-Memory Ring Buffer
  harness_logger.get_recent(n=500)
  → Endpoint: GET /api/v1/harness/logs
  → Fast access to recent events

Layer 2: SQLite Persistence
  ControlPlaneStore tables:
    observability_events  → all harness events with type + payload
    agent_runs            → trace_id, agent, status, latency
    audit_sessions        → full step-level trail per session
    guardrail_events      → every guardrail trigger
    policy_decisions      → every policy engine decision
  → Endpoints: /control/events, /control/runs, /harness/audit

Layer 3: LangSmith (additive, optional)
  Parent graph: 4 nodes visible as LangSmith run
  Child spans: RAG pipeline steps, evaluation spans
  → Status: GET /api/v1/control/observability/status
  → Enabled by: LANGSMITH_TRACING=true + LANGSMITH_API_KEY
```

### What LangSmith Shows (when configured)
```
▶ run_harness_graph [parent]
    ▶ registry_check
    ▶ runtime_control_check
    ▶ execute_existing_runtime
        ▶ policy_assistant_flow
            ▶ receive_policy_query
            ▶ classify_intent
            ▶ rag_retrieval [retriever]
            ▶ compliance_review
            ▶ prompt_template_load
            ▶ prompt_render
            ▶ generate_policy_answer [llm]
            ▶ rag_evaluation
                ▶ groundedness_score
                ▶ semantic_similarity_score
                ▶ citation_coverage
    ▶ finalize_response
```

### Screenshot Placeholder
`[Screenshot: Observability page with event stream]`
`[Screenshot: LangSmith trace tree showing nested spans]`

### Speaker Notes
"We have two observability tracks that operate independently. The local SQLite track is always on — it doesn't require any external service, and it's the source of truth for the audit dashboard you're looking at. LangSmith is layered on top as an additive integration for development-time visibility. If LangSmith goes down, or if the API key isn't configured, absolutely nothing changes in the system's behavior. The local track continues independently. This is an important architectural decision for a regulated environment — your audit record doesn't depend on a third-party SaaS."

---

## Slide 11: Collections Agent Workflow Demo

### Title
**Collections Agent: A Vendored Workflow Governed by the Harness**

### What the Collections Agent Is
The Collections Agent is a separately-developed intelligence system, onboarded into the harness as an **external plugin** (`agent_type: external_plugin`, `plugin_source: github_wrapped_workflow`). The harness governs it without modifying its internal logic.

### Pre-Call Intelligence (Deterministic — 🟢 LIVE)
Five-score engine, evidence-based, no LLM required:
| Score | Basis |
|---|---|
| Account Risk | Days past due, DPD pattern, outstanding amount |
| Payment Propensity | Historical payment behavior, part-payment history |
| Contact Probability | Channel responsiveness, time-of-day pattern |
| Settlement Likelihood | Settlement history, account age |
| Escalation Risk | Legal flags, prior escalation events |

### Post-Call Analysis (LLM-powered — 🟢 LIVE when Groq configured)
- PTP (Promise-to-Pay) extraction
- Claim detection (hardship, dispute, settlement offer)
- Sentiment and stress analysis
- Trust gate: PASS / CONDITIONAL / BLOCK
- NBA (Next Best Action) recommendation

### Harness Controls Applied
```yaml
# collections_workflow.yaml
guardrails:
  - customer_data_access  # blocks unauthorized account lookups
  - pii_leakage           # blocks customer PII in output
  - payment_authorization # requires human approval for payments
  - collections_conduct   # enforces RBI guidelines
  - prompt_injection      # protects transcript analysis input
requires_human_approval_for: [settlement, waiver, trigger_legal]
max_auto_waiver_pct: 0
```

### Screenshot Placeholder
`[Screenshot: Collections workspace with pre-call 5-score panel and evidence breakdowns]`
`[Screenshot: Post-call analysis with PTP detection and claim classification]`

### What Is NOT Claimed
- Voice pipeline: Backend migrated, browser wiring pending
- Not claiming production telephony
- Not claiming autonomous payment or waiver decisions

### Speaker Notes
"The Collections agent is the most important demo in this deck because it shows what the harness is for. This is not an agent we built from scratch — it's a system that already existed in a standalone form. We onboarded it into the harness by writing a YAML contract and an adapter wrapper. The harness now controls its lifecycle, enforces its guardrails, tracks its usage, and produces an audit trail for every invocation — all without changing the Collections agent's own code."

---

## Slide 12: Policy Assistant / Loan Assessment Demo

### Title
**RAG Agents in Action: Policy Assistant and Loan Assessment**

### Policy Assistant — Key Demo Points
1. Query enters through InputGuardrail (injection check)
2. Small-talk detected → friendly redirect (no RAG invoked)
3. Policy query → ChromaDB retrieval (top-5 nearest)
4. RAGGuard applies distance threshold
5. Groq generates grounded answer
6. Low confidence detected → automatic fallback to 70B model
7. RAG evaluation runs: groundedness, semantic similarity, citation coverage
8. Audit trail persisted to SQLite
9. Token usage recorded with cost estimate

### Demo Query for Slide
```
Query: "What documents are required for a home loan application?"

Expected response structure:
  ✓ Grounded answer from loan policy documents
  ✓ Citations: [Source: loan_policy_v2.pdf, chunk 3]
  ✓ groundedness_score: 0.74
  ✓ semantic_similarity_score: 0.81
  ✓ citation_coverage: 1.0 (all chunks cited)
```

### Loan Assessment — Key Demo Points
1. Structured `CustomerLoanProfile` input (validated fields)
2. Pre-computed: FOIR, LTV, loan-to-income ratio
3. ChromaDB retrieval from loan_docs collection
4. Groq generates eligibility narrative
5. Output guardrail appends mandatory regulatory disclaimer (always)
6. Audit trail persisted with intent=LOAN_ELIGIBILITY

### Demo Profile for Slide
```
Loan Type: Home Loan | Employment: Salaried
Monthly Income: ₹75,000 | CIBIL: 720
Loan Amount: ₹40,00,000 | Tenure: 240 months
```

### Screenshot Placeholder
`[Screenshot: Loan Assessment form filled in with all fields]`
`[Screenshot: Assessment output showing eligibility + mandatory disclaimer]`

### Speaker Notes
"Notice the disclaimer at the bottom of every loan assessment response. It's not optional — it's applied by the output guardrail regardless of what the LLM generated. Even if the LLM forgot to include a caveat, the harness adds it. This is the difference between relying on the model to behave correctly and enforcing correct behavior at the system level."

---

## Slide 13: Code Implementation Strategy

### Title
**Engineering Approach: How We Built It and Why It Will Scale**

### Key Design Decisions

**1. Separation of Concerns: Harness vs. Domain**
```
agent_harness/   ← Generic, domain-blind control-plane framework
                    (no banking knowledge)
banking_agents/  ← Domain application (banking context)
                    (uses harness as a library)
```
This means the harness can be reused for any domain — credit scoring, compliance checking, HR automation.

**2. YAML-Driven Configuration**
```
All agent definitions → YAML manifests
All policies → YAML configuration files
All guardrail rules → YAML definitions
→ No code change required to add a new agent or modify a policy
```

**3. Adapter Pattern for Universal Agent Support**
```python
# Any agent source → same interface
BaseAgentAdapter.invoke(payload, trace_id) → result
```

**4. SQLite for Portable Persistence**
- No external database required for demo
- Full schema with migration support
- Ready to swap for PostgreSQL in production

**5. Additive, Non-Breaking Observability**
```python
# LangSmith is purely additive — no-op if not configured
if not LANGSMITH_SDK_AVAILABLE or not is_langsmith_enabled():
    # traceable becomes a pass-through decorator
    # local logging continues unchanged
```

**6. Typed Contracts with Validation**
```python
# Contracts validated before agent registration
validator = ContractValidator()
validator.validate_or_raise(contract)
# Missing fields → RuntimeError on startup, not at runtime
```

### Screenshot Placeholder
`[Screenshot: AgenticPrimitives page showing skills, tools, hooks, evaluators]`

### Speaker Notes
"The implementation strategy was 'add governance without breaking the agent'. Every design decision was made with the constraint that the existing agent code should not need to change. The guardrails, the audit store, the usage meter — these all wrap the agent execution without touching it. This is a critical property for a real enterprise deployment where you might be onboarding systems built by different teams with different tech stacks."

---

## Slide 14: What Is Real in the Demo vs. Demo-Seeded

### Title
**Transparency: What Is Live, What Is Seeded, What Is Demo-Only**

### Full Inventory Table

| Feature | Status | Explanation |
|---|---|---|
| Policy RAG answers | 🟢 LIVE | Real ChromaDB retrieval + real Groq API |
| Loan eligibility assessment | 🟢 LIVE | Real structured logic + real Groq API |
| Collections pre-call scoring | 🟢 LIVE | Deterministic evidence engine |
| Collections transcript analysis | 🟢 LIVE | Real Groq extraction (Groq key required) |
| RAG evaluation scores | 🟢 LIVE | Computed automatically after every response |
| Token + cost tracking | 🟢 LIVE | Provider-reported counts from Groq API |
| Guardrail injection blocking | 🟢 LIVE | Runs before every query |
| Kill switch lifecycle | 🟢 LIVE | Persists to SQLite, survives restart |
| Audit trail storage | 🟢 LIVE | SQLite, persisted per session |
| Agent contract registry | 🟢 LIVE | Loaded from YAML, stored in SQLite |
| ChromaDB collections | 🟡 SEEDED | Documents pre-ingested from ingestion scripts |
| Collections accounts | 🟡 SEEDED | Sample accounts in seeded SQLite DB |
| Sample transcripts | 🟡 SEEDED | Curated library of sample call transcripts |
| LangSmith integration | 🔵 CONDITIONAL | Active only if env vars configured |
| LLM Judge RAG score | 🔵 CONDITIONAL | Active only if RAG_EVALUATOR_MODEL set |
| Voice pipeline frontend | 🔴 DEMO-LABELED | Backend exists, browser wiring pending |
| Degradation simulation | 🔴 DEMO trigger | `/demo/simulate-degradation` creates test event |
| Unsafe SQL demo | 🔴 DEMO trigger | `/demo/run-unsafe-sql` triggers a demo guardrail event |

### What We Do NOT Claim
- Production-grade telephony
- Guaranteed LLM extraction accuracy
- Autonomous payment or waiver decisions
- Production database (SQLite is used for demo; PostgreSQL for production)
- Multi-tenancy or enterprise authentication

### Speaker Notes
"We are deliberately transparent about what is real and what is demo-seeded in this system. The ChromaDB collections are pre-ingested from real banking policy documents — but they need to be ingested before the demo runs. The Collections accounts are sample data. The voice pipeline has a working backend but the browser microphone wiring isn't complete yet. Everything else — the guardrails, the kill switch, the audit trail, the RAG evaluation — those are all running on real backend logic with every request."

---

## Slide 15: Future Roadmap

### Title
**What's Next: From Demo to Production**

### Roadmap Items

**Immediate (0–3 months):**
- [ ] Complete voice pipeline browser wiring (Groq Whisper STT + browser microphone)
- [ ] Add PostgreSQL support alongside SQLite (ControlPlaneStore abstraction is ready)
- [ ] LLM Judge activation for all RAG agents (env var configuration)
- [ ] Agent health check automation (scheduled, not on-demand only)

**Near-term (3–6 months):**
- [ ] Multi-agent orchestration with explicit task graph (LangGraph multi-agent)
- [ ] Role-based access control (RBAC) on control plane routes
- [ ] Policy engine rule editor UI (YAML editing via dashboard)
- [ ] External agent health monitoring with automatic REVIEW trigger
- [ ] Collections voice pipeline full end-to-end demo

**Production Hardening:**
- [ ] PostgreSQL migration (replace SQLite for multi-instance deployment)
- [ ] Authentication / JWT for all API routes
- [ ] Rate limiting and request queuing
- [ ] Formal API versioning and deprecation policy
- [ ] Expanded test coverage for all guardrail edge cases

**Additional Agents to Onboard:**
- [ ] Fraud Detection Agent (external_plugin model)
- [ ] Regulatory Compliance Checker (RAG agent)
- [ ] Credit Bureau Integration Agent (REST adapter)
- [ ] Document OCR + Verification Agent (LangGraph workflow)

### What the Architecture Already Supports (Without Code Changes)
- Adding new agents → create a YAML manifest
- Adding new guardrail rules → edit `guardrails.yaml`
- Adding new tools → edit `tools.yaml`
- Adding new policies → edit `banking_action_policies.yaml`
- Onboarding external systems → write an adapter wrapper

### Screenshot Placeholder
`[Screenshot: AgentRegistry showing currently registered agents as starting point for roadmap discussion]`

### Speaker Notes
"The architecture was designed with extension in mind. Adding a new agent requires writing a YAML manifest and, if needed, an adapter wrapper. Adding a new guardrail rule is a YAML edit. The framework doesn't need to change. This is what we mean when we say 'enterprise-grade' — the system is designed to grow without becoming unmaintainable. The roadmap items here are mostly about hardening, authentication, and wiring up the remaining integrations — not about fundamental rearchitecting."

---

## Appendix: Special Slide — Architecture Narrative for Non-Technical Stakeholders

### Title
**What Problem Does Agent Harness Solve?**

### The Problem
When an AI agent is deployed in a bank, the following questions immediately arise:
1. **Who is this agent? Who owns it?** → Agent Contract + Registry answers this
2. **What can it access? What tools can it use?** → Policy Permissions + Tool Authorization
3. **What if it starts giving bad answers?** → RAG Quality Gate + Degradation Monitor
4. **How do we stop it if something goes wrong?** → Kill Switch + Lifecycle Management
5. **Who approved stopping it? Why? When?** → Kill Switch Event Log
6. **What did it do today? Step by step?** → Audit Trail
7. **How much did it cost us to run?** → Usage Meter
8. **Can we bring in a vendor's system and govern it the same way?** → Adapter + Plugin Model

**The Agent Harness answers all 8 questions — for every agent, on every invocation.**

### The Promise
"Any AI agent that runs through the Agent Harness is fully governed, fully audited, and fully controllable — regardless of whether it was built internally, by a vendor, or wrapped from an open-source repository."

---

*Document prepared from source code inspection. All technical claims are verifiable against the repository at `demo-agent-harness/Backend/` and `demo-agent-harness/Frontend/`.*
