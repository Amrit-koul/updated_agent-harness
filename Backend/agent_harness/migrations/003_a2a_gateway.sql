CREATE TABLE IF NOT EXISTS a2a_tasks(
    task_id TEXT PRIMARY KEY,
    context_id TEXT,
    agent_id TEXT NOT NULL,
    state TEXT NOT NULL,
    trace_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    task_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_a2a_tasks_agent_state
    ON a2a_tasks(agent_id, state);

CREATE INDEX IF NOT EXISTS idx_a2a_tasks_context
    ON a2a_tasks(context_id);
