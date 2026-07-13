import React, { useCallback, useMemo, useState } from 'react';
import PageHeader from '../../components/control/PageHeader';
import { KpiStrip } from '../../components/control/Kpi';
import { Chip, StatusChip } from '../../components/control/Chips';
import { ActionButton, LoadingState, SectionCard, asArray, display, fmtTime, parseControlTimestamp } from '../../components/control/Common';
import { useControlData } from '../../hooks/useControlData';
import { controlPlaneApi } from '../../services/controlPlaneApi';
import { SourceBadge } from '../../utils/evidenceLabels';

const RAG_AGENT_IDS = new Set(['policy_assistant_agent']);
const REACTIVATION_OVERRIDE_TYPES = new Set(['reactivate_after_review', 'break_glass_expiring']);

const STATUS_HELP = {
  active: 'Serving traffic',
  review: 'Human review required',
  quarantined: 'Blocked by safety control',
  disabled: 'Manually stopped',
};

const TRANSITION_HELP = {
  active: 'Activation requires Review as the current state, a change ticket, and two distinct approvers.',
  review: 'Review is the safe staging state for investigation, recovery, and reactivation.',
  quarantined: 'Quarantine immediately blocks runtime execution after critical safety events.',
  disabled: 'Disable is an administrative stop for planned maintenance or controlled shutdown.',
};

const STATUS_OPTIONS = ['active', 'review', 'quarantined', 'disabled'];

function isRagAgent(agent) {
  if (!agent) return false;
  if (agent.agent_capability === 'rag') return true;
  return RAG_AGENT_IDS.has(agent.agent_id);
}

function parseEvidence(row) {
  if (!row?.evidence_json) return {};
  if (typeof row.evidence_json === 'object') return row.evidence_json;
  try {
    return JSON.parse(row.evidence_json);
  } catch {
    return {};
  }
}

function rowTime(row) {
  const parsed = parseControlTimestamp(row?.created_at || row?.timestamp);
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed.getTime() : 0;
}

function latestByAgent(rows) {
  const byAgent = new Map();
  rows
    .slice()
    .sort((a, b) => rowTime(b) - rowTime(a))
    .forEach((row) => {
      if (row.agent_id && !byAgent.has(row.agent_id)) byAgent.set(row.agent_id, row);
    });
  return Array.from(byAgent.values());
}

function pct(value) {
  if (value == null || value === '') return <span className="cc-muted">No signal</span>;
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return display(value);
  return `${Math.round(numeric * 100)}%`;
}

function qualityGate(row) {
  const values = [
    row.groundedness_score,
    row.semantic_similarity_score,
    row.answer_relevance_score,
    row.retrieved_evidence_coverage ?? row.citation_coverage,
  ].filter((value) => value != null);
  if (!values.length) return 'review';
  if (values.some((value) => Number(value) < 0.4)) return 'quarantined';
  if (values.some((value) => Number(value) < 0.6)) return 'review';
  return 'active';
}

function qualityAction(row) {
  const gate = qualityGate(row);
  if (gate === 'quarantined') return 'Investigate evidence gap';
  if (gate === 'review') return 'Review grounding';
  return 'No action';
}

function evidenceText(row) {
  const coverage = row.retrieved_evidence_coverage ?? row.citation_coverage;
  const count = row.retrieved_chunk_count ?? row.cited_chunk_count;
  if (coverage != null && count != null) return `${pct(coverage)} / ${count} source${Number(count) === 1 ? '' : 's'}`;
  if (coverage != null) return pct(coverage);
  if (count != null) return `${count} source${Number(count) === 1 ? '' : 's'}`;
  return <span className="cc-muted">No evidence</span>;
}

function normalizeDecision(value) {
  return String(value || '').toUpperCase();
}

