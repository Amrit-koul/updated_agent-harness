# Canonical Control-Plane Runtime

The governed runtime is `ControlPlaneRuntime` in `Backend/banking_agents/harness/runtime.py`. It is the single runtime singleton for governed agent invocation and extends the existing implementation; no second runtime was added.

## Typed Runtime Models

Defined in `Backend/agent_harness/invocation.py`:

- `InvocationRequest`
- `InvocationContext`
- `InvocationResult`
- `RuntimeErrorCode`

Typed failure categories:

- `AGENT_NOT_FOUND`
- `CONTRACT_INVALID`
- `INPUT_SCHEMA_INVALID`
- `AGENT_NOT_ACTIVE`
- `PERMISSION_DENIED`
- `GUARDRAIL_BLOCKED`
- `BUDGET_EXCEEDED`
- `ADAPTER_FAILURE`
- `AGENT_TIMEOUT`
- `OUTPUT_INVALID`
- `INTERNAL_RUNTIME_ERROR`

## Runtime Call Chain

```text
Public route
  -> InvocationRequest
  -> ControlPlaneRuntime.invoke_result()
      -> accept_invocation_request
      -> resolve_agent_contract
      -> validate_contract
      -> resolve_runtime_and_adapter
      -> validate_input_schema
      -> verify_lifecycle_status
      -> resolve_security_context
      -> evaluate_action_permissions
      -> run_input_guardrails
      -> create_trace_and_audit_context
      -> enforce_model_token_policy
      -> invoke_adapter
      -> run_output_guardrails
      -> run_relevant_evaluators
      -> record_usage
      -> persist_observability_events
      -> persist_audit_evidence
      -> InvocationResult
```

Every phase writes a `runtime_phase_events` row and a corresponding `observability_events` row named `RUNTIME_PHASE_<PHASE>`.

## Persistence

`Backend/agent_harness/store.py` adds idempotent SQLite migrations for:

- `agent_invocations`
- `runtime_phase_events`

The explicit SQL migration is `Backend/agent_harness/migrations/001_control_plane_invocations.sql`.
The store also applies the same schema with `CREATE TABLE IF NOT EXISTS` when it opens a database.

`agent_invocations` includes:

- `invocation_id`
- `trace_id`
- `agent_id`
- `principal_id`
- `action`
- `lifecycle_status`
- `decision`
- `started_at`
- `completed_at`
- `duration_ms`
- `error_code`

Existing tables are preserved and demo data is not deleted.

## Public Invocation Routes

The main control-plane invocation route now uses `invoke_result()`:

- `POST /api/v1/control/agents/{agent_id}/invoke`

Demo routes continue to call the same helper and preserve the legacy `result` alias:

- `POST /api/v1/control/demo/run-policy-agent`
- `POST /api/v1/control/demo/run-loan-assessment`
- `POST /api/v1/control/demo/run-collections`
- `POST /api/v1/control/collections/{account_id}/post-call`
- `POST /api/v1/control/collections/voice/greet`
- `POST /api/v1/control/collections/voice/finalize`

Backward-compatible legacy routes now enter the canonical runtime before invoking business agents:

- `POST /api/v1/chat`
- `POST /api/v1/loan/assess`

## Old Bypass Paths Removed Or Routed

- Direct control route adapter invocation is replaced by `ControlPlaneRuntime.invoke_result()`.
- Legacy `/api/v1/chat` no longer calls the legacy parent graph directly for business execution; it routes to `policy_assistant_agent` through `ControlPlaneRuntime`.
- Legacy `/api/v1/loan/assess` enters `loan_assessment_agent` through `ControlPlaneRuntime` before returning the old response shape.
- `POST /api/v1/control/collections/voice/turn` no longer calls the voice pipeline directly from the route; it invokes `collections_workflow_agent` with `mode=voice_turn` through `ControlPlaneRuntime`.

Known remaining non-invocation endpoints:

- Heartbeat and external event ingestion persist events only; they do not invoke agents.
- Control-plane read routes remain read-only.

## Compatibility Evidence

The compatibility wrapper `ControlPlaneRuntime.invoke()` still returns the existing shape:

```json
{ "trace_id": "...", "agent_id": "...", "result": { } }
```

`_invoke_control_plane()` also includes typed `InvocationResult` fields plus the legacy `result` alias so current React code can continue to read `run.result`.

Focused tests in `Backend/tests/test_control_plane_runtime.py` cover:

- canonical phase emission
- active agent allowed
- review handling
- quarantined blocked
- disabled blocked
- invalid payload blocked
- adapter timeout
- guardrail block
- successful internal agent
- successful REST agent
- audit and trace rows written exactly once
