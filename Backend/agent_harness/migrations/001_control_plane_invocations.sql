CREATE TABLE IF NOT EXISTS agent_invocations (
    invocation_id TEXT PRIMARY KEY,
    trace_id TEXT,
    agent_id TEXT,
    principal_id TEXT,
    action TEXT,
    lifecycle_status TEXT,
    decision TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    error_code TEXT,
    request_json TEXT,
    result_json TEXT
);

CREATE TABLE IF NOT EXISTS runtime_phase_events (
    id INTEGER PRIMARY KEY,
    invocation_id TEXT,
    trace_id TEXT,
    agent_id TEXT,
    phase TEXT,
    status TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_invocations_trace_id
    ON agent_invocations(trace_id);

CREATE INDEX IF NOT EXISTS idx_runtime_phase_events_invocation_id
    ON runtime_phase_events(invocation_id);
