import React, { useCallback, useMemo, useState } from 'react';
import PageHeader from '../../components/control/PageHeader';
import Drawer from '../../components/control/Drawer';
import { ExecModeChip, HealthChip, StatusChip, DecisionChip } from '../../components/control/Chips';
import { JsonBlock, LoadingState, SectionCard, asArray, display, fmtTime } from '../../components/control/Common';
import { useControlData } from '../../hooks/useControlData';
import { controlPlaneApi } from '../../services/controlPlaneApi';
import { renderMissingField, EnforcementBadge, LLMJudgeBadge } from '../../utils/evidenceLabels';

function ContractDrawer({ agentId, onClose }) {
  const fetchDetails = useCallback(async () => {
    let contract;
    try {
      contract = await controlPlaneApi.getContract(agentId);
    } catch {
      contract = await controlPlaneApi.getAgent(agentId);
    }
    const [health, toolAuth, policy, guardrails] = await Promise.all([
      controlPlaneApi.getHealth(agentId).catch(() => null),
      controlPlaneApi.listToolAuthorizationEvents().catch(() => ({ events: [] })),
      controlPlaneApi.listPolicyDecisions().catch(() => ({ decisions: [] })),
      controlPlaneApi.listGuardrailEvents().catch(() => ({ events: [] })),
    ]);
    const security = await controlPlaneApi.listPrincipals()
      .then(async (payload) => {
        const principal = asArray(payload, 'principals').find((item) => item.agent_id === agentId);
        if (!principal) return { principal: null, effective: null, decisions: [] };
        const [effective, decisions] = await Promise.all([
          controlPlaneApi.getEffectivePermissions(principal.principal_id).catch(() => null),
          controlPlaneApi.listAuthorizationDecisions().catch(() => ({ decisions: [] })),
        ]);
        return {
          principal,
          effective,
          decisions: asArray(decisions, 'decisions').filter((item) => item.principal_id === principal.principal_id).slice(0, 10),
        };
      })
      .catch((error) => ({ unavailable: true, message: error.message }));
    return { 
      contract, 
      health, 
      toolAuth: asArray(toolAuth, 'events').filter(e => e.agent_id === agentId),
      policy: asArray(policy, 'decisions').filter(e => e.agent_id === agentId),
      guardrails: asArray(guardrails, 'events').filter(e => e.agent_id === agentId),
      security,
    };
  }, [agentId]);
  
  const state = useControlData(fetchDetails, [agentId]);
  const contract = normalizeContract(state.data?.contract);
  const toolAuth = state.data?.toolAuth || [];
  const policy = state.data?.policy || [];
  const guardrails = state.data?.guardrails || [];
  const primitives = contract?.primitives || {};
  const security = state.data?.security || {};
  
  const latestAuth = toolAuth[0];
  const latestPolicy = policy[0];
  const latestGuardrail = guardrails[0];

  const getRuntimeStatusText = (status) => {
    if (status === 'config_only') return 'Declared in manifest; runtime interception is not yet wired for this flow.';
    if (status === 'available_not_wired') return 'Authorization boundary exists, but this flow has not been routed through it yet.';
    if (status === 'runtime_enforced') return 'Authorization enforced by control plane.';
    return 'Not returned.';
  };

  const arraySections = ['skills', 'tools', 'prompts', 'guardrails'];
  const objectSections = ['input_schema', 'output_schema', 'state_schema', 'memory_schema', 'model_preferences', 'observability_hooks', 'metrics'];
  
  return (
    <Drawer title={contract?.name || agentId} subtitle="Agent Contract" onClose={onClose}>
      <LoadingState loading={state.loading} error={state.error} />
      {contract && <>
        <dl className="cc-detail-grid">
          {['agent_id', 'owner', 'business_function', 'agent_type', 'execution_mode', 'adapter_type', 'entrypoint', 'endpoint', 'version'].filter((key) => contract[key] != null && contract[key] !== '').map((key) => <React.Fragment key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{display(contract[key])}</dd></React.Fragment>)}
          <dt>Status</dt><dd><StatusChip status={contract.status} /></dd>
          <dt>Health</dt><dd><HealthChip health={state.data?.health?.status} /></dd>
          {contract.latest_kill_switch_event && <><dt>Latest lifecycle reason</dt><dd>{display(contract.latest_kill_switch_event.reason)} ({display(contract.latest_kill_switch_event.trigger)})</dd><dt>Lifecycle timestamp</dt><dd>{display(contract.latest_kill_switch_event.timestamp)}</dd></>}
        </dl>

        <div className="cc-drawer-section"><h3>Capabilities & Security</h3>
          <dl className="cc-detail-grid">
            <dt>Declared Tools</dt>
            <dd>{contract.tools?.length ? contract.tools.join(', ') : <span className="cc-muted">None declared</span>}</dd>
            
            <dt>Allowed Actions</dt>
            <dd>{contract.policy_permissions?.allowed_actions?.length ? contract.policy_permissions.allowed_actions.join(', ') : renderMissingField()}</dd>
            
            <dt>Allowed Data Scopes</dt>
            <dd>{contract.policy_permissions?.allowed_data_scopes?.length ? contract.policy_permissions.allowed_data_scopes.join(', ') : renderMissingField()}</dd>
            
            <dt>Human Approval Reqs</dt>
            <dd>{contract.policy_permissions?.requires_human_approval_for?.length ? contract.policy_permissions.requires_human_approval_for.join(', ') : 'Not required'}</dd>
            
            <dt>Runtime Auth Status</dt>
            <dd>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <EnforcementBadge status={contract.enforcement_status || (latestAuth ? 'runtime_enforced' : 'config_only')} />
                <span className="cc-muted cc-small">{getRuntimeStatusText(contract.enforcement_status || (latestAuth ? 'runtime_enforced' : 'config_only'))}</span>
              </div>
            </dd>

            <dt>LLM Judge Usage</dt>
            <dd>
              {contract.llm_judge ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <LLMJudgeBadge status={contract.llm_judge.status} />
                  {contract.llm_judge.score && <span className="cc-small">Score: {contract.llm_judge.score}</span>}
                </div>
              ) : renderMissingField()}
            </dd>
          </dl>
        </div>

        <div className="cc-drawer-section"><h3>Latest Execution Evidence</h3>
          <dl className="cc-detail-grid">
            <dt>Latest Tool Auth</dt>
            <dd>{latestAuth ? <><DecisionChip decision={latestAuth.decision} /> <span className="cc-muted cc-small">({fmtTime(latestAuth.timestamp)})</span></> : <span className="cc-muted">No evidence</span>}</dd>
            
            <dt>Latest Policy Decision</dt>
            <dd>{latestPolicy ? <><DecisionChip decision={latestPolicy.decision} /> <span className="cc-muted cc-small">({fmtTime(latestPolicy.timestamp)})</span></> : <span className="cc-muted">No evidence</span>}</dd>
            
            <dt>Latest Guardrail Event</dt>
            <dd>{latestGuardrail ? <><DecisionChip decision={latestGuardrail.decision} /> <span className="cc-muted cc-small">({fmtTime(latestGuardrail.timestamp)})</span></> : <span className="cc-muted">No evidence</span>}</dd>
          </dl>
        </div>

        <div className="cc-drawer-section"><h3>Security Principal</h3>
          {security.unavailable ? (
            <p className="cc-muted cc-small">{security.message}</p>
          ) : security.principal ? (
            <>
              <dl className="cc-detail-grid">
                <dt>Principal ID</dt><dd className="mono">{security.principal.principal_id}</dd>
                <dt>Principal Type</dt><dd>{display(security.principal.principal_type)}</dd>
                <dt>Status</dt><dd><StatusChip status={security.principal.status} /></dd>
                <dt>Credential Reference</dt><dd>{display(security.principal.credential_reference) || 'Not configured'}</dd>
              </dl>
              <div className="cc-primitive-detail">
                <strong>Assigned Roles</strong>
                {security.effective?.roles?.length ? (
                  <div className="cc-token-list">{security.effective.roles.map((role) => <span key={`${role.role_id}-${role.scope_type}-${role.scope_value}`}>{role.role_name} · {role.scope_type}:{role.scope_value}</span>)}</div>
                ) : <p className="cc-muted cc-small">No valid roles returned.</p>}
              </div>
              <div className="cc-primitive-detail">
                <strong>Effective Permissions</strong>
                {security.effective?.permissions?.length ? (
                  <div className="cc-token-list">{security.effective.permissions.map((permission) => <span key={`${permission.permission_id}-${permission.role_id}-${permission.scope_type}-${permission.scope_value}`}>{permission.permission_id}</span>)}</div>
                ) : <p className="cc-muted cc-small">No effective permissions returned.</p>}
              </div>
              <div className="cc-primitive-detail">
                <strong>Recent Authorization Decisions</strong>
                {security.decisions?.length ? (
                  <div className="cc-table-scroll"><table className="cc-table"><thead><tr><th>Decision</th><th>Resource</th><th>Action</th><th>Reason</th></tr></thead><tbody>{security.decisions.map((item) => <tr key={item.decision_id}><td><DecisionChip decision={item.decision} /></td><td className="mono">{item.resource_type}:{item.resource_id}</td><td>{item.requested_action}</td><td>{item.reason_code}</td></tr>)}</tbody></table></div>
                ) : <p className="cc-muted cc-small">No authorization decisions returned.</p>}
              </div>
            </>
          ) : <p className="cc-muted cc-small">No principal returned for this agent.</p>}
        </div>

        {arraySections.map((key) => contract[key]?.length ? <div className="cc-drawer-section" key={key}><h3>{key.replaceAll('_', ' ')}</h3><div className="cc-token-list">{contract[key].map((item) => <span key={String(item)}>{String(item)}</span>)}</div></div> : null)}
        {objectSections.map((key) => contract[key] != null ? <div className="cc-drawer-section" key={key}><h3>{key.replaceAll('_', ' ')}</h3><JsonBlock value={contract[key]} /></div> : null)}
        
        <div className="cc-drawer-section"><h3>Agentic Primitives</h3>
          {['skills', 'memory_contracts', 'hooks', 'evaluators'].map((key) => primitives[key]?.length ? <div className="cc-primitive-detail" key={key}><strong>{key.replaceAll('_', ' ')}</strong><div className="cc-token-list">{primitives[key].map((item, index) => <span key={item.skill_id || item.tool_id || item.memory_scope || item.hook_id || item.prompt_id || item.evaluator_id || index}>{item.name || item.skill_id || item.tool_id || item.memory_scope || item.hook_id || item.prompt_id || item.evaluator_id}</span>)}</div></div> : null)}
          {primitives.validation_warnings?.length ? <div className="cc-primitive-detail"><strong>Validation Warnings</strong><div className="cc-token-list">{primitives.validation_warnings.map((item, index) => <span key={index}>{item.code}: {item.reference}</span>)}</div></div> : <p className="cc-muted cc-small">No primitive validation warnings returned.</p>}
        </div>
      </>}
    </Drawer>
  );
}

