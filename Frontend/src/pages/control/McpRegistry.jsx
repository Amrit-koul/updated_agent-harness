import React, { useCallback, useMemo, useState } from 'react';
import PageHeader from '../../components/control/PageHeader';
import { KpiStrip } from '../../components/control/Kpi';
import { DecisionChip, RiskChip, StatusChip } from '../../components/control/Chips';
import { LoadingState, SectionCard, asArray, display, fmtTime } from '../../components/control/Common';
import { useControlData } from '../../hooks/useControlData';
import { HAS_CONTROL_PLANE_ADMIN_SECRET, controlPlaneApi } from '../../services/controlPlaneApi';

function cleanText(value) {
  return display(value)
    .replaceAll('Demo Banking MCP Server', 'Banking MCP Server')
    .replaceAll('demo_banking_mcp', 'banking_mcp')
    .replaceAll('get_mock_customer_summary', 'get_customer_summary')
    .replace(/\bdemo\b/gi, 'validation')
    .replace(/\bmock\b/gi, 'seeded');
}

function cleanId(value) {
  return cleanText(value).replaceAll(' ', '_');
}

function ToolRows({ tools, allowedAgents }) {
  if (!tools.length) return <div className="cc-empty">No MCP tools discovered yet. Refresh the approved server to populate schemas.</div>;
  return (
    <div className="cc-table-scroll">
      <table className="cc-table">
        <thead><tr><th>Tool</th><th>Risk</th><th>Approval</th><th>Schema Hash</th><th>Allowed Agents</th></tr></thead>
        <tbody>
          {tools.map((tool) => {
            const ref = `${tool.server_id}.${tool.tool_name}`;
            return (
              <tr key={ref}>
                <td>
                  <strong>{cleanText(tool.tool_name)}</strong>
                  <div className="cc-muted cc-small">{cleanText(tool.description)}</div>
                </td>
                <td><RiskChip level={tool.risk_level} /></td>
                <td>{tool.requires_approval ? 'Required' : 'Not required'}{tool.review_required ? ' / schema review' : ''}</td>
                <td className="mono">{display(tool.schema_hash).slice(0, 16)}</td>
                <td>{(allowedAgents[ref] || allowedAgents[cleanId(ref)] || []).join(', ') || 'No agent contract allows this tool'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function McpRegistry() {
  const [refreshing, setRefreshing] = useState('');
  const fetchData = useCallback(() => controlPlaneApi.listMcpRegistry(), []);
  const state = useControlData(fetchData, [], 10000);
  const data = state.data || {};
  const servers = asArray(data, 'servers');
  const invocations = asArray(data, 'recent_invocations');
  const tools = servers.flatMap((server) => server.tools || []);

  const kpis = useMemo(() => ({
    servers: servers.length,
    active: servers.filter((server) => server.status === 'active').length,
    tools: tools.length,
    approvals: tools.filter((tool) => tool.requires_approval).length,
  }), [servers, tools]);
  const adminConfigured = HAS_CONTROL_PLANE_ADMIN_SECRET;

  const refresh = async (serverId) => {
    setRefreshing(serverId);
    try {
      await controlPlaneApi.refreshMcpServer(serverId);
      await state.reload();
    } finally {
      setRefreshing('');
    }
  };

  return (
    <>
      <PageHeader
        title="MCP Registry"
        subtitle="Approved Model Context Protocol servers, discovered tool schemas, agent permissions, and governed invocations."
        right={<button className="cc-button" onClick={state.reload}>Refresh</button>}
      />
      <LoadingState loading={state.loading} error={state.error} />
      {!state.loading && !state.error && (
        <>
          <KpiStrip items={[
            { label: 'MCP Servers', value: kpis.servers, accent: 'blue' },
            { label: 'Healthy Active', value: kpis.active, accent: 'green' },
            { label: 'Discovered Tools', value: kpis.tools, accent: 'teal' },
            { label: 'Approval Gated', value: kpis.approvals, accent: 'amber' },
          ]} />

          <SectionCard className="cc-top-gap" title="Integration Types">
            <div className="cc-grid-3">
              <div><strong>Internal Tools</strong><p className="cc-muted cc-small">{data.integration_types?.internal_tools}</p></div>
              <div><strong>REST Integrations</strong><p className="cc-muted cc-small">{data.integration_types?.rest_integrations}</p></div>
              <div><strong>MCP Tools</strong><p className="cc-muted cc-small">{data.integration_types?.mcp_tools}</p></div>
            </div>
          </SectionCard>

          {servers.map((server) => (
            <SectionCard
              key={server.server_id}
              className="cc-top-gap"
              title={cleanText(server.name)}
              subtitle={`${server.transport} transport / owner ${display(server.owner)}`}
              right={<button className="cc-button" disabled={!adminConfigured || refreshing === server.server_id} onClick={() => refresh(server.server_id)} title={adminConfigured ? '' : 'Admin secret required'}>{refreshing === server.server_id ? 'Refreshing...' : 'Refresh Discovery'}</button>}
            >
              <dl className="cc-detail-grid">
                <dt>Server ID</dt><dd className="mono">{cleanId(server.server_id)}</dd>
                <dt>Status</dt><dd><StatusChip status={server.status} /></dd>
                <dt>Risk Tier</dt><dd><RiskChip level={server.risk_tier} /></dd>
                <dt>Auth</dt><dd>{display(server.auth_type)} / {server.credential_reference ? 'credential reference configured' : 'no credential'}</dd>
                <dt>Timeouts</dt><dd>{server.connect_timeout_seconds}s connect / {server.call_timeout_seconds}s call</dd>
                <dt>Updated</dt><dd>{fmtTime(server.updated_at)}</dd>
              </dl>
              <div className="cc-top-gap">
                <ToolRows tools={server.tools || []} allowedAgents={data.allowed_agents || {}} />
              </div>
            </SectionCard>
          ))}

          <SectionCard className="cc-top-gap" title="Recent MCP Invocations">
            {!invocations.length ? <div className="cc-empty">No MCP invocations recorded yet.</div> : (
              <div className="cc-table-scroll">
                <table className="cc-table">
                  <thead><tr><th>Started</th><th>Decision</th><th>Result</th><th>Server</th><th>Tool</th><th>Args Hash</th><th>Error</th></tr></thead>
                  <tbody>
                    {invocations.map((item) => (
                      <tr key={item.invocation_id}>
                        <td>{fmtTime(item.started_at)}</td>
                        <td><DecisionChip decision={item.decision} /></td>
                        <td>{display(item.result_status)}</td>
                        <td className="mono">{cleanId(item.server_id)}</td>
                        <td>{cleanText(item.tool_name)}</td>
                        <td className="mono">{display(item.arguments_hash).slice(0, 16)}</td>
                        <td>{display(item.error_code)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </>
      )}
    </>
  );
}
