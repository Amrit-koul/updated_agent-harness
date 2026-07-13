# Codebase Implementation Audit

Repository audited: `D:\Projects\Final_AgentHarness`  
Scope: FastAPI backend, React frontend, LangGraph wrappers, YAML contracts, SQLite persistence, adapters, guardrails, lifecycle controls, observability, and demo PowerPoint source `doc4_ppt_content.md`.  
Constraint followed: no application code was modified; this file is the only artifact created.

## Executive Summary

The repository contains two overlapping harness/control-plane paths:

1. Legacy/runtime chat path in `Backend/banking_agents/main.py` using `agent_harness.HarnessOrchestrator`, `AgentFleet`, `AgentCatalog`, `agent_harness.graph.run_harness_graph`, legacy `agent_registry`, and `audit_store`.
2. Manifest-driven control-plane path in `Backend/banking_agents/control_routes.py` and `Backend/banking_agents/harness/runtime.py`, which loads YAML manifests from `Backend/banking_agents/config/agents/*.yaml`, builds adapters from `Backend/agent_harness/adapters.py`, persists to `Backend/data/control_plane.db`, and is what most current React control pages call.

The control-plane runtime is substantially implemented and wired for Python-function agents, REST agents, policy checks, guardrail checks, lifecycle events, RAG evaluation, local observability, usage metering, and audit persistence. Several capabilities are partial or config-only: memory contracts are catalogued but not enforced, tool authorization exists but is not automatically applied to every tool used inside agent code, external-webhook adapter code exists but no webhook manifest is registered, RBAC and token-budget enforcement are missing, MCP integration is missing, and some UI controls are demos or evidence viewers rather than true production controls.

The current PowerPoint is broadly accurate for the live demo story, but it overstates "all calls go through typed Adapter Boundary" for the legacy `/api/v1/chat` and `/api/v1/loan/assess` path, overstates tool authorization as per-tool runtime enforcement for ordinary invocations, lists LangGraph and external-webhook adapters as part of the adapter surface although no registered agent currently uses them, and does not mention that RBAC, token budgets, MCP, and external-webhook manifests are absent.

## Capability Matrix