function normalizeContract(payload) {
  if (!payload) return null;
  const c = payload.contract || payload;
  if (!c.identity && !c.adapter && !c.schemas && !c.capabilities && !c.permissions) {
    return c;
  }

  const identity = c.identity || {};
  const runtime = c.runtime || c.adapter || {};
  const schemas = c.schemas || {};
  const capabilities = c.capabilities || {};
  const permissions = c.permissions || {};
  const observability = c.observability || {};
  const lifecycle = c.lifecycle || {};

  return {
    agent_id: identity.agent_id || payload.agent_id,
    name: identity.display_name || identity.name,
    description: identity.description,
    version: identity.contract_version || identity.version,
    owner: identity.owner,
    business_function: identity.business_function,
    agent_type: identity.agent_type,
    execution_mode: runtime.execution_mode || identity.execution_mode,
    status: lifecycle.status || lifecycle.initial_status,
    default_status: lifecycle.default_status || lifecycle.initial_status,
    adapter_type: runtime.adapter_type,
    entrypoint: runtime.entrypoint,
    endpoint: runtime.endpoint,
    input_schema: schemas.input_schema,
    output_schema: schemas.output_schema,
    state_schema: schemas.state_schema,
    memory_schema: schemas.memory_schema,
    skills: capabilities.skills || [],
    tools: capabilities.tools || [],
    prompts: capabilities.prompts || [],
    model_preferences: c.model_policy || capabilities.model_preferences || {},
    policy_permissions: permissions.policy_permissions || permissions || {},
    allowed_data_scopes: permissions.allowed_data_scopes || [],
    guardrails: c.guardrails || [],
    observability_hooks: observability.hooks || {},
    metadata: c.metadata || {},
    source_file: payload.source_file,
  };
}

