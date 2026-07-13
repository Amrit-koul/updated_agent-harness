import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../../components/control/PageHeader';
import { JsonBlock, LoadingState, SectionCard } from '../../components/control/Common';
import { controlPlaneApi } from '../../services/controlPlaneApi';
import { useControlData } from '../../hooks/useControlData';

// ─── Integration steps — manifest → control plane ────────────────────────────

const INTEGRATION_STEPS = [
  ['1', 'Define manifest', 'Author a YAML file declaring agent identity, adapter type, input/output schemas, permissions, guardrails, and observability hooks.'],
  ['2', 'Add adapter', 'Select an adapter boundary: python_function, langgraph, rest_api, or external_webhook. The harness normalises all invocations through the same runtime.'],
  ['3', 'Normalise input', 'The adapter validates the inbound payload against the contract\'s input_schema before passing it to the agent implementation.'],
  ['4', 'Execute through control plane', 'The harness runs: lifecycle status check → policy check → guardrail check → adapter invoke → output capture.'],
  ['5', 'Apply policy and guardrails', 'Policy decisions and guardrail events are evaluated per the contract\'s policy_permissions and guardrails list before any output is returned.'],
  ['6', 'Persist trace and audit evidence', 'Every invocation writes an execution trace, usage/cost event, and audit record keyed to the agent_id declared in the contract.'],
];

// ─── Integration patterns table ──────────────────────────────────────────────

const PATTERNS = [
  {
    name: 'Internal python_function',
    adapter: 'python_function',
    entrypoint: 'package.module.function',
    governance: 'Full lifecycle, policy, guardrails, trace, audit, usage.',
    caveat: 'Entrypoint must be importable from the application Python path.',
  },
  {
    name: 'LangGraph workflow',
    adapter: 'langgraph',
    entrypoint: 'package.module.graph_or_callable',
    governance: 'Same control path; graph invoke() or ainvoke() is called.',
    caveat: 'Tool permissions must be declared explicitly in the manifest.',
  },
  {
    name: 'REST vendor agent',
    adapter: 'rest_api',
    entrypoint: 'https://vendor-host/invoke  (endpoint field)',
    governance: 'Policy + guardrail run before the HTTP call; result is audited.',
    caveat: 'The local endpoint is unauthenticated. Production requires auth_env_var.',
  },
  {
    name: 'External webhook agent',
    adapter: 'external_webhook',
    entrypoint: 'https://external-host/hook  (endpoint field)',
    governance: 'Heartbeats and status visible to the control plane.',
    caveat: 'The control plane cannot physically stop an external process that ignores it.',
  },
];

// ─── Small presentational helpers ────────────────────────────────────────────

function Pill({ value, variant = 'default' }) {
  const colours = { active: 'cc-badge-green', review: 'cc-badge-yellow', disabled: 'cc-badge-red', quarantined: 'cc-badge-red', default: 'cc-badge' };
  return <span className={colours[value] || colours.default}>{value}</span>;
}

function FieldRow({ label, value, mono = false }) {
  if (value == null || value === '') return null;
  return (
    <div className="cc-kv-row">
      <span className="cc-kv-label">{label}</span>
      <span className={mono ? 'mono' : undefined}>{String(value)}</span>
    </div>
  );
}

function TagList({ items, empty = 'None declared' }) {
  if (!items || items.length === 0) return <span className="cc-muted">{empty}</span>;
  return (
    <div className="cc-tag-list">
      {items.map((item) => <span key={item} className="cc-badge">{item}</span>)}
    </div>
  );
}

function SchemaBlock({ schema }) {
  if (!schema || Object.keys(schema).length === 0) return <span className="cc-muted">Not declared</span>;
  return <JsonBlock value={schema} />;
}

// ─── Runtime boundary diagram (text) ─────────────────────────────────────────

function RuntimeBoundary() {
  const steps = [
    ['Request', 'Inbound payload arrives at the control plane invoke endpoint.'],
    ['Policy check', 'policy_permissions from the contract are evaluated. Blocked requests are recorded and rejected.'],
    ['Guardrail check', 'guardrails from the contract run input validation. PII, injection, and scope violations are caught here.'],
    ['Adapter invoke', 'The adapter boundary normalises the payload and calls the implementation (function / graph / HTTP / webhook).'],
    ['Output validation', 'The adapter returns a normalised dict. Output guardrails may apply depending on configuration.'],
    ['Usage telemetry', 'Token usage and latency are recorded to the usage_events table.'],
    ['Audit evidence', 'A trace record and audit event are persisted with agent_id, trace_id, and outcome.'],
    ['Lifecycle update', 'Failure rates feed the degradation monitor. The kill switch can transition status based on rules.'],
  ];
  return (
    <ol className="cc-step-list">
      {steps.map(([title, desc]) => (
        <li key={title}>
          <span>→</span>
          <div><strong>{title}</strong><p>{desc}</p></div>
        </li>
      ))}
    </ol>
  );
}