| # | Capability | Status | Exact implementation location | Active caller or route | Persisted data involved | Test coverage | Shortcomings | PowerPoint accuracy |
|---|---|---|---|---|---|---|---|---|
| 1 | Control-plane runtime | LIVE_AND_WIRED | `Backend/banking_agents/harness/runtime.py` `ControlPlaneRuntime`, singleton `control_plane`; `Backend/banking_agents/control_routes.py` router prefix `/api/v1/control` | `POST /api/v1/control/agents/{agent_id}/invoke`, demo routes, collections routes, policy/tool/lifecycle APIs | `Backend/data/control_plane.db`: `agents`, `agent_contracts`, `agent_runs`, `observability_events`, `policy_decisions`, `guardrail_events`, `kill_switch_events`, `degradation_events`, `rag_evaluations`, `usage_events`, `tool_authorization_events`, `agent_memory` | `Backend/tests/test_observability.py::test_control_and_collections_trace_names` exercises `control_plane.invoke` for collections | Separate legacy `/api/v1/harness/*` and `/api/v1/chat` path still exists; no auth/RBAC; singleton initializes at import | Mostly accurate, but deck glosses over duplicate legacy/control paths |
| 2 | Parent LangGraph runtime or graph wrapper | PARTIAL | `Backend/agent_harness/graph.py` `_parent_graph`, `run_harness_graph`, nodes `registry_check`, `runtime_control_check`, `execute_existing_runtime`, `finalize_response` | Only legacy routes `POST /api/v1/chat` and `POST /api/v1/loan/assess` in `Backend/banking_agents/main.py` call `run_harness_graph` | Local observability via `Backend/agent_harness/observability.py`; legacy audit in `Backend/data/audit.db` for session save | `Backend/test_harness.py` smoke script; `Backend/tests/test_observability.py` traces names for domain agents, not graph route end-to-end | New manifest-driven `/api/v1/control/*` path does not use this parent graph; it uses span tracing inside `ControlPlaneRuntime.invoke` | Partially accurate; deck implies parent graph wraps the main harness architecture generally, but it is not on `/api/v1/control/*` |
| 3 | Agent registry | LIVE_AND_WIRED | `Backend/agent_harness/registry.py` `AgentRegistry.load`, `get_contract`, `get_adapter`, legacy `agent_registry`; manifests in `Backend/banking_agents/config/agents/*.yaml` | `ControlPlaneRuntime.__init__` loads manifests; `GET /api/v1/control/agents`; legacy `GET /api/v1/harness/agents` uses legacy registry entries | `agents`, `agent_contracts`; in-memory `_contracts`, `_adapters`, `_metrics`; legacy `_legacy` registry | Indirect in `test_control_and_collections_trace_names`; no focused registry tests | Registry contains compatibility legacy state and manifest state in same class; duplicate path can confuse kill-switch semantics | Accurate for YAML registry, incomplete about legacy compatibility registry |
| 4 | Agent contract schema | LIVE_AND_WIRED | `Backend/agent_harness/contracts.py` `AgentContract`, `AgentStatus`; validation in `Backend/agent_harness/contract_validator.py`; API shape in `GET /api/v1/control/agents/{agent_id}/contract` | Registry load on runtime startup; contract API; adapter factory | `agent_contracts.contract_json`, `source_file` | No dedicated contract validator unit tests | Only checks field presence and adapter type; does not validate JSON Schema semantics, enum values, prompt/tool existence, or output schema conformance | Mostly accurate; "typed contract" exists, but schema enforcement is shallow |
| 5 | Primitive catalog | LIVE_AND_WIRED | `Backend/agent_harness/primitives.py` `PrimitiveCatalog`; YAML files `skills.yaml`, `tools.yaml`, `memory_contracts.yaml`, `hooks.yaml`, `evaluators.yaml`; prompt scan under `Backend/banking_agents/prompts` | `GET /api/v1/control/skills`, `/tools`, `/memory/contracts`, `/hooks`, `/evaluators`, `/prompts`, `/primitives/validation` | No dedicated primitive tables; derived from YAML and manifests; events for hooks in `observability_events` | Prompt registry tests cover prompt packages; no primitive catalog test | Catalog is read-only; validation reports warnings but does not block invocation; several collections manifest tool/skill names are not present in YAML | Accurate as a catalog; not an enforcement layer by itself |
| 6 | Memory contracts | PARTIAL | Config `Backend/banking_agents/config/memory_contracts.yaml`; runtime memory methods `Backend/agent_harness/base_adapter.py` `load_memory`, `save_memory`; API `GET /api/v1/control/memory/contracts`, `/memory/events` | Catalog APIs only; adapter memory methods are available but not used by current wrappers found via `rg` | `agent_memory(agent_id, entity_id, memory_json, updated_at)` | No tests found | Retention, redaction, encryption, access policy, allowed agent IDs are declared but not enforced; no active agent call chain uses `save_memory` | Deck accurately says contracts exist, but overstates governance if read as enforced memory policy |
| 7 | Skills and tools registry | PARTIAL | `Backend/banking_agents/config/skills.yaml`, `tools.yaml`; `PrimitiveCatalog.list_skills/list_tools`; `ToolAuthorizationService` references tools | UI/API registry is live; `/tools/authorize` checks declared tools | YAML only plus `tool_authorization_events` when authorization API is called | No tests for skills/tools authorization | Registry definitions do not automatically wrap actual Python tool calls inside legacy/domain agents; collections manifest references tools not in `tools.yaml` (`collections_context_loader`, `transcript_analyzer`, etc.) | Partially accurate; registry exists, enforcement is not universal |
| 8 | Python-function adapter | LIVE_AND_WIRED | `Backend/agent_harness/adapters.py` `PythonFunctionAgentAdapter`; factory in `plugin_loader.py`; manifests `policy_assistant.yaml`, `loan_assessment.yaml`, `collections_workflow.yaml`, `sample_github_wrapped_agent.yaml` | `ControlPlaneRuntime.invoke` -> `registry.get_adapter` -> `adapter.invoke_async`; demo policy/loan/collections routes | `agent_runs`, `usage_events`, `policy_decisions`, `guardrail_events`, RAG/events depending agent | `test_control_and_collections_trace_names`; RAG tests for policy/loan internals | Input validation only checks required keys, not types; output schema not validated; adapter timeout works but no cancellation of underlying non-cooperative function beyond thread future cancel | Accurate |
| 9 | LangGraph adapter | IMPLEMENTED_NOT_WIRED | `Backend/agent_harness/adapters.py` `LangGraphAgentAdapter`; supported in `ContractValidator.ADAPTERS` and `plugin_loader.ADAPTER_TYPES` | No manifest in `Backend/banking_agents/config/agents/*.yaml` uses `adapter_type: langgraph` | None unless a future manifest uses it | No tests found | Code exists but no active registered agent uses it; collections manifest says `internal_orchestration: langgraph` while adapter type is `python_function` | Deck overstates it as an active adapter option in the current estate |
| 10 | REST adapter | LIVE_AND_WIRED | `Backend/agent_harness/adapters.py` `RestApiAgentAdapter`; manifests `demo_vendor_rest_agent.yaml`, `sample_external_rest_agent.yaml`, `sample_external_agent.yaml`; mock app `Backend/banking_agents/external_plugins/mock_vendor_rest_agent/app.py` | `POST /api/v1/control/agents/demo_vendor_rest_agent/invoke`; onboarding UI invokes demo vendor REST agent | `agent_runs`, `usage_events`, policy/guardrail events; external endpoint response | No focused tests; UI has demo invocation | Requires local mock at `127.0.0.1:9001`; `sample_external_rest_agent` requires `SAMPLE_EXTERNAL_AGENT_API_KEY`; no live server startup in app | Accurate if demo-labeled |
| 11 | External-webhook adapter | IMPLEMENTED_NOT_WIRED | `Backend/agent_harness/adapters.py` `ExternalWebhookAgentAdapter`; factory supports `external_webhook`; health reads `HEARTBEAT` events | No registered manifest uses `adapter_type: external_webhook`; heartbeat route exists for any registered agent | Would use `observability_events` heartbeat rows; none wired to webhook manifest | No tests found | No webhook contract, no delivery-specific endpoint, no retry/queue semantics beyond REST parent | Deck overstates by listing Hook adapter as available in active architecture |
| 12 | Policy engine | LIVE_AND_WIRED | `Backend/banking_agents/policy/control_plane.py` `BankPolicyEngine.check`; `Backend/banking_agents/guardrails/business.py`; route `POST /api/v1/control/policy/check` | Every `ControlPlaneRuntime.invoke` calls pre-policy and post-policy; manual `/policy/check` route | `policy_decisions`, `guardrail_events`, `observability_events` | Indirect collections trace test; no policy matrix unit tests | YAML `banking_action_policies.yaml` is mainly used by tool authorization, not `BankPolicyEngine`; policy engine is deterministic regex/status/scope rather than fully YAML-driven | Partially accurate; "YAML-driven business policies" is stronger than implementation |
| 13 | Tool permissions | PARTIAL | `Backend/banking_agents/policy/tool_authorization.py` `ToolAuthorizationService`; routes `POST /api/v1/control/tools/authorize`, `GET /tools/authorization-events`; demo unsafe SQL route | Explicit tool authorization API; `POST /api/v1/control/demo/run-unsafe-sql`; not automatically called for normal agent tool use | `tool_authorization_events`, `observability_events` | No tests found | Ordinary control-plane invocation checks action/status/data scope at agent level but not every declared tool call; no runtime interception inside domain tools | Deck overstates this as all tool invocations checked |
| 14 | Guardrails | LIVE_AND_WIRED | Legacy input/output: `Backend/banking_agents/guardrails/input_validator.py`, `output_validator.py`; control business guardrails: `Backend/banking_agents/guardrails/business.py`; RAG guard in domain agents; control route `/guardrails` | Legacy `/api/v1/chat`, `/api/v1/loan/assess`; control `BankPolicyEngine.check`; tool auth; demo unsafe SQL | Legacy `audit.db.guardrail_events` when saved; control `guardrail_events`, `policy_decisions` | Tests cover redaction and traced agent flows, not guardrail edge cases | Control `/guardrails` returns static list; config names and business regex are not fully unified; output schema not enforced | Mostly accurate, with caveat that guardrail catalog endpoint is static |
| 15 | Lifecycle and kill switch | LIVE_AND_WIRED | `Backend/agent_harness/kill_switch.py` `KillSwitchService.change_status`; `BankKillSwitchService.apply_guardrail`; routes `POST /api/v1/control/kill-switch/{agent_id}`, `GET /kill-switch/events`; legacy toggle in `main.py` `/api/v1/harness/agents/{agent_name}/toggle` | Control-plane invoke checks status through policy; manual UI page calls status change; unsafe SQL/degradation demos can transition | `agents.status`, `kill_switch_events`, `observability_events` | Indirect in collections trace test; no lifecycle transition unit tests | Two kill switch paths exist: manifest lifecycle and legacy toggle; manual route requires `reason`, `approved_by`, `override_type`, but UI must provide them; legacy toggle is weaker and in-memory | Accurate for control path, not for legacy toggle path |
| 16 | Degradation monitoring | LIVE_AND_WIRED | `Backend/agent_harness/degradation_monitor.py` `DegradationMonitor.evaluate`; config `degradation_rules.yaml`; route `/demo/simulate-degradation`, `/degradation/events` | Called after policy block, success, and failure in `ControlPlaneRuntime.invoke`; demo simulate route | `degradation_events`, `kill_switch_events`; latest RAG eval from `rag_evaluations` | No dedicated tests | Rolling metrics are in-memory and reset on process restart except lifecycle status; only RAG agents checked by hardcoded `RAG_AGENT_IDS`; success code path calls `evaluate(agent_id)` without passing `trace_id` | Deck is mostly accurate but should label degradation simulation and in-memory metric limits |
| 17 | RAG quality evaluation | LIVE_AND_WIRED | `Backend/banking_agents/evaluation/rag.py` `evaluate_rag_response`; wrappers persist via `control_plane.store.add_rag_evaluation` in `Backend/banking_agents/agents/control_plane_plugins/internal.py`; APIs `/evaluations` | Policy/loan control demo routes; domain agents `PolicyRAGAgent.answer_with_evaluation`, `LoanEligibilityRAGAgent.answer_with_evaluation` | `rag_evaluations` with query hash and metadata JSON | `test_policy_agent_uses_versioned_prompt`, `test_loan_agent_structured_path`; no store assertion | Optional LLM judge only if env configured; quality gate computed in API response, not enforced to block the original response except degradation later | Accurate with optional judge caveat |
| 18 | Observability and tracing | LIVE_AND_WIRED | `Backend/agent_harness/tracing.py`, `trace_provider.py`, `observability.py`; local store via `ControlPlaneStore.add_event`; route `/observability/status` | Control-plane invoke spans; hooks emit to `observability_events`; legacy logger in `Backend/banking_agents/observability/logger.py` | `observability_events`, `agent_runs`; optional LangSmith not persisted as URL | Tests in `test_observability.py` cover no-op tracing and trace names | LangSmith conditional; no trace URL persisted; two observability systems (legacy logger/ring + control store) | Accurate if optional LangSmith is understood |
| 19 | Audit persistence | LIVE_AND_WIRED | Control: `Backend/agent_harness/store.py`; legacy: `Backend/agent_harness/audit.py`; collections domain DB models | Control routes `/runs`, `/events`; legacy `/api/v1/harness/audit`; collections `/history` | `control_plane.db`, `audit.db`, `collections_domain.db` tables listed above | Limited; no DB persistence tests except indirect runtime | Audit split across multiple DBs; no centralized trace joining between legacy audit sessions and control-plane runs | Accurate but should note split stores |
| 20 | Usage and cost metering | LIVE_AND_WIRED | `Backend/agent_harness/usage.py` `UsageMeter`; config `model_pricing.yaml`; domain calls in `PolicyRAGAgent`, `LoanEligibilityRAGAgent`; runtime fallback records unknown/external usage | `ControlPlaneRuntime.invoke`; APIs `/usage/summary`, `/usage/events`; UI Usage Cost page | `usage_events` | No focused tests | Collections/external usage often recorded as `provider: external/unknown`, `model: unknown`, no token counts; pricing config is demo estimates | Deck overstates "provider-reported counts" for all calls; true for Groq RAG calls when provider returns usage, fallback elsewhere |
| 21 | Third-party heartbeat/event ingestion | LIVE_AND_WIRED | Routes `POST /api/v1/control/agents/{agent_id}/heartbeat`, `POST /api/v1/control/events/ingest`; `ExternalWebhookAgentAdapter.get_health` can read heartbeat | Any registered agent can heartbeat or ingest event; no UI form found | `observability_events` event types `HEARTBEAT`, external event type | No tests | Heartbeat/event APIs do not authenticate source; no webhook adapter manifest consumes heartbeat health; event ingestion only stores payload | Deck mentions third-party governance generally; heartbeat ingestion is underrepresented |
| 22 | Model configuration | PARTIAL | Agent manifests `model_preferences`; `Backend/banking_agents/config/model_gateway.yaml`, `model_pricing.yaml`; actual model use in `PolicyRAGAgent`, `LoanEligibilityRAGAgent`, collections voice/extraction code | Domain agents read their own settings/model IDs; usage pricing reads `model_pricing.yaml` | `usage_events.model`; no model config table | Tests patch model IDs and Groq clients | `model_gateway.yaml` is not centrally enforced by `ControlPlaneRuntime`; no model allowlist/routing layer in adapter boundary | Deck mostly accurate about configured Groq models, overstates central gateway behavior |
| 23 | Agent identity and RBAC | PARTIAL | Identity fields in `AgentContract`: `agent_id`, `owner`, `business_function`; no RBAC middleware/routes found | Contract/registry UI displays identity; all FastAPI routes are unauthenticated | `agent_contracts`, `agents` | None | No user identity, role checks, route protection, operator audit identity except free-form `approved_by` body | Deck roadmap correctly lists RBAC as future; current identity contract is live but RBAC missing |
| 24 | Token-budget configuration and enforcement | MISSING | No `token_budget` config/enforcement found; only usage metering estimates tokens in `UsageMeter` | None | `usage_events.total_tokens` after calls | None | No per-agent/request budget, no pre-call budget check, no budget kill/review trigger | Deck does not claim token budgets; cost tracking claims are narrower |
| 25 | MCP integration | MISSING | No backend MCP server/client/config found by `rg "MCP|mcp"` except unrelated prompt text; no manifests mention MCP | None | None | None | No MCP tool registry or connector runtime | Not represented in PPT; omission is accurate for current code |
| 26 | Frontend pages representing capabilities | PARTIAL | Routes in `Frontend/src/main.jsx`; API clients `Frontend/src/services/controlPlaneApi.js`, `Frontend/src/api.js`; pages under `Frontend/src/pages/control/*`, `ChatPage.jsx`, `LoanAssessmentPage.jsx`, `CollectionsAgentPage.jsx` | React pages call `/api/v1/control/*`; old `DashboardPage.jsx` calls `/api/v1/harness/*` but `/dashboard` redirects to `/control/tower` | Reads backend tables through APIs; local UI state only | No frontend tests found | Some views are registry/evidence viewers only; fake/demo controls exist for unsafe SQL, degradation simulation, vendor invoke; no UI for heartbeat/event ingestion, RBAC, token budgets, MCP, model gateway config | Deck accurately claims 10+ views, but some are demo/evidence views rather than full operational controls |

