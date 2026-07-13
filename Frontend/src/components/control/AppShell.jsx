import React, { useCallback } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { HAS_CONTROL_PLANE_ADMIN_SECRET, controlPlaneApi } from '../../services/controlPlaneApi';
import { useControlData } from '../../hooks/useControlData';

const NAV_ITEMS = [
  ['/control/tower', 'Control Tower', '▦'],
  ['/control/agents', 'Agent Registry', '☷'],
  ['/control/observability', 'Observability', '⌁'],
  ['/control/policy-guardrails', 'Policy & Guardrails', '◇'],
  ['/control/kill-switch', 'Kill Switch & Degradation', '⏻'],
  ['/control/audit-logs', 'Audit Logs', '▤'],
  ['/control/onboarding', 'Agent Contract', '⬡'],
  ['/control/usage-cost', 'Usage & Cost', '$'],
  ['/control/rag-quality', 'RAG Quality', '≈'],
  ['/control/primitives', 'Agentic Primitives', '◆'],
  ['/control/mcp-registry', 'MCP Registry', 'M'],
];

export default function AppShell() {
  const fetchAgents = useCallback(() => controlPlaneApi.listAgents(), []);
  const status = useControlData(fetchAgents, [], 10000);
  const connected = !status.loading && !status.error;
  const navItems = HAS_CONTROL_PLANE_ADMIN_SECRET
    ? [...NAV_ITEMS.slice(0, -1), ['/control/security-rbac', 'Security & RBAC', '#'], NAV_ITEMS[NAV_ITEMS.length - 1]]
    : NAV_ITEMS;

  return (
    <div className="cc-app">
      <aside className="cc-sidebar">
        <div className="cc-brand"><strong>AI Operations<br />Control Centre</strong></div>
        <nav className="cc-sidebar-nav">
          <div className="cc-nav-section-label">Platform</div>
          {navItems.map(([to, label, icon]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `cc-nav-link${isActive ? ' active' : ''}`}>
              <span className="cc-nav-icon">{icon}</span><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="cc-agent-fleet">
          <div className="cc-agent-fleet-title">Agent Fleet</div>
          <Link to="/chat" className="cc-fleet-link">Policy Assistant</Link>
          <Link to="/loan-assessment" className="cc-fleet-link">Loan Assessment</Link>
          <Link to="/collections" className="cc-fleet-link">Collections Agent</Link>
        </div>
      </aside>
      <div className="cc-main">
        <header className="cc-topheader">
          <strong>AI Operations Control Centre</strong>
          <div className="cc-header-meta"><span className="cc-connection"><i className={connected ? 'online' : 'offline'} />{status.loading ? 'Checking services' : connected ? 'Services connected' : 'Services unavailable'}</span></div>
        </header>
        <main className="cc-content"><Outlet context={{ reloadShell: status.reload }} /></main>
      </div>
    </div>
  );
}