function getLifecycleSignal(agent, evaluation, policyDecisions) {
  if (isRagAgent(agent)) {
    if (!evaluation) {
      return { signal: 'No RAG quality signal yet', action: 'Run the agent to collect quality evidence', controlPoint: 'Observability' };
    }
    const groundedness = Math.round(Number(evaluation.groundedness_score || 0) * 100);
    return {
      signal: `${groundedness}% groundedness`,
      action: groundedness < 60 ? 'Review grounding before continued use' : 'No action',
      controlPoint: 'Observability',
    };
  }

  const latestPolicy = policyDecisions
    .filter((item) => item.agent_id === agent.agent_id)
    .sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)))[0];

  if (!latestPolicy) {
    return { signal: 'No policy decisions recorded', action: 'No action', controlPoint: 'Policy Engine' };
  }

  const decision = normalizeDecision(latestPolicy.decision);
  return {
    signal: `${decision}: ${latestPolicy.reason || 'Policy decision recorded'}`,
    action: decision === 'BLOCK' ? 'Investigate before reactivation' : decision === 'REVIEW' ? 'Review case evidence' : 'No action',
    controlPoint: 'Policy Engine',
  };
}

function agentTypeDisplay(agent) {
  const execMode = agent.execution_mode || '';
  const agentType = agent.agent_type || '';
  if (isRagAgent(agent)) return 'RAG Agent';
  if (['external_plugin', 'github_wrapped_workflow'].includes(agentType)) return 'Workflow / External Plugin';
  if (agentType === 'vendor') return 'Vendor Agent';
  if (execMode === 'voice') return 'Voice Agent';
  if (execMode === 'workflow') return 'Workflow Agent';
  return 'Agent';
}

function actionFor(agent, signal) {
  if (agent.status === 'review') return 'Review evidence, then approve or stop';
  if (agent.status === 'quarantined') return 'Hard blocked; move to Review after investigation';
  if (agent.status === 'disabled') return 'Stopped; move to Review before reactivation';
  return signal.action || 'No action';
}

function missingApprovalFields(override) {
  const missing = ['reason', 'approved_by', 'override_type', 'change_ticket'].filter((key) => !String(override[key] || '').trim());
  if (override.status === 'active') {
    const first = String(override.approved_by || '').trim().toLowerCase();
    const second = String(override.second_approved_by || '').trim().toLowerCase();
    if (!second) missing.push('second_approved_by');
    if (first && second && first === second) missing.push('distinct_second_approver');
    if (!REACTIVATION_OVERRIDE_TYPES.has(override.override_type)) missing.push('reactivation_override_type');
  }
  return missing;
}

function defaultOverrideType(status) {
  return status === 'active' ? 'reactivate_after_review' : 'manual_lifecycle_change';
}

function missingLabel(key) {
  const labels = {
    approved_by: 'approver',
    second_approved_by: 'second approver',
    distinct_second_approver: 'two distinct approvers',
    reactivation_override_type: 'reactivation override type',
    change_ticket: 'change ticket',
    override_type: 'override type',
  };
  return labels[key] || key;
}

function transitionWarning(currentStatus, targetStatus) {
  if (!currentStatus || currentStatus === targetStatus) return null;
  if (targetStatus === 'active' && currentStatus !== 'review') {
    return 'Reactivation must go through Review first. Move this agent to Review, complete investigation, then activate it.';
  }
  return null;
}

