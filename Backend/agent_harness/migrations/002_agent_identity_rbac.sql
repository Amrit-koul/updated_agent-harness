CREATE TABLE IF NOT EXISTS agent_principals(
  principal_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL UNIQUE,
  principal_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  credential_reference TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roles(
  role_id TEXT PRIMARY KEY,
  role_name TEXT NOT NULL UNIQUE,
  description TEXT,
  system_role INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS permissions(
  permission_id TEXT PRIMARY KEY,
  resource_type TEXT NOT NULL,
  action TEXT NOT NULL,
  description TEXT
);

CREATE TABLE IF NOT EXISTS role_permissions(
  role_id TEXT NOT NULL,
  permission_id TEXT NOT NULL,
  PRIMARY KEY(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS principal_roles(
  principal_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  scope_type TEXT NOT NULL DEFAULT 'global',
  scope_value TEXT NOT NULL DEFAULT '*',
  valid_from TEXT,
  valid_until TEXT,
  granted_by TEXT,
  granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(principal_id, role_id, scope_type, scope_value)
);

CREATE TABLE IF NOT EXISTS authorization_decisions(
  decision_id TEXT PRIMARY KEY,
  invocation_id TEXT,
  principal_id TEXT,
  resource_type TEXT,
  resource_id TEXT,
  requested_action TEXT,
  resolved_roles TEXT,
  resolved_permissions TEXT,
  decision TEXT,
  reason_code TEXT,
  policy_version TEXT,
  timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_principals_agent_id ON agent_principals(agent_id);
CREATE INDEX IF NOT EXISTS idx_principal_roles_principal ON principal_roles(principal_id);
CREATE INDEX IF NOT EXISTS idx_authorization_decisions_principal ON authorization_decisions(principal_id);
CREATE INDEX IF NOT EXISTS idx_authorization_decisions_invocation ON authorization_decisions(invocation_id);
CREATE INDEX IF NOT EXISTS idx_authorization_decisions_timestamp ON authorization_decisions(timestamp);