## Duplicate, Conflicting, Static, and Dead Surfaces

### Duplicated registry/runtime/harness implementations

- `Backend/agent_harness/*` is the reusable/generic harness package used by both paths.
- `Backend/banking_agents/harness/*` duplicates many filenames (`runtime.py`, `registry.py`, `policy_engine.py`, `kill_switch.py`, `degradation_monitor.py`, `contracts.py`, `adapters.py`, etc.). The live `ControlPlaneRuntime` imports mostly from `agent_harness`, while `banking_agents/harness/runtime.py` is the bank-specific bootstrap.
- `Backend/agent_harness/registry.py` contains both manifest registry state (`_contracts`, `_adapters`, `_metrics`) and legacy compatibility state (`_legacy`).
- `Backend/banking_agents/main.py` creates a legacy `HarnessOrchestrator` with `AgentFleet`/`AgentCatalog`, while `Backend/banking_agents/harness/runtime.py` creates the manifest-driven control plane.

### Conflicting control-plane paths

- Legacy customer routes:
  - `POST /api/v1/chat` -> `run_harness_graph` -> legacy `HarnessOrchestrator`.
  - `POST /api/v1/loan/assess` -> `run_harness_graph` -> legacy `HarnessOrchestrator`.
- Current frontend customer routes:
  - `Frontend/src/api.js` sends chat to `POST /api/v1/control/demo/run-policy-agent`, not `/api/v1/chat`.
  - `Frontend/src/api.js` sends loan assessment to `POST /api/v1/control/demo/run-loan-assessment`, not `/api/v1/loan/assess`.