export default function KillSwitchDegradation() {
  const [excludeTest, setExcludeTest] = useState(true);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState(null);
  const [agentId, setAgentId] = useState('collections_workflow_agent');
  const [showValidation, setShowValidation] = useState(false);
  const [override, setOverride] = useState({
    status: 'review',
    reason: 'quality_or_safety_review_required',
    approved_by: 'ops_admin',
    second_approved_by: 'risk_admin',
    override_type: 'manual_lifecycle_change',
    change_ticket: 'CHG-CONTROL-001',
  });

  const fetchData = useCallback(async () => {
    const [agents, kill, degradation, policy, guardrails, evaluations] = await Promise.all([
      controlPlaneApi.listAgents(),
      controlPlaneApi.listKillSwitchEvents(),
      controlPlaneApi.listDegradationEvents(),
      controlPlaneApi.listPolicyDecisions(),
      controlPlaneApi.listGuardrailEvents(),
      controlPlaneApi.listEvaluations(),
    ]);
    return {
      agents: asArray(agents, 'agents'),
      kill: asArray(kill, 'events'),
      degradation: asArray(degradation, 'events'),
      policy: asArray(policy, 'decisions'),
      guardrails: asArray(guardrails, 'events'),
      evaluations: asArray(evaluations, 'evaluations'),
    };
  }, []);

  const state = useControlData(fetchData, [], 5000);
  const data = state.data || { agents: [], kill: [], degradation: [], policy: [], guardrails: [], evaluations: [] };
  const selectedAgent = data.agents.find((agent) => agent.agent_id === agentId) || data.agents[0];
  const currentStatus = selectedAgent?.status || 'unknown';
  const warning = transitionWarning(currentStatus, override.status);
  const missing = missingApprovalFields(override);
  const canSubmit = !warning && missing.length === 0 && currentStatus !== override.status;

  const filterEvents = (rows) => {
    if (!excludeTest) return rows;
    return rows.filter((event) => {
      const source = String(event.source || '').toLowerCase();
      return !event.is_simulated && !['admin_validation', 'manual_validation', 'simulation', 'demo_endpoint'].includes(source);
    });
  };

  const kill = filterEvents(data.kill);
  const degradation = filterEvents(data.degradation);
  const guardrails = filterEvents(data.guardrails);
  const policy = filterEvents(data.policy);
  const evaluations = filterEvents(data.evaluations);
  const ragEvaluations = latestByAgent(evaluations.filter((item) => isRagAgent({ agent_id: item.agent_id, agent_capability: item.agent_capability })));

  const counts = useMemo(() => STATUS_OPTIONS.reduce(
    (out, status) => ({ ...out, [status]: data.agents.filter((agent) => agent.status === status).length }),
    {},
  ), [data.agents]);

  const timeline = useMemo(() => {
    function lifecycleLabel(row) {
      if (row.source === 'manual_admin') return 'Manual lifecycle change';
      if (row.new_status === 'disabled' || row.new_status === 'quarantined') return 'Kill switch engaged';
      if (row.new_status === 'review') return 'Moved to review';
      if (row.new_status === 'active') return 'Reactivated';
      return 'Lifecycle status changed';
    }

    return [
      ...kill.map((row) => ({
        ...row,
        type: lifecycleLabel(row),
        time: row.timestamp,
        trigger: row.reason,
        next: row.new_status,
        evidence: parseEvidence(row),
      })),
      ...degradation.map((row) => ({ ...row, type: 'Quality degradation', time: row.created_at || row.timestamp, trigger: row.reason, next: 'review' })),
      ...guardrails.map((row) => ({ ...row, type: 'Guardrail event', time: row.timestamp, trigger: row.reason, next: row.decision })),
      ...policy.map((row) => ({ ...row, type: 'Policy decision', time: row.timestamp, trigger: row.reason, next: row.decision })),
    ].sort((a, b) => String(b.time).localeCompare(String(a.time))).slice(0, 30);
  }, [kill, degradation, guardrails, policy]);

  async function applyOverride() {
    setBusy('override');
    setNotice(null);
    try {
      const result = await controlPlaneApi.changeAgentStatus(agentId, {
        ...override,
        source: 'manual_admin',
        triggered_by: 'audited_control_panel',
      });
      setNotice(`Lifecycle change recorded: ${result.previous_status} -> ${result.new_status}.`);
      state.reload();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy('');
    }
  }

  async function runValidation(kind) {
    setBusy(kind);
    setNotice(null);
    try {
      if (kind === 'unsafe') await controlPlaneApi.runUnsafeSql({ agent_id: agentId, sql: 'DROP TABLE customers;' });
      else if (kind === 'quality') await controlPlaneApi.simulateDegradation({ agent_id: agentId, scenario: 'low_groundedness' });
      else await controlPlaneApi.invokeAgent(agentId, { query: 'Governed validation invocation' });
      setNotice('Validation action recorded in the evidence timeline.');
      state.reload();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <>
      <PageHeader
        title="Kill Switch"
        subtitle="A clear lifecycle workflow for reviewing, stopping, quarantining, and safely reactivating governed agents."
        right={(
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <label className="cc-switch">
              <input type="checkbox" checked={!excludeTest} onChange={(event) => setExcludeTest(!event.target.checked)} />
              Include validation evidence
            </label>
            <button className="cc-button" onClick={state.reload}>Refresh</button>
          </div>
        )}
      />

      {notice && <div className="cc-notice info">{notice}</div>}
      <LoadingState loading={state.loading} error={state.error} />

      {!state.loading && !state.error && (
        <>
          <KpiStrip items={[
            { label: 'Active', value: counts.active },
            { label: 'Review', value: counts.review, accent: 'amber' },
            { label: 'Quarantined', value: counts.quarantined, accent: 'red' },
            { label: 'Disabled', value: counts.disabled, accent: 'grey' },
            { label: 'Automatic Changes', value: degradation.filter((row) => row.source === 'automatic').length + kill.filter((row) => row.source === 'automatic').length, accent: 'purple' },
            { label: 'Manual Changes', value: kill.filter((row) => row.source === 'manual_admin').length, accent: 'teal' },
          ]} />

          <SectionCard className="cc-top-gap" title="Lifecycle Path" subtitle="Production rule: stopped agents go to Review before they can return to Active.">
            <div className="cc-lifecycle-path">
              {STATUS_OPTIONS.map((status) => (
                <div key={status} className={`cc-lifecycle-step ${status}`}>
                  <StatusChip status={status} />
                  <strong>{STATUS_HELP[status]}</strong>
                  <span>{TRANSITION_HELP[status]}</span>
                </div>
              ))}
            </div>
          </SectionCard>

          <div className="cc-grid-2 cc-top-gap">
            <SectionCard title="Lifecycle Change" subtitle="Select the agent, choose the target state, and provide approval evidence.">
              <div className="cc-detail-grid">
                <dt>Agent</dt>
                <dd>
                  <select className="cc-input" value={agentId} onChange={(event) => setAgentId(event.target.value)}>
                    {data.agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.name || agent.agent_id}</option>)}
                  </select>
                </dd>
                <dt>Current state</dt><dd><StatusChip status={currentStatus} /> <span className="cc-muted cc-small">{STATUS_HELP[currentStatus]}</span></dd>
                <dt>Target state</dt>
                <dd>
                  <select
                    className="cc-input"
                    value={override.status}
                    onChange={(event) => {
                      const status = event.target.value;
                      setOverride({ ...override, status, override_type: defaultOverrideType(status) });
                    }}
                  >
                    {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </dd>
                <dt>Reason</dt><dd><input className="cc-input" value={override.reason} onChange={(event) => setOverride({ ...override, reason: event.target.value })} /></dd>
                <dt>Change ticket</dt><dd><input className="cc-input" value={override.change_ticket} onChange={(event) => setOverride({ ...override, change_ticket: event.target.value })} /></dd>
                <dt>Override type</dt>
                <dd>
                  <select className="cc-input" value={override.override_type} onChange={(event) => setOverride({ ...override, override_type: event.target.value })}>
                    {override.status === 'active' ? (
                      <>
                        <option value="reactivate_after_review">reactivate_after_review</option>
                        <option value="break_glass_expiring">break_glass_expiring</option>
                      </>
                    ) : (
                      <option value="manual_lifecycle_change">manual_lifecycle_change</option>
                    )}
                  </select>
                </dd>
                <dt>Approver</dt><dd><input className="cc-input" value={override.approved_by} onChange={(event) => setOverride({ ...override, approved_by: event.target.value })} /></dd>
                <dt>Second approver</dt><dd><input className="cc-input" value={override.second_approved_by} onChange={(event) => setOverride({ ...override, second_approved_by: event.target.value })} /></dd>
              </div>

              <div className={`cc-transition-summary ${warning || missing.length ? 'blocked' : 'ready'}`}>
                <strong>{currentStatus} to {override.status}</strong>
                <span>{warning || (missing.length ? `Missing: ${missing.map(missingLabel).join(', ')}` : TRANSITION_HELP[override.status])}</span>
              </div>

              <ActionButton loading={busy === 'override'} disabled={!canSubmit} onClick={applyOverride}>
                Record Lifecycle Change
              </ActionButton>
            </SectionCard>

            <SectionCard title="Agent Lifecycle Board" subtitle="Current state and latest governance signal for each registered agent.">
              <LifecycleBoard agents={data.agents} kill={kill} policy={policy} evaluations={ragEvaluations} />
            </SectionCard>
          </div>

          <div className="cc-grid-2 cc-top-gap">
            <SectionCard title="Intervention Timeline" subtitle="Most recent lifecycle, policy, guardrail, and degradation events.">
              <Timeline rows={timeline} />
            </SectionCard>
            <SectionCard title="RAG Quality Monitor" subtitle="Latest retrieval quality signal per RAG agent. Validation evidence is hidden unless enabled above.">
              <Quality rows={ragEvaluations} />
            </SectionCard>
          </div>

          <SectionCard
            className="cc-top-gap"
            title="Validation Actions"
            subtitle="Internal validation controls for exercising policy blocks and degradation flows."
            right={<button className="cc-button" onClick={() => setShowValidation(!showValidation)}>{showValidation ? 'Hide' : 'Show'}</button>}
          >
            {showValidation ? (
              <div className="cc-actions">
                <ActionButton danger loading={busy === 'unsafe'} onClick={() => runValidation('unsafe')}>Unsafe SQL Test</ActionButton>
                <ActionButton loading={busy === 'quality'} onClick={() => runValidation('quality')}>Quality Degradation Test</ActionButton>
                <ActionButton loading={busy === 'invoke'} onClick={() => runValidation('invoke')}>Invoke Current State</ActionButton>
              </div>
            ) : <div className="cc-empty">Validation controls are hidden during normal operations.</div>}
          </SectionCard>
        </>
      )}
    </>
  );
}

