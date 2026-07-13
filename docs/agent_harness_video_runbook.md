# Agent Harness Video Recording Runbook

This is a presenter-ready recording guide. It is written as a sequence of scenes: what to show in the UI, what to say, what code file to open, which lines to highlight, and how to connect the UI behavior back to the implementation.

## Setup Before Recording

Open the app in the browser and keep these routes ready:

1. `/control/tower`
2. `/control/agents`
3. `/control/policy-guardrails`
4. `/control/observability`
5. `/control/audit-logs`
6. `/control/rag-quality`
7. `/control/usage-cost`
8. `/control/kill-switch`
9. `/chat`
10. `/loan-assessment`
11. `/collections`

Note: `/control/run-console` currently redirects to `/control/agents`, so do not present it as a separate screen unless you add a real page later.

Keep these VS Code tabs open in this order:

1. `Frontend/src/main.jsx`
2. `Frontend/src/services/controlPlaneApi.js`
3. `Frontend/src/api.js`
4. `Backend/banking_agents/control_routes.py`
5. `Backend/banking_agents/harness/runtime.py`
6. `Backend/banking_agents/config/agents/policy_assistant.yaml`
7. `Backend/agent_harness/contracts.py`
8. `Backend/agent_harness/registry.py`
9. `Backend/agent_harness/adapters.py`
10. `Backend/agent_harness/store.py`
11. `Backend/agent_harness/kill_switch.py`
12. `Backend/agent_harness/usage.py`
13. `Backend/agent_harness/observability.py`
14. `Backend/agent_harness/graph.py`

Use these demo inputs:

- Policy Assistant: `What are the KYC requirements for opening a new savings account?`
- Loan Assessment: keep the default HOME loan profile and run it.
- Collections: choose any prepared account, run pre-call automatically, select a transcript, then run post-call.
- Kill Switch: use `collections_workflow_agent`, move `active -> review` with reason `quality_or_safety_review_required`, then show that the Collections page reports the lifecycle block. If you need to reactivate, move `review -> active` with two distinct approvers and `reactivate_after_review`.

## Scene 1 - Explain Agent Harness Before Use Cases

Show: title slide or `/control/tower`.

Say:

"Before I show the individual use cases, I want to explain what Agent Harness actually is.

Most agent demos connect a user directly to an LLM, a workflow, or a chatbot. That is useful for experimentation, but it is not enough for a bank.

A bank needs a governed runtime. It needs to know which agents exist, who owns them, what they are allowed to do, which tools they can use, whether they are active or stopped, what evidence they used, what they cost, and whether they can be disabled immediately.

Agent Harness is that runtime and control plane. The business agents do the work, but the harness governs how they are registered, invoked, observed, audited, evaluated, and stopped."

Then say:

"The key message for this demo is simple: the user does not directly call an agent. The user calls the harness, and the harness governs the agent."

Switch to VS Code: `Frontend/src/main.jsx`, lines 27-46.

Say:

"Even at the routing level, the application is separated into two experiences. These routes under `/control/...` are the control plane. The routes `/chat`, `/loan-assessment`, and `/collections` are the business agent experiences."

Point to:

- Lines 29-41: control panel routes.
- Lines 44-46: business agent routes.

Return to UI: show the left navigation and the three fleet links.

## Scene 2 - Platform Shape: Control Plane and Agent Fleet

Show: `/control/agents`.

Say:

"This is the control plane. It is built for governance, operations, risk, compliance, and engineering teams.

The agent fleet is different. It is where business users interact with banking use cases such as policy support, loan assessment, and collections intelligence.

The important part is that both experiences are connected through the same backend control APIs."

Switch to VS Code: `Frontend/src/services/controlPlaneApi.js`, lines 1-8.

Say:

"The control panel API client centralizes calls under `/api/v1/control`. That means the UI is not managing governance by itself. It is calling the backend control plane."

Point to:

- Line 2: `PREFIX = '/api/v1/control'`.
- Lines 7-8: every request goes to that backend prefix.

Then show lines 26-57.

Say:

"Here are the operations the UI can call: list agents, retrieve contracts, get status, invoke agents, list events, list policy decisions, change lifecycle state, and run the three demo agents."