- Legacy ops routes:
  - `/api/v1/harness/agents`, `/audit`, `/metrics`, `/governance`, `/logs`, `/kill-switch-log`, `/health`.
- Current ops routes:
  - `/api/v1/control/*`.
- Old `Frontend/src/pages/DashboardPage.jsx` still targets `/api/v1/harness/*`, but `Frontend/src/main.jsx` redirects `/dashboard` to `/control/tower`.

### Hardcoded demo data and seeded data

- `Frontend/src/pages/LoanAssessmentPage.jsx` has a prefilled `INIT` applicant profile.
- `Frontend/src/pages/ChatPage.jsx` has hardcoded suggested prompts.
- `Backend/banking_agents/collections_domain/data/accounts.json` is seeded collections portfolio data.
- `Backend/banking_agents/external_plugins/collections_working_demo/samples/*.json` are curated sample transcripts.
- `Backend/banking_agents/config/agents/demo_vendor_rest_agent.yaml` points to local mock `http://127.0.0.1:9001/invoke`.
- `Backend/banking_agents/control_routes.py` demo routes:
  - `/demo/run-policy-agent`
  - `/demo/run-loan-assessment`
  - `/demo/run-collections`
  - `/demo/run-unsafe-sql`
  - `/demo/simulate-degradation`

