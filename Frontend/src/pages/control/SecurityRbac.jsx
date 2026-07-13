import React, { useCallback, useMemo, useState } from 'react';
import PageHeader from '../../components/control/PageHeader';
import { KpiStrip } from '../../components/control/Kpi';
import { DecisionChip, StatusChip } from '../../components/control/Chips';
import { LoadingState, SectionCard, asArray, display, fmtTime } from '../../components/control/Common';
import { useControlData } from '../../hooks/useControlData';
import { HAS_CONTROL_PLANE_ADMIN_SECRET, controlPlaneApi } from '../../services/controlPlaneApi';

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

export default function SecurityRbac() {
  const [principalId, setPrincipalId] = useState('');
  const adminConfigured = HAS_CONTROL_PLANE_ADMIN_SECRET;

  const fetchData = useCallback(async () => {
    if (!adminConfigured) {
      return { adminDisabled: true, principals: [], roles: [], decisions: [], effective: null, selected: '' };
    }
    const [principals, roles, decisions] = await Promise.all([
      controlPlaneApi.listPrincipals(),
      controlPlaneApi.listRoles(),
      controlPlaneApi.listAuthorizationDecisions(),
    ]);
    const principalRows = asArray(principals, 'principals');
    const selected = principalId || principalRows[0]?.principal_id || '';
    const effective = selected
      ? await controlPlaneApi.getEffectivePermissions(selected).catch(() => null)
      : null;
    return {
      principals: principalRows,
      roles: asArray(roles, 'roles'),
      decisions: asArray(decisions, 'decisions'),
      effective,
      selected,
    };
  }, [adminConfigured, principalId]);

  const state = useControlData(fetchData, [principalId], 10000);
  const data = state.data || { principals: [], roles: [], decisions: [], effective: null, selected: principalId };
  const selectedPrincipal = data.principals.find((item) => item.principal_id === data.selected);
  const selectedDecisions = data.decisions.filter((item) => item.principal_id === data.selected);

  const kpis = useMemo(() => ({
    principals: data.principals.length,
    activePrincipals: data.principals.filter((item) => item.status === 'active').length,
    roles: data.roles.length,
    denied: data.decisions.filter((item) => item.decision === 'DENY').length,
  }), [data]);

  const resourceTypes = unique(data.effective?.permissions?.map((item) => item.resource_type) || []);

  return (
    <>
      <PageHeader
        title="Security & RBAC"
        subtitle="Agent principals, role bindings, effective permissions, and authorization decisions from the control-plane boundary."
        right={<button className="cc-button" disabled={!adminConfigured} onClick={state.reload}>Refresh</button>}
      />
      <LoadingState loading={state.loading} error={state.error} />
      {(state.error || data.adminDisabled) && (
        <SectionCard title="Admin Access" subtitle="Administrative identity is intentionally required before RBAC data is requested.">
          <p className="cc-muted cc-small">
            Configure backend CONTROL_PLANE_ADMIN_SECRET and matching frontend VITE_CONTROL_PLANE_ADMIN_SECRET to enable RBAC administration.
          </p>
        </SectionCard>
      )}
      {!state.loading && !state.error && !data.adminDisabled && (
        <>
          <KpiStrip items={[
            { label: 'Principals', value: kpis.principals, accent: 'blue' },
            { label: 'Active Principals', value: kpis.activePrincipals, accent: 'green' },
            { label: 'Roles', value: kpis.roles, accent: 'teal' },
            { label: 'Denied Decisions', value: kpis.denied, accent: 'red' },
          ]} />

          <SectionCard className="cc-top-gap" title="Principal Selector" subtitle="Inspect one agent principal and its resolved permissions.">
            <select className="cc-input" value={data.selected} onChange={(event) => setPrincipalId(event.target.value)}>
              {data.principals.map((principal) => (
                <option key={principal.principal_id} value={principal.principal_id}>
                  {principal.display_name || principal.agent_id} - {principal.principal_id}
                </option>
              ))}
            </select>
            {selectedPrincipal && (
              <dl className="cc-detail-grid cc-top-gap">
                <dt>Agent ID</dt><dd className="mono">{selectedPrincipal.agent_id}</dd>
                <dt>Principal ID</dt><dd className="mono">{selectedPrincipal.principal_id}</dd>
                <dt>Type</dt><dd>{display(selectedPrincipal.principal_type)}</dd>
                <dt>Status</dt><dd><StatusChip status={selectedPrincipal.status} /></dd>
                <dt>Credential Reference</dt><dd>{display(selectedPrincipal.credential_reference) || 'Not configured'}</dd>
              </dl>
            )}
          </SectionCard>

          <div className="cc-grid-2 cc-top-gap">
            <SectionCard title="Assigned Roles">
              {!data.effective?.roles?.length ? <div className="cc-empty">No valid roles returned.</div> : (
                <div className="cc-table-scroll"><table className="cc-table"><thead><tr><th>Role</th><th>Scope</th><th>Valid Until</th></tr></thead><tbody>
                  {data.effective.roles.map((role) => (
                    <tr key={`${role.role_id}-${role.scope_type}-${role.scope_value}`}>
                      <td>{display(role.role_name)}</td>
                      <td className="mono">{role.scope_type}:{role.scope_value}</td>
                      <td>{fmtTime(role.valid_until)}</td>
                    </tr>
                  ))}
                </tbody></table></div>
              )}
            </SectionCard>

            <SectionCard title="Permission Coverage" subtitle={resourceTypes.length ? `Resources: ${resourceTypes.join(', ')}` : ''}>
              {!data.effective?.permissions?.length ? <div className="cc-empty">No effective permissions returned.</div> : (
                <div className="cc-token-list">
                  {data.effective.permissions.map((permission) => (
                    <span key={`${permission.permission_id}-${permission.role_id}-${permission.scope_type}-${permission.scope_value}`}>
                      {permission.permission_id}
                    </span>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>

          <SectionCard className="cc-top-gap" title="Recent Authorization Decisions">
            {!selectedDecisions.length ? <div className="cc-empty">No authorization decisions recorded for this principal yet.</div> : (
              <div className="cc-table-scroll"><table className="cc-table"><thead><tr><th>Time</th><th>Decision</th><th>Resource</th><th>Action</th><th>Reason</th><th>Invocation</th></tr></thead><tbody>
                {selectedDecisions.map((item) => (
                  <tr key={item.decision_id}>
                    <td>{fmtTime(item.timestamp)}</td>
                    <td><DecisionChip decision={item.decision} /></td>
                    <td className="mono">{item.resource_type}:{item.resource_id}</td>
                    <td>{display(item.requested_action)}</td>
                    <td>{display(item.reason_code)}</td>
                    <td className="mono">{display(item.invocation_id)}</td>
                  </tr>
                ))}
              </tbody></table></div>
            )}
          </SectionCard>
        </>
      )}
    </>
  );
}