Point to:

- Lines 27-32: registry/status/invocation calls.
- Lines 35-40: events, evaluations, policy, guardrails.
- Lines 49-53: kill switch and degradation.
- Lines 54-57: policy, loan, and collections demo runs.

Switch to backend: `Backend/banking_agents/control_routes.py`, lines 148-188.

Say:

"Those frontend calls land here in FastAPI. The `/agents` endpoint reads the registry. The `/agents/{agent_id}/contract` endpoint returns the governed contract. The `/agents/{agent_id}/invoke` endpoint invokes the agent through the control plane."

Point to:

- Lines 148-149: list registered agents.
- Lines 158-172: contract view.
- Lines 186-188: governed invocation endpoint.

Return to UI: open an agent drawer in `/control/agents`.

Say:

"So when I open an agent here, I am looking at data from the registry and the persisted evidence store, not a static UI card."

## Scene 3 - Agent Registry

Show: `/control/agents`.

UI action:

1. Point to the registered agents list.
2. Open `Policy Assistant Agent`.
3. Point to owner, business function, adapter type, status, tools, permissions, latest policy/evidence sections.

Say:

"This is the Agent Registry. The registry is the system of record for agents onboarded into the platform.

Instead of treating agents as untracked scripts, the harness gives each agent an identity, owner, business function, risk tier, runtime adapter, permissions, guardrails, model policy, and lifecycle state.

For enterprise AI, this is the first control: knowing which agents exist and how they are configured."

Switch to VS Code: `Frontend/src/pages/control/AgentRegistry.jsx`, lines 10-23.

Say:

"The drawer fetches the contract, health, tool authorization, policy decisions, and guardrail events."

Point to:

- Lines 14-16: fetch contract/agent detail.
- Lines 18-23: fetch health, authorization, policy, and guardrail evidence.

Show lines 75-80.

Say:

"These visible fields in the drawer come from the contract: identity, ownership, business function, adapter, entrypoint, status, and latest lifecycle event."

Show lines 82-126.

Say:

"This is where the UI connects contract metadata to runtime evidence: declared tools, allowed actions, data scopes, runtime authorization status, latest tool authorization, latest policy decision, and latest guardrail event."

Switch to `Backend/banking_agents/config/agents/policy_assistant.yaml`, lines 1-28.

Say:

"This YAML file is the formal contract for the Policy Assistant. It declares the agent ID, owner, business function, risk tier, adapter type, entrypoint, schemas, tools, prompts, evaluators, hooks, model settings, permissions, budget, guardrails, observability, and status."

Point to:

- Lines 1-6: identity, owner, business function, risk tier.
- Lines 8-11: runtime type, execution mode, adapter, entrypoint.
- Lines 13-16: input, output, state, and memory schemas.
- Lines 18-22: skills, tools, prompts, evaluators, hooks.
- Lines 23-27: model, permissions, budget, guardrails, observability.
- Line 28: lifecycle status.

Switch to `Backend/agent_harness/registry.py`, lines 19-51.

Say:

"The registry loads these contracts from config, validates them, restores persisted lifecycle state, stores the contract, initializes metrics, persists the contract view, and builds adapters when needed."

Point to:

- Lines 19-24: load and validate contracts.
- Lines 27-35: restore persisted lifecycle state.
- Lines 37-40: persist agent and contract records.
- Lines 48-51: create adapter from the contract.

Return to UI.

Say:

"That is the connection: this drawer is the visible control-plane view of the YAML contract, the registry, and the persisted runtime evidence."

## Scene 4 - Runtime Path: What Happens When an Agent Runs

Show: `/control/tower` or `/control/agents`.

Say:

"The runtime has four major stages: registry check, lifecycle and control check, adapter execution, and finalization with evidence capture."

Switch to `Backend/banking_agents/harness/runtime.py`, lines 54-90.

Say:

"This file initializes the control-plane runtime. It wires together the store, tracer, usage meter, budget manager, contract validator, registry, authorization service, MCP governance, primitives, policy engine, kill switch, degradation monitor, LLM judge, and tool authorization service."

Point to:

- Lines 56-63: store, services, usage, budget, contract validator, registry.
- Lines 64-71: authorization and MCP governance.
- Lines 73-79: primitives, hooks, policy, kill switch, degradation.
- Lines 83-89: LLM risk judge and tool authorization.

Show lines 105-120.

Say:

"When an invocation starts, the runtime creates an invocation ID, trace ID, timestamp, policy and guardrail containers, and the principal identity."

Show lines 300-345.

Say:

"These helper methods are the runtime control path: resolve the contract, validate the contract, resolve the adapter, validate input, verify lifecycle status, evaluate policy, and run input guardrails."

Point to:

- Lines 300-304: resolve agent contract.
- Lines 306-312: validate contract.
- Lines 314-321: resolve adapter.
- Lines 323-330: validate input schema.
- Lines 332-336: lifecycle check.
- Lines 338-345: policy and input guardrails.

Show lines 194-230.

Say:

"Only after those checks does the runtime start the run, invoke the adapter, run output guardrails, collect evaluators, and record usage."

Point to:

- Lines 194-200: trace and audit context, run started.
- Lines 202-218: adapter invocation.
- Lines 224-228: output guardrails.
- Lines 230-232: evaluator and usage collection.

Show lines 235-255.

Say:

"After execution, it persists the completed run, records metrics, emits trace provider events, evaluates degradation, checks kill-switch action, emits hooks, and returns a structured invocation result."

Return to UI: show any recent event page.

Say:

"That is why after running a business agent, we can return to the control plane and see evidence. The UI is not just showing the response; it is showing what the runtime captured."

## Scene 5 - Adapter Boundary

Show: agent drawer in `/control/agents`, point to adapter type.

Say:

"The harness does not require every agent to be implemented the same way. The common requirement is that every agent sits behind a governed adapter boundary."

Switch to `Backend/agent_harness/adapters.py`, lines 34-83.

Say:

"This is the Python function adapter. The contract entrypoint is resolved, invoked with a trace ID, wrapped in tracing, normalized into a dictionary, and protected by timeout handling."

Point to:

- Lines 34-38: Python adapter resolves the entrypoint.
- Lines 43-51: traced function call and normalized result.
- Lines 57-67: timeout-controlled synchronous invocation.
- Lines 69-83: async invocation support.

Show lines 86-109.

Say:

"This is the LangGraph adapter. A graph workflow can be governed by the same harness contract."

Show lines 112-160.

Say:

"This is the REST API adapter. External agents can be invoked over HTTP while still using the harness for lifecycle, policy, audit, observability, and usage controls."

Show lines 204-236.

Say:

"This A2A adapter shows the same pattern for agent-to-agent services. The external protocol changes, but the governance boundary remains the same."

Return to UI.

Say:

"The key point is that Agent Harness standardizes governance without forcing every team to rebuild its agent in one framework."

## Scene 6 - Policy Assistant: Business Agent Plus Control Evidence

Show: `/chat`.

UI action:

1. Enter: `What are the KYC requirements for opening a new savings account?`
2. Submit.
3. Point to answer, sources, governed response badge, evidence-backed badge, trace/session indicator.

Say:

"This is the Policy Assistant. It supports employees who need fast, evidence-backed answers from internal policy documents.

The business value is faster policy lookup and more consistent interpretation. The governance value is that the response is tied to evidence and traceable through the harness."

Switch to `Frontend/src/pages/ChatPage.jsx`, lines 16-23.

Say:

"These suggested prompts show the type of banking policy questions this screen is designed for: KYC, dormant accounts, account closure, payments, and nominee updates."

Show lines 69-109.

Say:

"The UI renders governance badges when a response is governed, evidence-backed, and trace recorded."

Point to:

- Lines 69-73: governed, evidence-backed, trace-recorded conditions.
- Lines 78-106: visible badges.

Show lines 286-311.

Say:

"When the user sends a question, the page calls the frontend API, stores the session ID, displays the final answer, and keeps the RAG evaluation and citations with the response."

Switch to `Frontend/src/api.js`, lines 32-74.

Say:

"The frontend does not call a chatbot endpoint directly. It calls `/api/v1/control/demo/run-policy-agent`, then uses the returned trace ID to fetch control-plane events."