### Static status values and static catalog values

- `GET /api/v1/control/guardrails` returns a hardcoded list in `Backend/banking_agents/control_routes.py`, not a fully parsed guardrail registry.
- `PrimitiveCatalog.validation()` returns warnings but never blocks registration or invocation.
- `ControlTower.jsx` labels some cards as "config metadata only".
- REST health is on-demand; no scheduler updates persistent health status.

### Fake or demo UI controls

- `Frontend/src/pages/control/KillSwitchDegradation.jsx` can trigger demo unsafe SQL and simulated degradation via `/demo/*`.
- `Frontend/src/pages/control/Agentcontract.jsx` includes a vendor REST demo invocation for `demo_vendor_rest_agent`.
- Several screens display evidence when rows exist but do not configure backend behavior: primitives, memory contracts, hooks, evaluators.

### Dead or low-use routes

- `/api/v1/chat` and `/api/v1/loan/assess` are live backend routes but bypassed by the current frontend.
- `/api/v1/harness/*` routes are live but mostly bypassed by current navigation.
- `Frontend/src/pages/control/Runconsole.jsx` imports and uses control APIs, but `Frontend/src/main.jsx` does not register a route for it.
- `ExternalWebhookAgentAdapter` is implemented but has no manifest using it.

### Schemas with fields without enforcement

- `AgentContract.input_schema` required fields are enforced by `BaseAgentAdapter.validate_input`; property types and JSON Schema constraints are not.
- `AgentContract.output_schema`, `state_schema`, and `memory_schema` are not validated at runtime.
- `memory_contracts.yaml` declares retention, encryption, redaction, and access policy but these are not enforced.
- `observability_hooks` determine which hooks are shown/emit some lifecycle events, but disabled hook points like `pre_tool`/`post_tool` are not wired into actual tool calls.
- `model_gateway.yaml` is present but not a central enforced gateway.

### Backend capabilities missing from UI

- `POST /api/v1/control/agents/{agent_id}/heartbeat`
- `POST /api/v1/control/events/ingest`
- `GET /api/v1/control/agents/{agent_id}/health` is visible in registry drawer but not used as a monitoring workflow.
- Direct `POST /api/v1/control/policy/check`
- Full `POST /api/v1/control/tools/authorize` form; UI mainly displays events and demo unsafe SQL.
- Collections live voice endpoints `/collections/voice/start`, `/turn`, `/finalize` are not represented in `CollectionsAgentPage.jsx`.

### UI claims unsupported or only partially supported by backend