// ─── Contract viewer ────────────────────────

function ContractViewer({ agentId }) {
  const fetcher = useCallback(() => controlPlaneApi.getContract(agentId), [agentId]);
  const { data, loading, error } = useControlData(fetcher, [agentId]);

  if (loading || error || !data) {
    return <LoadingState loading={loading} error={error} empty={!data}>No contract data returned.</LoadingState>;
  }

  const contract = data.effective_resolved_contract || data.contract;
  const { source_file, _demo, original_contract_version, validation_result, unresolved_references, active_runtime, model_deployment, latest_evidence } = data;
  const { identity, runtime, schemas, capabilities, model_policy, permissions, budget_policy, observability, lifecycle, metadata } = contract;
  const guardrails = contract.guardrails || metadata?.guardrails || [];

  return (
    <div className="cc-contract-viewer">

      {/* Truth notice */}
      {_demo && (
        <div className="cc-notice info" style={{ marginBottom: '1rem' }}>
          <strong>Adapter contract.</strong> This agent exists to illustrate the REST adapter boundary.
          The vendor endpoint is a local mock service — not a production integration.
        </div>
      )}

      {/* A. Identity */}
      <SectionCard title="A · Identity">
        <div className="cc-kv-grid">
          <FieldRow label="Agent ID"          value={identity.agent_id} mono />
          <FieldRow label="Name"              value={identity.display_name || identity.name} />
          <FieldRow label="Contract version"  value={identity.contract_version} />
          <FieldRow label="Original version"  value={original_contract_version} />
          <FieldRow label="Owner"             value={identity.owner} />
          <FieldRow label="Business function" value={identity.business_function} />
          <FieldRow label="Risk tier"         value={identity.risk_tier} />
          <FieldRow label="Agent type"        value={identity.agent_type} />
        </div>
        {identity.description && (
          <p className="cc-muted" style={{ marginTop: '0.75rem' }}>{identity.description}</p>
        )}
      </SectionCard>

      {/* B. Adapter boundary */}
      <SectionCard title="B · Adapter Boundary">
        <div className="cc-kv-grid">
          <FieldRow label="Runtime type" value={runtime.runtime_type} mono />
          <FieldRow label="Execution mode" value={runtime.execution_mode} mono />
          <FieldRow label="Adapter type" value={runtime.adapter_type} mono />
          <FieldRow label="Timeout seconds" value={runtime.timeout_seconds} />
          {runtime.entrypoint && <FieldRow label="Entrypoint" value={runtime.entrypoint} mono />}
          {runtime.endpoint   && <FieldRow label="Endpoint"   value={runtime.endpoint}   mono />}
        </div>
        <p className="cc-muted" style={{ marginTop: '0.75rem' }}>
          The adapter is the only boundary through which the implementation is invoked.
          The control plane never calls the implementation directly.
        </p>
      </SectionCard>

      {/* C. Input / output schema */}
      <SectionCard title="C · Input / Output Schema">
        <p className="cc-section-label" style={{ marginBottom: '0.5rem' }}>Input schema</p>
        <SchemaBlock schema={schemas.input_schema} />
        <p className="cc-section-label" style={{ margin: '1rem 0 0.5rem' }}>Output schema</p>
        <SchemaBlock schema={schemas.output_schema} />
        <p className="cc-section-label" style={{ margin: '1rem 0 0.5rem' }}>State schema</p>
        <SchemaBlock schema={schemas.state_schema} />
        <p className="cc-section-label" style={{ margin: '1rem 0 0.5rem' }}>Memory schema</p>
        <SchemaBlock schema={schemas.memory_schema} />
      </SectionCard>

      {/* D. Capabilities */}
      <SectionCard title="D · Capabilities">
        <div className="cc-kv-grid">
          <div className="cc-kv-row"><span className="cc-kv-label">Skills</span><TagList items={capabilities.skills} /></div>
          <div className="cc-kv-row"><span className="cc-kv-label">Tools</span><TagList items={capabilities.tools} /></div>
          <div className="cc-kv-row"><span className="cc-kv-label">Memory contracts</span><TagList items={capabilities.memory_contracts} /></div>
          <div className="cc-kv-row"><span className="cc-kv-label">Prompts</span><TagList items={capabilities.prompts} /></div>
          <div className="cc-kv-row"><span className="cc-kv-label">Evaluators</span><TagList items={capabilities.evaluators} /></div>
          <div className="cc-kv-row"><span className="cc-kv-label">Hooks</span><TagList items={capabilities.hooks} /></div>
        </div>
      </SectionCard>

      <SectionCard title="E · Model Policy">
        <div className="cc-kv-grid">
          <FieldRow label="Provider" value={model_policy.provider} mono />
          <FieldRow label="Deployment" value={model_deployment || model_policy.deployment} mono />
          <FieldRow label="Temperature" value={model_policy.temperature} />
          <FieldRow label="Max output tokens" value={model_policy.max_output_tokens} />
          <FieldRow label="Supports tools" value={model_policy.supports_tools ? 'yes' : 'no'} />
          <FieldRow label="Structured output" value={model_policy.supports_structured_output ? 'yes' : 'no'} />
        </div>
      </SectionCard>

      {/* E. Runtime permissions */}
      <SectionCard title="F · Runtime Permissions">
        <div className="cc-kv-grid">
          <div className="cc-kv-row">
            <span className="cc-kv-label">Allowed tools</span>
            <TagList items={permissions.allowed_tools} />
          </div>
          <div className="cc-kv-row">
            <span className="cc-kv-label">Allowed actions</span>
            <TagList items={permissions.allowed_actions} />
          </div>
          <div className="cc-kv-row">
            <span className="cc-kv-label">Data scopes</span>
            <TagList items={permissions.allowed_data_scopes} />
          </div>
          <div className="cc-kv-row">
            <span className="cc-kv-label">Requires human approval for</span>
            <TagList items={permissions.human_approval_required_for} empty="None" />
          </div>
          <div className="cc-kv-row">
            <span className="cc-kv-label">Denied actions</span>
            <TagList items={permissions.denied_actions} empty="None" />
          </div>
        </div>
      </SectionCard>

      {/* F. Guardrail policy */}
      <SectionCard title="G · Budget Policy">
        <JsonBlock value={budget_policy || {}} />
      </SectionCard>

      <SectionCard title="H · Guardrail Policy">
        <TagList items={guardrails} empty="No guardrails declared" />
        <p className="cc-muted" style={{ marginTop: '0.75rem' }}>
          Guardrails are evaluated by the harness before and after invocation.
          A failed guardrail blocks the response and writes a guardrail_event record.
        </p>
      </SectionCard>

      {/* G. Observability hooks */}
      <SectionCard title="I · Observability Requirements">
        {observability.hooks && Object.keys(observability.hooks).length > 0 ? (
          <div className="cc-tag-list">
            {Object.entries(observability.hooks).map(([hook, enabled]) => (
              <span key={hook} className={enabled ? 'cc-badge-green' : 'cc-badge'}>
                {hook}: {enabled ? 'on' : 'off'}
              </span>
            ))}
          </div>
        ) : (
          <span className="cc-muted">No observability hooks declared</span>
        )}
      </SectionCard>

      {/* H. Lifecycle controls */}
      <SectionCard title="J · Lifecycle Controls">
        <div className="cc-kv-grid">
          <div className="cc-kv-row">
            <span className="cc-kv-label">Current status</span>
            <Pill value={active_runtime?.status || lifecycle.initial_status} variant={active_runtime?.status || lifecycle.initial_status} />
          </div>
          <FieldRow label="Manifest default" value={lifecycle.initial_status} />
        </div>
        <p className="cc-muted" style={{ marginTop: '0.75rem' }}>
          Status transitions (active → review → quarantined → disabled) are controlled by the Kill Switch page.
          The contract declares the manifest default; runtime status is persisted separately in the store.
        </p>
      </SectionCard>

      <SectionCard title="K · Validation And Evidence">
        <div className="cc-kv-grid">
          <FieldRow label="Validation" value={validation_result?.valid ? 'valid' : 'invalid'} />
          <FieldRow label="Active runtime" value={`${active_runtime?.runtime_type || runtime.runtime_type} / ${active_runtime?.adapter_type || runtime.adapter_type}`} />
        </div>
        <p className="cc-section-label" style={{ margin: '1rem 0 0.5rem' }}>Unresolved references</p>
        <JsonBlock value={unresolved_references || {}} />
        <p className="cc-section-label" style={{ margin: '1rem 0 0.5rem' }}>Latest evidence</p>
        <JsonBlock value={latest_evidence || {}} />
      </SectionCard>

      {/* I. Raw manifest (source file) */}
      <SectionCard
        title="L · Raw Contract (Manifest Preview)"
        subtitle={source_file ? `Source: ${source_file}` : 'Source file not recorded'}
      >
        <div className="cc-notice info" style={{ marginBottom: '0.75rem' }}>
          <strong>Read-only preview.</strong> This is the parsed manifest as loaded by the registry at startup.
          To update a contract, edit the YAML file and restart the service.
        </div>
        <JsonBlock value={contract} />
      </SectionCard>

    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AgentContract() {
  const [selectedId, setSelectedId] = useState('');
  const [viewingId, setViewingId]   = useState(null);

  const listFetcher = useCallback(() => controlPlaneApi.listAgents(), []);
  const { data: agentsData, loading: agentsLoading, error: agentsError } = useControlData(listFetcher, []);
  const agents = agentsData?.agents || [];

  return (
    <>
      <PageHeader
        title="Agent Contract"
        subtitle="Manifest and adapter contract used by the harness to govern agent execution."
      />

      {/* Truth statement */}
      <div className="cc-notice info" style={{ marginBottom: '1.5rem' }}>
        <strong>How this works.</strong> Agents are loaded from YAML manifests at startup.
        The harness uses the contract to enforce adapter boundary, runtime permissions, guardrail policy,
        lifecycle controls, and observability hooks. This page documents and previews those contracts —
        it does not mutate the registry at runtime.
      </div>

      {/* ── Section A: Contract Overview ── */}
      <SectionCard
        title="Contract Overview"
        subtitle="Fields that every registered agent must declare in its manifest."
      >
        <div className="cc-table-scroll">
          <table className="cc-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Section</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['agent_id, name, owner, business_function', 'Identity', 'Unique identifier, display name, owning team, and business domain.'],
                ['agent_type, execution_mode', 'Identity', 'internal/external and workflow/rag/synchronous/decoupled.'],
                ['adapter_type, entrypoint / endpoint', 'Adapter boundary', 'Which adapter class handles invocation and where the implementation lives.'],
                ['input_schema, output_schema', 'Schemas', 'JSON Schema objects the adapter validates before and after invocation.'],
                ['state_schema, memory_schema', 'Schemas', 'Shape of per-session state and long-term memory the agent may use.'],
                ['skills, tools, prompts', 'Capabilities', 'Declared capabilities — tools listed here are the only ones policy will permit.'],
                ['policy_permissions', 'Runtime permissions', 'Allowed tools, actions, data scopes, and human-approval triggers.'],
                ['guardrails', 'Guardrail policy', 'Named guardrail checks that run on every invocation.'],
                ['observability_hooks', 'Observability', 'Which tracing and audit events are emitted.'],
                ['status', 'Lifecycle', 'Manifest default lifecycle state (active / review / disabled).'],
              ].map(([field, section, purpose]) => (
                <tr key={field}>
                  <td className="mono" style={{ whiteSpace: 'nowrap' }}>{field}</td>
                  <td>{section}</td>
                  <td>{purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* ── Section B: How a Third-Party Agent Plugs In ── */}
      <SectionCard
        title="How a Third-Party Agent Plugs In"
        subtitle="Manifest-driven integration — six steps from YAML to governed invocation."
      >
        <ol className="cc-step-list">
          {INTEGRATION_STEPS.map(([n, title, desc]) => (
            <li key={n}>
              <span>{n}</span>
              <div><strong>{title}</strong><p>{desc}</p></div>
            </li>
          ))}
        </ol>
      </SectionCard>

      {/* ── Section B2: Supported adapter patterns ── */}
      <SectionCard
        title="Supported Integration Patterns"
        subtitle="Example contracts for implementation patterns and governance boundaries."
      >
        <div className="cc-table-scroll">
          <table className="cc-table">
            <thead>
              <tr>
                <th>Pattern</th>
                <th>adapter_type</th>
                <th>Entrypoint / Endpoint</th>
                <th>Automatic governance</th>
                <th>Caveat</th>
              </tr>
            </thead>
            <tbody>
              {PATTERNS.map((p) => (
                <tr key={p.name}>
                  <td><strong>{p.name}</strong></td>
                  <td className="mono">{p.adapter}</td>
                  <td className="mono" style={{ fontSize: '0.8em' }}>{p.entrypoint}</td>
                  <td>{p.governance}</td>
                  <td className="cc-muted">{p.caveat}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* ── Section C: Contract Preview ── */}
      <SectionCard
        title="Contract Preview"
        subtitle="Select a registered agent to view its manifest contract."
        right={
          agents.length > 0 && (
            <Link className="cc-link-button" to="/control/agents">
              Agent Registry ↗
            </Link>
          )
        }
      >
        <div className="cc-notice info" style={{ marginBottom: '1rem' }}>
          <strong>Registry data.</strong> Contracts are loaded from{' '}
          <span className="mono">banking_agents/config/agents/*.yaml</span> at service startup
          and stored in the <span className="mono">agent_contracts</span> table.
          Selecting an agent below calls{' '}
          <span className="mono">GET /api/v1/control/agents/&#123;id&#125;/contract</span>.
        </div>

        {agentsLoading && <div className="cc-empty">Loading registered agents…</div>}
        {agentsError  && <div className="cc-empty cc-error">Cannot load agents: {agentsError.message}</div>}

        {!agentsLoading && !agentsError && (
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <label style={{ flex: '1', minWidth: '220px' }}>
              <span style={{ display: 'block', marginBottom: '0.35rem', fontSize: '0.8rem', opacity: 0.7 }}>
                Registered agent ({agents.length} loaded)
              </span>
              <select
                className="cc-input"
                value={selectedId}
                onChange={(e) => { setSelectedId(e.target.value); setViewingId(null); }}
              >
                <option value="">— select agent —</option>
                {agents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.name || a.agent_id}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="cc-button"
              disabled={!selectedId}
              onClick={() => setViewingId(selectedId)}
            >
              View Contract
            </button>
          </div>
        )}

        {viewingId && <ContractViewer agentId={viewingId} />}
      </SectionCard>

      {/* ── Section D: Runtime Boundary ── */}
      <SectionCard
        title="Runtime Boundary"
        subtitle="Request flow through the control plane — every step is contract-driven."
      >
        <RuntimeBoundary />
      </SectionCard>

      {/* ── Section E: Adapter Test ── */}
      <SectionCard
        title="Adapter Test"
        subtitle="Run the sample REST adapter through the harness to observe the full adapter boundary. The local mock vendor service must be running on port 9001."
      >
        <div className="cc-notice warning" style={{ marginBottom: '1rem' }}>
          <strong>Sample adapter.</strong> This invokes the REST adapter test contract, not a real vendor.
          Start the mock service (<span className="mono">banking_agents/external_plugins/mock_vendor_rest_agent/app.py</span>) before running.
        </div>
        <DemoAdapterTest />
        <div style={{ marginTop: '1rem' }}>
          <Link className="cc-link-button" to="/control/agents">View full Agent Registry</Link>
        </div>
      </SectionCard>
    </>
  );
}

// ─── Adapter test (extracted so it has its own state) ────────────────────

function DemoAdapterTest() {
  const [run, setRun] = useState({ loading: false, result: null, error: null });

  const execute = async () => {
    setRun({ loading: true, result: null, error: null });
    try {
      const result = await controlPlaneApi.invokeAgent('demo_vendor_rest_agent', {
        query: 'Summarise this customer collections request',
      });
      setRun({ loading: false, result, error: null });
    } catch (err) {
      setRun({ loading: false, result: null, error: err.message || 'Invocation failed.' });
    }
  };

  return (
    <>
      <button className="cc-button" onClick={execute} disabled={run.loading}>
        {run.loading ? 'Running adapter test…' : 'Run Adapter Test'}
      </button>
      {run.error && (
        <div className="cc-notice warning cc-top-gap">
          <strong>Invocation failed:</strong> {run.error}
          <p className="cc-muted" style={{ marginTop: '0.4rem' }}>
            This is expected if the mock vendor service is not running on port 9001.
            The harness attempted the full policy → guardrail → adapter path regardless.
          </p>
        </div>
      )}
      {run.result && (
        <div className="cc-top-gap">
          <p className="cc-muted" style={{ marginBottom: '0.5rem' }}>
            Response routed through harness control plane (policy check → guardrail → adapter invoke → audit):
          </p>
          <JsonBlock value={run.result} />
        </div>
      )}
    </>
  );
}