Point to:

- Lines 32-36: policy agent call through control endpoint.
- Lines 38-41: fetch trace events.
- Lines 66-74: return answer, audit trail, trace ID, RAG evaluation, citations.

Switch to `Backend/banking_agents/control_routes.py`, lines 696-697.

Say:

"That API maps to the policy assistant agent ID and invokes it through the control plane."

Switch to `Backend/banking_agents/harness/runtime.py`, lines 397-414.

Say:

"For RAG-style outputs, the runtime collects evaluator results and records usage. This is what later appears in RAG Quality and Usage & Cost."

Return to UI: open `/control/rag-quality`.

Say:

"Now I return to the control panel. The response we just generated has quality evidence: grounding, semantic similarity, answer relevance, citation coverage, and the trace that ties it back to the run."

Open `/control/observability`.

Say:

"And here are runtime events. This shows that the agent execution is inspectable, not hidden behind a chatbot response."

## Scene 7 - Loan Assessment: Structured Decision Support

Show: `/loan-assessment`.

UI action:

1. Show the structured form.
2. Keep default HOME profile.
3. Run assessment.
4. Point to result, warning that it is indicative only, RAG quality gate, submitted profile.
5. Click or point to `View Control Panel`.

Say:

"The Loan Assessment Agent demonstrates how agentic workflows can support structured lending decisions.

The objective is not to replace final credit authority. The objective is to gather information, apply rules, evaluate factors, generate a recommendation, and present reasoning in a consistent format."

Switch to `Frontend/src/pages/LoanAssessmentPage.jsx`, lines 11-42.

Say:

"The frontend validates the lending inputs before sending them to the backend: loan type, employment type, age, income, CIBIL score, loan amount, tenure, property value, EMI, interest rate, and additional context."

Show lines 118-130.

Say:

"These are the prepared default demo values, so the recording can run smoothly without typing everything live."

Show lines 149-171.

Say:

"On submit, the UI builds a structured profile and calls the loan assessment API."

Switch to `Frontend/src/api.js`, lines 77-82.

Say:

"The frontend calls `/api/v1/control/demo/run-loan-assessment`. Again, this goes through the control plane."

Switch to `Backend/banking_agents/control_routes.py`, lines 700-701.

Say:

"The backend maps that demo endpoint to `loan_assessment_agent` and invokes it through the same runtime."

Switch to `Backend/banking_agents/config/agents/loan_assessment.yaml`, lines 1-26.

Say:

"The loan agent has its own contract: different owner, business function, high risk tier, Python function entrypoint, tools such as document search and eligibility checker, model settings, human approval for final approval, budget policy, and guardrails."

Return to UI: open `/control/policy-guardrails`, `/control/audit-logs`, or `/control/observability`.

Say:

"After the loan run, the control plane has policy decisions, guardrail events, trace events, and audit evidence. The business screen shows the recommendation; the control plane shows how that recommendation was governed."

## Scene 8 - Collections Intelligence: Workflow Agent Under the Same Harness

Show: `/collections`.

UI action:

1. Select a prepared account.
2. Let pre-call run.
3. Point to five-score engine, persona/context, risk flags, recommended NBA.
4. Select a transcript.
5. Run post-call.
6. Point to post-call output, audit history tab, and any control evidence.

Say:

"The Collections Intelligence Agent demonstrates a governed workflow for delinquency and recovery operations.

Collections teams need account context, payment behavior, contact history, risk flags, willingness to pay, ability to pay, and the next best action. This agent brings those signals together, but the harness governs the execution."

Switch to `Frontend/src/pages/CollectionsAgentPage.jsx`, lines 58-85.

Say:

"On page load, the UI fetches accounts, transcripts, and the current lifecycle status of `collections_workflow_agent`."

Show lines 87-107.

Say:

"The pre-call and post-call actions both call control-plane APIs, not a direct workflow function."

Show lines 119-133.

Say:

"The page then separates business output from control evidence. It can show account intelligence, scoring, persona, post-call analysis, and also lifecycle or policy block evidence."

Show lines 163-171.

Say:

"If the harness blocks the agent or the agent is in review, the business UI reflects that state and links the user back to lifecycle controls."

Switch to `Frontend/src/services/controlPlaneApi.js`, lines 57-75.

Say:

"Collections uses the same control-plane API client. It calls `/demo/run-collections`, plus endpoints for accounts and transcripts."

Switch to `Backend/banking_agents/control_routes.py`, lines 704-719.

Say:

"The backend accepts multiple collection modes, normalizes the payload, and invokes `collections_workflow_agent` through the control plane."

Switch to `Backend/banking_agents/config/agents/collections_workflow.yaml`, lines 1-11, then 76-133.

Say:

"This contract is different from the policy and loan agents: it represents a collections workflow with its own owner, risk tier, entrypoint, tools, prompts, permissions, budget policy, and guardrails. Different business workflow, same harness."

Return to UI: open `/control/observability` and `/control/audit-logs`.

Say:

"Now the governance evidence from the workflow is visible in the control plane. This is the proof that business agents and operational controls are connected."

## Scene 9 - Observability vs Audit

Show: `/control/observability`.

Say:

"Observability answers operational questions: which agent ran, when it ran, which step executed, whether it succeeded, how long it took, which trace or session it belongs to, and where a failure occurred."

Switch to `Backend/banking_agents/control_routes.py`, lines 604-649.

Say:

"The observability status endpoint reports whether LangSmith is active, but the local SQLite store remains the source of truth. LangSmith is additive; local events are still written."

Point to:

- Lines 615-627: integration status.
- Lines 643-648: local store note.

Switch to `Backend/agent_harness/observability.py`, lines 22-34.

Say:

"At the framework level, observability emits structured events with component, action, status, and metadata."

Switch to `Backend/agent_harness/store.py`, lines 18, 77, and 92-100.

Say:

"The store persists observability events and runtime phase events. This is why the control panel can reconstruct execution traces."

Show: `/control/audit-logs`.

Say:

"Audit is different. Observability is for engineering and operations. Audit is for compliance and accountability. It reconstructs what happened, what decision was made, and why."

## Scene 10 - Usage and Cost

Show: `/control/usage-cost`.

Say:

"Usage and cost tracking becomes important when agents scale. The platform needs visibility into which agents, models, and business functions consume AI resources."

Switch to `Backend/banking_agents/control_routes.py`, lines 234-263.

Say:

"These routes power the Usage & Cost page: summary, events, and budget definitions."

Switch to `Backend/agent_harness/usage.py`, lines 111-143.

Say:

"The usage meter records provider, model, tokens, estimated cost, source, latency, status, fallback, and metadata, then persists the record to `usage_events`."

Switch to `Backend/agent_harness/store.py`, line 25.

Say:

"The usage table stores the detailed usage record: trace, run, agent, model, tokens, estimated cost, latency, fallback, status, timestamp, and metadata."

Return to UI.

Say:

"So cost is not an afterthought. It is part of the governed operating model."

## Scene 11 - Kill Switch: Runtime-Enforced Lifecycle Control

Show: `/control/kill-switch`.

UI action:

1. Select `collections_workflow_agent`.
2. Show current state.
3. Target state: `review`.
4. Reason: `quality_or_safety_review_required`.
5. Approved by: `ops_admin`.
6. Change ticket: `CHG-CONTROL-001`.
7. Apply lifecycle change.
8. Show timeline event.

Say:

"The kill switch is not just a UI button. It is part of the runtime control path.

If an agent is moved to review, quarantined, or disabled, the harness checks that lifecycle state before execution and can block the adapter from running.

For a bank, this is critical. If an agent begins producing unsafe, low-quality, non-compliant, or operationally incorrect output, the bank should not need to redeploy code. An authorized lifecycle change should be enough to stop or control execution."

Switch to `Frontend/src/pages/control/KillSwitchDegradation.jsx`, lines 184-224.

Say:

"The UI keeps track of selected agent, target lifecycle state, reason, approver, second approver, override type, and change ticket. It also prevents invalid transitions before submission."

Show lines 270-286.

Say:

"When I apply the override, the page calls `changeAgentStatus` with source `manual_admin` and triggered_by `audited_control_panel`."