- "Runtime Auth Status" in `AgentRegistry.jsx` infers runtime enforcement from latest tool authorization event; absence means no evidence, not necessarily no enforcement.
- Collections control evidence section expects fields such as `lifecycle_status`, `adapter_invoked`, `usage_mode`, `policy_decision`, `guardrails_evaluated`; wrapper results mainly return `control_evidence` extraction/scoring fields unless blocked.
- Tool authorization and policy matrix screens may imply per-tool interception, but ordinary agent invocation does not automatically call `ToolAuthorizationService.authorize`.

## Complete Request Path Traces

### A. Policy assistant request

Primary frontend path:

`Frontend/src/ChatPage.jsx` -> `api.chat()` in `Frontend/src/api.js` -> `POST /api/v1/control/demo/run-policy-agent`
-> `Backend/banking_agents/control_routes.py::demo_policy`
-> `_invoke_control_plane("policy_assistant_agent", ...)`
-> `ControlPlaneRuntime.invoke` in `Backend/banking_agents/harness/runtime.py`
-> registry `AgentRegistry.get_contract("policy_assistant_agent")`
-> contract `Backend/banking_agents/config/agents/policy_assistant.yaml`
-> pre-policy/guardrail `BankPolicyEngine.check` -> `BankingBusinessGuardrails.evaluate`
-> adapter `PythonFunctionAgentAdapter` from `Backend/agent_harness/adapters.py`
-> underlying function `Backend/banking_agents/agents/control_plane_plugins/internal.py::policy_assistant`
-> runtime dependency `banking_agents.main._require_runtime()` -> `main.orchestrator.tool_instances["consult_policy_expert"]`
-> domain agent `Backend/banking_agents/agents/domain/policy_rag_agent.py` `answer_with_evaluation`
-> RAG retrieval via policy RAG, RAG guard, Groq generation, optional fallback
-> evaluation `Backend/banking_agents/evaluation/rag.py::evaluate_rag_response`
-> usage `UsageMeter.record_llm_response` in policy agent and fallback external/unknown record if none exists
-> persist `rag_evaluations`, `observability_events`, `policy_decisions`, `guardrail_events`, `agent_runs`, `usage_events`
-> post-policy output review in `ControlPlaneRuntime.invoke`
-> response `{trace_id, agent_id, result}` to frontend.

Legacy backend path still exists:

`POST /api/v1/chat` -> `InputValidator.validate` -> `run_harness_graph` -> legacy `HarnessOrchestrator.execute("chat_orchestrator")` -> `OrchestratorAgent.run()` -> policy tool -> output validator -> `audit_store.save_session` in `audit.db`. Current frontend does not use this route.

### B. Loan-assessment request

Primary frontend path:

`Frontend/src/LoanAssessmentPage.jsx` -> `api.loanAssess()` -> `POST /api/v1/control/demo/run-loan-assessment`
-> `control_routes.py::demo_loan`
-> `_invoke_control_plane("loan_assessment_agent", body)`
-> `ControlPlaneRuntime.invoke`
-> registry contract `loan_assessment_agent`
-> contract `Backend/banking_agents/config/agents/loan_assessment.yaml`
-> `BankPolicyEngine.check` and `BankingBusinessGuardrails.evaluate`
-> `PythonFunctionAgentAdapter`
-> `Backend/banking_agents/agents/control_plane_plugins/internal.py::loan_assessment`
-> `main.loan_agent.answer_with_evaluation`
-> `Backend/banking_agents/agents/domain/loan_eligibility_rag_agent.py`
-> profile validation/eligibility calculations/RAG/Groq
-> `evaluate_rag_response`
-> `UsageMeter.record_llm_response`
-> `control_plane.store.add_rag_evaluation` and `LOAN_ASSESSMENT_GENERATED` event
-> `ControlPlaneRuntime` post-policy output review, run completion, degradation evaluate
-> response `{trace_id, agent_id, result}`.

Legacy backend path still exists:

`POST /api/v1/loan/assess` -> `InputValidator` if query -> legacy `agent_registry.is_enabled("consult_loan_expert")` -> `run_harness_graph("loan_agent")` -> legacy `HarnessOrchestrator` -> `loan_agent.answer` -> `OutputValidator` -> legacy `audit_store.save_session`. Current frontend does not use this route.

### C. Collections-agent request

Frontend path:

`Frontend/src/CollectionsAgentPage.jsx`
-> `controlPlaneApi.runCollectionsPreCall/PostCall/FullLifecycle`
-> `POST /api/v1/control/demo/run-collections`
or `POST /api/v1/control/collections/{account_id}/post-call`
-> `control_routes.py::demo_collections` or `collections_post_call`
-> `_invoke_control_plane("collections_workflow_agent", payload)`
-> `ControlPlaneRuntime.invoke`
-> registry contract `collections_workflow_agent`
-> contract `Backend/banking_agents/config/agents/collections_workflow.yaml`
-> `BankPolicyEngine.check` and business guardrails
-> `PythonFunctionAgentAdapter`
-> `Backend/banking_agents/external_plugins/collections_working_demo/wrapper.py::invoke`
-> mode dispatch:
   - `pre_call` -> `run_account_workflow` in `Backend/banking_agents/collections_domain`
   - `post_call` -> transcript resolution -> `transcript_extraction.extract` -> `process_recorded_call`
   - `full_lifecycle` -> pre-call then post-call
   - `voice_greet`/`voice_analyze` -> voice/extraction helpers
