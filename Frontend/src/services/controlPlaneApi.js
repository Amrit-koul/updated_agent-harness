const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
const PREFIX = '/api/v1/control';
const HAS_CONTROL_PLANE_ADMIN_SECRET = Boolean(import.meta.env.VITE_CONTROL_PLANE_ADMIN_SECRET);

async function request(path, options = {}) {
  const adminSecret = import.meta.env.VITE_CONTROL_PLANE_ADMIN_SECRET;
  const response = await fetch(`${API_BASE}${PREFIX}${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(adminSecret ? { 'X-Control-Plane-Admin-Secret': adminSecret } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

const post = (path, body = {}) => request(path, { method: 'POST', body: JSON.stringify(body) });
const del = (path) => request(path, { method: 'DELETE' });

export const controlPlaneApi = {
  listAgents: () => request('/agents'),
  getAgent: (id) => request(`/agents/${encodeURIComponent(id)}`),
  getContract: (id) => request(`/agents/${encodeURIComponent(id)}/contract`),
  getStatus: (id) => request(`/agents/${encodeURIComponent(id)}/status`),
  getHealth: (id) => request(`/agents/${encodeURIComponent(id)}/health`),
  invokeAgent: (id, body = {}) => post(`/agents/${encodeURIComponent(id)}/invoke`, body),
  listRuns: () => request('/runs'),
  getRun: (traceId) => request(`/runs/${encodeURIComponent(traceId)}`),
  listEvents: () => request('/events'),
  listEvaluations: () => request('/evaluations'),
  getTraceEvents: (traceId) => request(`/events/${encodeURIComponent(traceId)}`),
  listPolicyDecisions: () => request('/policy/decisions'),
  listGuardrails: () => request('/guardrails'),
  listGuardrailEvents: () => request('/guardrails/events'),
  listToolAuthorizationEvents: () => request('/tools/authorization-events'),
  authorizeToolAction: (body = {}) => post('/tools/authorize', body),
  listMcpRegistry: () => request('/mcp/servers'),
  getMcpServer: (id) => request(`/mcp/servers/${encodeURIComponent(id)}`),
  refreshMcpServer: (id) => post(`/mcp/servers/${encodeURIComponent(id)}/refresh`),
  listMcpInvocations: () => request('/mcp/invocations'),
  invokeMcpTool: (agentId, serverId, toolName, body = {}) =>
    post(`/agents/${encodeURIComponent(agentId)}/mcp/${encodeURIComponent(serverId)}/${encodeURIComponent(toolName)}`, body),
  listKillSwitchEvents: () => request('/kill-switch/events'),
  listDegradationEvents: () => request('/degradation/events'),
  runUnsafeSql: (body = {}) => post('/demo/run-unsafe-sql', body),
  changeAgentStatus: (id, body = {}) => post(`/kill-switch/${encodeURIComponent(id)}`, body),
  simulateDegradation: (body = {}) => post('/demo/simulate-degradation', body),
  runPolicyAgent: (body = {}) => post('/demo/run-policy-agent', body),
  runLoanAssessment: (body = {}) => post('/demo/run-loan-assessment', body),
  // Collections — multi-mode, server-side extraction
  runCollections: (body = {}) => post('/demo/run-collections', body),
  runCollectionsPreCall: (accountId) =>
    post('/demo/run-collections', { mode: 'pre_call', account_id: accountId }),
  runCollectionsPostCall: (accountId, transcript, capturedId) =>
    post('/demo/run-collections', {
      mode: 'post_call',
      account_id: accountId,
      ...(capturedId ? { captured_transcript_id: capturedId } : {}),
      ...(transcript ? { transcript } : {}),
    }),
  runCollectionsFullLifecycle: (accountId, capturedId, transcript) =>
    post('/demo/run-collections', {
      mode: 'full_lifecycle',
      account_id: accountId,
      ...(capturedId ? { captured_transcript_id: capturedId } : {}),
      ...(transcript ? { transcript } : {}),
    }),
  listCollectionsAccounts: () => request('/demo/collections/accounts'),
  getCollectionsTranscripts: () => request('/collections/transcripts'),
  getCollectionsHistory: (accountId) =>
    request(`/collections/${encodeURIComponent(accountId)}/history`),
  getUsageSummary: () => request('/usage/summary'),
  listUsageEvents: () => request('/usage/events'),
  getUsageBudgets: () => request('/usage/budgets'),
  listSkills: () => request('/skills'),
  listTools: () => request('/tools'),
  getPrimitiveValidation: () => request('/primitives/validation'),
  listMemoryContracts: () => request('/memory/contracts'),
  listMemoryEvents: () => request('/memory/events'),
  listHooks: () => request('/hooks'),
  listHookEvents: () => request('/hooks/events'),
  getObservabilityStatus: () => request('/observability/status'),  // ← added
  listPrompts: () => request('/prompts'),
  listEvaluators: () => request('/evaluators'),
  listPrincipals: () => request('/security/principals'),
  getPrincipal: (id) => request(`/security/principals/${encodeURIComponent(id)}`),
  createPrincipal: (body = {}) => post('/security/principals', body),
  disablePrincipal: (id, body = {}) => post(`/security/principals/${encodeURIComponent(id)}/disable`, body),
  listRoles: () => request('/security/roles'),
  assignRole: (principalId, body = {}) => post(`/security/principals/${encodeURIComponent(principalId)}/roles`, body),
  revokeRole: (principalId, roleId, scopeType = 'global', scopeValue = '*') =>
    del(`/security/principals/${encodeURIComponent(principalId)}/roles/${encodeURIComponent(roleId)}?scope_type=${encodeURIComponent(scopeType)}&scope_value=${encodeURIComponent(scopeValue)}`),
  getEffectivePermissions: (principalId) => request(`/security/principals/${encodeURIComponent(principalId)}/effective-permissions`),
  listAuthorizationDecisions: () => request('/security/authorization-decisions'),
};

export { API_BASE, HAS_CONTROL_PLANE_ADMIN_SECRET };