Switch to `Frontend/src/services/controlPlaneApi.js`, line 52.

Say:

"That frontend action maps to `/kill-switch/{agent_id}`."

Switch to `Backend/banking_agents/control_routes.py`, lines 661-689.

Say:

"The backend endpoint requires a reason, passes approver, severity, override type, evidence, change ticket, and second approver into the kill switch service, and exposes kill-switch events back to the UI."

Switch to `Backend/agent_harness/kill_switch.py`, lines 5-14.

Say:

"The service defines allowed manual transitions. Notice that reactivation is controlled: stopped agents move through review before returning to active."

Show lines 19-53.

Say:

"The transition function validates the reason, validates the target status, reads the old status, checks manual approval fields, enforces two approvers for reactivation, validates allowed transitions, and updates the registry state."

Show lines 56-66.

Say:

"Then it records lifecycle evidence, inserts a kill-switch event, emits a `KILL_SWITCH_EVENT`, emits `LIFECYCLE_STATUS_CHANGED`, and returns the payload."

Switch to `Backend/banking_agents/harness/runtime.py`, lines 332-336.

Say:

"This is the enforcement point. Before adapter execution, the runtime checks lifecycle status. Disabled and quarantined agents are blocked before business logic runs."

Show lines 417-433.

Say:

"When blocked by policy or lifecycle state, the runtime records a blocked result, adds an `INVOCATION_BLOCKED` event, and does not invoke the adapter."

Return to UI: open `/collections` and select/run a case if the agent is in review.

Say:

"Now I return to the business UI. The collections agent is affected by the lifecycle state set in the control plane. This demonstrates the connection between governance UI, backend lifecycle service, runtime enforcement, and business experience."

If reactivating:

Show `/control/kill-switch`, move `review -> active`.

Say:

"To return the agent to service, reactivation requires review, an approved override type, a change ticket, and two distinct approvers. That gives the bank an accountable recovery path."

## Scene 12 - Persistence: Evidence Is Stored, Not Just Displayed

Show: `/control/audit-logs` or `/control/observability`.

Say:

"The control plane is not a temporary dashboard. Runtime evidence is stored."

Switch to `Backend/agent_harness/store.py`, lines 15-32.

Say:

"These tables show the control-plane persistence model: agents, runs, observability events, policy decisions, guardrail events, kill-switch events, RAG evaluations, usage events, tool authorization events, invocations, and runtime phase events."

Point to:

- Line 15: agents.
- Line 17: agent runs.
- Line 18: observability events.
- Line 19: policy decisions.
- Line 20: guardrail events.
- Line 21: kill switch events.
- Line 24: RAG evaluations.
- Line 25: usage events.
- Lines 30-32: authorization decisions, invocations, runtime phases.

Show lines 92-100.

Say:

"Each runtime phase can be persisted and also mirrored into observability events. This is how the control plane can show the execution trail after the run completes."

Return to UI.

Say:

"The UI is a view over persisted control-plane evidence."

## Scene 13 - Optional Parent Graph Explanation

Use this only if you want to explicitly show the graph abstraction. If time is short, skip this scene because `runtime.py` already proves the main path.

Switch to `Backend/agent_harness/graph.py`, lines 72-132.

Say:

"This parent graph makes the common runtime stages explicit: registry check and runtime control check."

Point to:

- Lines 72-96: registry check.
- Lines 99-132: runtime control check.

Show lines 135-174.

Say:

"The execution node delegates to the existing runtime, and if the agent is blocked it short-circuits without calling business logic."

Show lines 177-216.

Say:

"Finalization records status, and the graph assembly links registry check, runtime control check, execution, and finalization."

## Scene 14 - Final Architecture Summary

Show: `/control/tower`, then briefly switch between `/chat`, `/loan-assessment`, `/collections`, and back to `/control/observability`.

Say:

"Now the complete picture is visible.

The Policy Assistant, Loan Assessment Agent, and Collections Intelligence Agent are different business agents. They have different purposes, workflows, risk levels, and implementation details.

But they are governed by the same operating layer: contracts, registry, lifecycle checks, policy and guardrails, adapter execution, observability, audit, RAG quality, usage, cost, and kill switch.