-> collections DB persistence in `Backend/data/collections_domain.db` tables such as `call_history`, `review_cases`, `claims`, `score_history`, `trust_audit_logs`, `ptp_history`
-> no RAG evaluation for collections
-> usage fallback record by `ControlPlaneRuntime` if no LLM usage event exists
-> `agent_runs`, `policy_decisions`, `guardrail_events`, `observability_events`, `usage_events`
-> post-policy output review and degradation evaluation
-> response `{trace_id, agent_id, result}`.

### D. External REST agent invocation

UI/demo path:

`Frontend/src/pages/control/Agentcontract.jsx`
-> `controlPlaneApi.invokeAgent("demo_vendor_rest_agent", {query: ...})`
-> `POST /api/v1/control/agents/demo_vendor_rest_agent/invoke`
-> `control_routes.py::invoke_agent`
-> `ControlPlaneRuntime.invoke`
-> registry contract `demo_vendor_rest_agent`
-> contract `Backend/banking_agents/config/agents/demo_vendor_rest_agent.yaml`
-> `BankPolicyEngine.check` and business guardrails
-> `RestApiAgentAdapter` in `Backend/agent_harness/adapters.py`
-> HTTP `POST http://127.0.0.1:9001/invoke` with `trace_id`
-> mock underlying agent `Backend/banking_agents/external_plugins/mock_vendor_rest_agent/app.py::invoke` if separately running
-> no RAG evaluation
-> usage fallback external/unknown record
-> `agent_runs`, `policy_decisions`, `guardrail_events`, `usage_events`, `observability_events`
-> post-policy output review
-> response `{trace_id, agent_id, result}` or adapter connection/config error mapped by `_invoke_control_plane`.

### E. External webhook agent invocation

Current status: no complete active path.

Implemented code path if a manifest existed:

`POST /api/v1/control/agents/{webhook_agent}/invoke`
-> `ControlPlaneRuntime.invoke`
-> manifest with `adapter_type: external_webhook`
-> `ExternalWebhookAgentAdapter.invoke`
-> inherited REST POST to manifest endpoint
-> response wrapped as `{accepted: True, delivery: ..., trace_id}`
-> run/usage/event persistence.

Actual repository evidence:

- Adapter exists in `Backend/agent_harness/adapters.py`.
- Factory supports it in `Backend/agent_harness/plugin_loader.py`.
- `ContractValidator` accepts `external_webhook`.
- No YAML manifest under `Backend/banking_agents/config/agents` uses `adapter_type: external_webhook`.
- Therefore request path E is `IMPLEMENTED_NOT_WIRED`, not live.

### F. Kill-switch transition

Manual path:

`Frontend/src/pages/control/KillSwitchDegradation.jsx`
-> `controlPlaneApi.changeAgentStatus(agentId, body)`
-> `POST /api/v1/control/kill-switch/{agent_id}`
-> `control_routes.py::kill_switch`
-> `BankKillSwitchService.change_status` inherited from `Backend/agent_harness/kill_switch.py`
-> registry `get_contract`, validate target `AgentStatus`, validate manual requirements for `source in {"manual","manual_admin","admin_validation"}` (`reason`, `approved_by`, `override_type`)
-> `AgentRegistry.set_status`
-> persist `agents.status`
-> insert `kill_switch_events`
-> insert `observability_events` event types `KILL_SWITCH_EVENT` and `LIFECYCLE_STATUS_CHANGED`
-> response with previous/new status and evidence.

Automatic path:

`ToolAuthorizationService` or `BankPolicyEngine` emits critical guardrail event
-> `BankKillSwitchService.apply_guardrail`
-> `change_status` to `review` or `quarantined`
-> same persistence.

Legacy path:

`POST /api/v1/harness/agents/{agent_name}/toggle`
-> legacy `agent_registry.toggle`
-> in-memory `_legacy.enabled` and `_events`; not the same persisted lifecycle mechanism.

### G. Third-party heartbeat

`POST /api/v1/control/agents/{agent_id}/heartbeat`
-> `control_routes.py::heartbeat`
-> `control_plane.registry.get_contract(agent_id)` validates registration
-> trace ID from body or generated UUID
-> `control_plane.store.add_event("HEARTBEAT", trace_id, agent_id, body)`
-> persist row in `observability_events`
-> response `{agent_id, status, heartbeat: "accepted", trace_id, timestamp}`.

Webhook health code path if used:

`GET /api/v1/control/agents/{agent_id}/health`
-> `registry.get_adapter(agent_id).get_health()`
-> for `ExternalWebhookAgentAdapter`, latest `HEARTBEAT` row is compared with `metadata.health_check.max_heartbeat_age_seconds`.