export default function AgentRegistry() {
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const fetchAgents = useCallback(() => controlPlaneApi.listAgents(), []);
  const state = useControlData(fetchAgents, [], 10000);
  const agents = asArray(state.data, 'agents');
  const filtered = useMemo(() => agents.filter((agent) => `${agent.name} ${agent.agent_id} ${agent.business_function}`.toLowerCase().includes(query.toLowerCase())), [agents, query]);
  return (
    <>
      <PageHeader title="Agent Registry" subtitle="YAML-registered agents returned by the control plane. Select an agent to inspect its contract." right={<button className="cc-button" onClick={state.reload}>Refresh</button>} />
      <SectionCard title="Registered Agents" right={<input className="cc-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter agents" aria-label="Filter agents" />}>
        <LoadingState loading={state.loading} error={state.error} empty={!state.loading && filtered.length === 0}>No registered agents match this filter.</LoadingState>
        {filtered.length > 0 && <div className="cc-table-scroll"><table className="cc-table"><thead><tr><th>Agent Name</th><th>Agent ID</th><th>Business Function</th><th>Owner</th><th>Agent Type</th><th>Execution Mode</th><th>Status</th><th>Health</th><th>Last Run</th><th>Actions</th></tr></thead><tbody>{filtered.map((agent) => <tr key={agent.agent_id} className="clickable" onClick={() => setSelected(agent.agent_id)}><td><strong>{display(agent.name)}</strong></td><td className="mono">{display(agent.agent_id)}</td><td>{display(agent.business_function)}</td><td>{display(agent.owner)}</td><td>{display(agent.agent_type)}</td><td><ExecModeChip mode={agent.execution_mode} /></td><td><StatusChip status={agent.status} /></td><td>{agent.health ? <HealthChip health={agent.health} /> : '—'}</td><td>{display(agent.last_run)}</td><td><button className="cc-link-button">View contract</button></td></tr>)}</tbody></table></div>}
      </SectionCard>
      {selected && <ContractDrawer agentId={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