That is the difference between building an AI agent and operating an agent estate."

## Scene 15 - EY Value Proposition

Show: closing slide or `/control/tower`.

Say:

"For EY, Agent Harness can become a reusable accelerator for responsible agentic AI adoption in banking.

The proposition is not limited to implementing one agent. EY can help banks identify use cases, assess risk and control needs, design the operating model, deploy the harness foundation, onboard agents through formal contracts, implement lifecycle and policy controls, integrate audit and observability, define human oversight, track quality and cost, and scale toward an enterprise agent factory.

In simple terms, this is a reusable pattern for helping banks move from AI experimentation to governed AI operations."

## Closing Script

Say:

"So the business value is not only that we built a Policy Assistant, Loan Assessment Agent, and Collections Intelligence Agent.

The larger value is that we built the operating layer around them.

Agent Harness gives EY a reusable pattern for helping banks safely scale agentic AI.

Agents are onboarded through formal contracts. They run through a governed runtime. Every execution can be observed. Important decisions can be audited. Evidence quality and model usage can be measured. Lifecycle state can be controlled. Agents can be stopped when operational, compliance, or risk conditions require it.

That is the difference between building individual AI agents and operating an enterprise agent estate.

For clients, this provides a path from isolated pilots to a scalable, governed agent factory. For EY, it creates a repeatable consulting and implementation proposition across banking use cases."

## Short Version If You Need to Compress the Video

Use this 8-scene path:

1. Explain Agent Harness: governed operating layer, not just agents.
2. Show routes: `main.jsx` lines 27-46, control plane vs agent fleet.
3. Show registry UI, then `policy_assistant.yaml` lines 1-28 and `registry.py` lines 19-51.
4. Run Policy Assistant, then show `api.js` lines 32-74 and `control_routes.py` lines 696-697.
5. Show runtime: `runtime.py` lines 300-345 and 194-230.
6. Run Loan and Collections quickly, then return to Observability/Audit/RAG/Usage.
7. Demonstrate Kill Switch: UI -> `controlPlaneApi.js` line 52 -> `control_routes.py` lines 661-689 -> `kill_switch.py` lines 19-66 -> `runtime.py` lines 332-336.
8. Close with EY value proposition.

## Repeatable One-Liners

Use these throughout:

- "The real product is not only the agents. It is the operating layer around the agents."
- "The user does not directly call an agent. The user calls the harness, and the harness governs the agent."
- "Agent contracts turn AI agents into managed enterprise assets."
- "The harness standardizes governance without forcing every agent to use the same implementation framework."
- "Observability explains runtime behavior. Audit reconstructs governance and accountability."
- "The kill switch is enforced by the runtime, not only represented in the UI."
- "The platform moves from 'the model answered' to 'the answer had evidence.'"
- "This is the difference between an AI pilot and an enterprise operating model."
- "This is the difference between building an agent and operating an agent estate."

## Things To Avoid Saying

Avoid:

- "This is just a demo."
- "This page is only for UI."
- "We hard-coded this."
- "This is a simple chatbot."
- "The agent decides everything."
- "The model is always correct."
- "This replaces human approval."
- "Everything is fully production-ready."

Prefer:

- "This is a working accelerator and reference implementation."
- "The platform demonstrates the core operating model."
- "The architecture is extensible toward enterprise integrations."
- "Human approval can remain part of the workflow."
- "The harness provides runtime and governance controls around model behavior."
- "Production deployment would integrate with the client's IAM, model platform, observability stack, and data estate."

## Production Roadmap Answer

If asked whether this is production-ready, say:

"This implementation demonstrates the key platform capabilities and the target operating model.

For client production deployment, the same architecture can be extended with enterprise IAM and RBAC, centralized secrets management, managed databases, enterprise observability, SIEM integration, model gateways, approval workflows, policy administration, data-loss prevention, production-grade vector stores, Kubernetes or another managed runtime, model-risk management controls, resilience, disaster recovery, and enterprise API management."

## Final One-Sentence Story

Agent Harness allows a bank to treat AI agents as governed enterprise assets rather than isolated applications.