No current webhook manifest uses this health behavior.

### H. External event ingestion

`POST /api/v1/control/events/ingest`
-> `control_routes.py::ingest_event`
-> require `agent_id` and `registry.exists(agent_id)`
-> trace metadata via `_trace_metadata`
-> `get_tracer().trace("Agent Control Plane Event ...")`
-> `control_plane.store.add_event(event_type, trace_id, agent_id, body["payload"])`
-> persist to `observability_events`
-> response `{ingested: true, trace_id, event_type}`.

There is no adapter invocation, policy check, tool authorization, RAG evaluation, usage metering, or lifecycle evaluation in this ingestion route. It is audit/event storage, not execution.

## Frontend Screen Coverage

| Screen | File | Backend support | Classification |
|---|---|---|---|
| Policy Assistant chat | `Frontend/src/pages/ChatPage.jsx` | Calls `/api/v1/control/demo/run-policy-agent`; displays citations/RAG evidence lightly | LIVE_AND_WIRED |
| Loan Assessment | `Frontend/src/pages/LoanAssessmentPage.jsx` | Calls `/api/v1/control/demo/run-loan-assessment`; displays RAG quality gate | LIVE_AND_WIRED |
| Collections Intelligence | `Frontend/src/pages/CollectionsAgentPage.jsx` | Calls collections control demo, accounts, transcripts, history, status | LIVE_AND_WIRED for pre/post transcript demo; PARTIAL for live voice |
| Control Tower | `Frontend/src/pages/control/ControlTower.jsx` | Aggregates agents, policy, guardrails, kill, degradation, tool auth | LIVE_AND_WIRED evidence dashboard |
| Agent Registry | `Frontend/src/pages/control/AgentRegistry.jsx` | Lists agents, contract drawer, health, tool auth/policy/guardrail evidence | LIVE_AND_WIRED with inferred enforcement caveat |
| Agent Contract / Onboarding | `Frontend/src/pages/control/Agentcontract.jsx` | Contract viewer plus demo REST invocation | PARTIAL / demo action |
| Policy Guardrails | `Frontend/src/pages/control/PolicyGuardrails.jsx` | Reads guardrail static list, events, decisions, tool auth | PARTIAL because catalog list is static |
| Kill Switch / Degradation | `Frontend/src/pages/control/KillSwitchDegradation.jsx` | Manual status change and demo simulations | LIVE_AND_WIRED for lifecycle; demo for simulations |
| Audit Logs | `Frontend/src/pages/control/AuditLogs.jsx` | Reads events/decisions/guardrails/kill/degradation | LIVE_AND_WIRED |
| Observability | `Frontend/src/pages/control/Observability.jsx` | Reads runs, events, hooks, usage, LangSmith status | LIVE_AND_WIRED with optional LangSmith |
| Usage Cost | `Frontend/src/pages/control/UsageCost.jsx` | Reads `/usage/summary`, `/usage/events` | LIVE_AND_WIRED, estimate caveat |
| Agentic Primitives | `Frontend/src/pages/control/AgenticPrimitives.jsx` | Reads skills/tools/tool-auth/memory/hooks/prompts/evaluators/validation | PARTIAL because many are registry-only |
| RAG Quality | `Frontend/src/pages/control/RagQuality.jsx` | Reads `/evaluations` and quality gates | LIVE_AND_WIRED for policy/loan RAG |
| Run Console | `Frontend/src/pages/control/Runconsole.jsx` | Has control calls but no route in `main.jsx` | IMPLEMENTED_NOT_WIRED |
| Legacy Dashboard | `Frontend/src/pages/DashboardPage.jsx` | Calls `/api/v1/harness/*`, but `/dashboard` redirects to Control Tower | IMPLEMENTED_NOT_WIRED |

## PowerPoint Accuracy Summary

Accurate claims:

- Policy Assistant, Loan Assessment, Collections workflow, and Control Plane dashboard exist.
- YAML contracts load into registry and persist to SQLite.
- Python-function and REST adapters are live.
- RAG evaluation runs for policy/loan control-plane invocations and persists.
- Kill switch lifecycle is persisted in the manifest control-plane path.
- LangSmith is optional.
- Collections data and transcripts are seeded/demo-labeled.
- Voice pipeline caveat is present in the deck.
- RBAC is correctly listed as roadmap/future.

Overstated or incomplete claims:

- "All calls go through typed Adapter Boundary" is true for `/api/v1/control/*` agent invocations, not for legacy `/api/v1/chat` and `/api/v1/loan/assess`.
- Parent LangGraph is live for legacy routes, not for the main `/api/v1/control/*` runtime used by current frontend.
- Tool authorization is an API/service and demo path, not automatic interception of every domain tool call.
- Policy engine is not broadly YAML-driven; core checks are deterministic code plus manifest permissions.
- LangGraph adapter and external-webhook adapter are implemented but not wired to registered agents.
- Memory contract, hook, evaluator, and model gateway catalogs are not full enforcement layers.
- Usage/cost metering is provider-reported for Groq RAG where available, but collections/external fallback records are often `unknown` without token counts.