function LifecycleBoard({ agents, kill, policy, evaluations }) {
  if (!agents.length) return <div className="cc-empty">No agents registered.</div>;
  return (
    <div className="cc-table-scroll">
      <table className="cc-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Type</th>
            <th>Status</th>
            <th>Last Change</th>
            <th>Signal</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => {
            const event = kill.find((row) => row.agent_id === agent.agent_id);
            const evaluation = evaluations.find((row) => row.agent_id === agent.agent_id);
            const signal = getLifecycleSignal(agent, evaluation, policy);
            return (
              <tr key={agent.agent_id}>
                <td><strong>{display(agent.name || agent.agent_id)}</strong><div className="mono">{agent.agent_id}</div></td>
                <td>{agentTypeDisplay(agent)}</td>
                <td><StatusChip status={agent.status} /></td>
                <td>{fmtTime(event?.timestamp)}</td>
                <td>{signal.signal}<div className="cc-muted cc-small">{signal.controlPoint}</div></td>
                <td>{actionFor(agent, signal)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ rows }) {
  if (!rows.length) return <div className="cc-empty">No runtime interventions recorded.</div>;
  return (
    <div className="cc-table-scroll">
      <table className="cc-table">
        <thead><tr><th>Time</th><th>Source</th><th>Agent</th><th>Event</th><th>Reason</th><th>Result</th><th>Approval</th></tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || index}>
              <td>{fmtTime(row.time)}</td>
              <td><SourceBadge source={row.source} /></td>
              <td className="mono">{display(row.agent_id)}</td>
              <td><Chip value={row.type} /></td>
              <td>{display(row.trigger)}</td>
              <td><StatusChip status={row.next} /></td>
              <td>{row.approved_by ? `${row.approved_by}${row.evidence?.second_approved_by ? ` / ${row.evidence.second_approved_by}` : ''}` : display(row.evidence?.change_ticket)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Quality({ rows }) {
  if (!rows.length) return <div className="cc-empty">No runtime RAG quality signals recorded. Run the Policy Assistant agent to populate this view.</div>;
  return (
    <div className="cc-table-scroll">
      <table className="cc-table">
        <thead><tr><th>Agent</th><th>Last Checked</th><th>Groundedness</th><th>Similarity</th><th>Evidence Coverage</th><th>Quality State</th><th>Action</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.evaluation_id}>
              <td>{display(row.agent_id)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{fmtTime(row.created_at || row.timestamp)}</td>
              <td>{pct(row.groundedness_score)}</td>
              <td>{pct(row.semantic_similarity_score)}</td>
              <td>{evidenceText(row)}</td>
              <td><StatusChip status={qualityGate(row)} /></td>
              <td>{qualityAction(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
