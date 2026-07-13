"""Generic SQLite control-plane persistence implementation."""
import json
import sqlite3
import hashlib
import uuid
from pathlib import Path
from threading import Lock


class ControlPlaneStore:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False); self.conn.row_factory = sqlite3.Row; self.lock = Lock()
        with self.conn: self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents(agent_id TEXT PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_contracts(agent_id TEXT PRIMARY KEY, contract_json TEXT, source_file TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_runs(trace_id TEXT PRIMARY KEY, agent_id TEXT, status TEXT, started_at TEXT, completed_at TEXT, latency_ms INTEGER, confidence REAL, input_json TEXT, output_json TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS observability_events(id INTEGER PRIMARY KEY, trace_id TEXT, agent_id TEXT, event_type TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS policy_decisions(id INTEGER PRIMARY KEY, trace_id TEXT, agent_id TEXT, action TEXT, decision TEXT, reason TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS guardrail_events(id INTEGER PRIMARY KEY, trace_id TEXT, agent_id TEXT, guardrail_id TEXT, decision TEXT, severity TEXT, reason TEXT, matched_rule TEXT, suggested_action TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS kill_switch_events(id INTEGER PRIMARY KEY, agent_id TEXT, old_status TEXT, new_status TEXT, source TEXT, reason TEXT, triggered_by TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS degradation_events(id INTEGER PRIMARY KEY, agent_id TEXT, source TEXT, reason TEXT, metrics_json TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_memory(agent_id TEXT, entity_id TEXT, memory_json TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(agent_id,entity_id));
        CREATE TABLE IF NOT EXISTS rag_evaluations(evaluation_id TEXT PRIMARY KEY, trace_id TEXT, agent_id TEXT, query_hash TEXT, groundedness_score REAL, semantic_similarity_score REAL, llm_judge_score REAL, answer_relevance_score REAL, citation_coverage REAL, retrieved_chunk_count INTEGER, cited_chunk_count INTEGER, evaluator_method TEXT, evaluator_prompt_id TEXT, evaluator_prompt_version TEXT, reason TEXT, metadata_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS usage_events(usage_id TEXT PRIMARY KEY, trace_id TEXT, run_id TEXT, agent_id TEXT, agent_name TEXT, business_function TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, estimated_input_cost REAL, estimated_output_cost REAL, estimated_total_cost REAL, currency TEXT, pricing_source TEXT, usage_source TEXT, estimated_method TEXT, latency_ms INTEGER, retry_count INTEGER DEFAULT 0, fallback_used INTEGER DEFAULT 0, fallback_from_model TEXT, fallback_to_model TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, metadata_json TEXT);
        CREATE TABLE IF NOT EXISTS budget_definitions(definition_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, policy_json TEXT NOT NULL, provider TEXT, model TEXT, currency TEXT DEFAULT 'USD', active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS budget_usage_periods(period_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, agent_id TEXT NOT NULL, period_type TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, input_tokens_used INTEGER DEFAULT 0, output_tokens_used INTEGER DEFAULT 0, total_tokens_used INTEGER DEFAULT 0, cost_used REAL DEFAULT 0, input_tokens_reserved INTEGER DEFAULT 0, output_tokens_reserved INTEGER DEFAULT 0, total_tokens_reserved INTEGER DEFAULT 0, cost_reserved REAL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(definition_id, period_type, period_start));
        CREATE TABLE IF NOT EXISTS budget_reservations(reservation_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, period_id TEXT NOT NULL, trace_id TEXT, invocation_id TEXT, agent_id TEXT NOT NULL, provider TEXT, model TEXT, status TEXT NOT NULL, estimated_input_tokens INTEGER DEFAULT 0, estimated_output_tokens INTEGER DEFAULT 0, estimated_total_tokens INTEGER DEFAULT 0, estimated_cost REAL DEFAULT 0, actual_input_tokens INTEGER, actual_output_tokens INTEGER, actual_total_tokens INTEGER, actual_cost REAL, usage_source TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, reconciled_at TEXT, metadata_json TEXT);
        CREATE TABLE IF NOT EXISTS budget_events(event_id TEXT PRIMARY KEY, definition_id TEXT, period_id TEXT, reservation_id TEXT, trace_id TEXT, invocation_id TEXT, agent_id TEXT NOT NULL, event_type TEXT NOT NULL, severity TEXT, threshold_pct REAL, message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, metadata_json TEXT, dedupe_key TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS tool_authorization_events(id INTEGER PRIMARY KEY, timestamp TEXT, trace_id TEXT, agent_id TEXT, tool_id TEXT, action TEXT, data_scope TEXT, decision TEXT, reason TEXT, matched_policy TEXT, risk_level TEXT, required_approval INTEGER, approval_satisfied INTEGER, lifecycle_status TEXT, guardrails_evaluated TEXT, violations TEXT, runtime_enforced INTEGER, authorization_status TEXT, source TEXT, payload_summary TEXT);
        CREATE TABLE IF NOT EXISTS agent_invocations(invocation_id TEXT PRIMARY KEY, trace_id TEXT, agent_id TEXT, principal_id TEXT, action TEXT, lifecycle_status TEXT, decision TEXT, started_at TEXT, completed_at TEXT, duration_ms INTEGER, error_code TEXT, request_json TEXT, result_json TEXT);
        CREATE TABLE IF NOT EXISTS runtime_phase_events(id INTEGER PRIMARY KEY, invocation_id TEXT, trace_id TEXT, agent_id TEXT, phase TEXT, status TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, payload_json TEXT);
        CREATE TABLE IF NOT EXISTS agent_principals(principal_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL UNIQUE, principal_type TEXT NOT NULL, display_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', credential_reference TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS roles(role_id TEXT PRIMARY KEY, role_name TEXT NOT NULL UNIQUE, description TEXT, system_role INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS permissions(permission_id TEXT PRIMARY KEY, resource_type TEXT NOT NULL, action TEXT NOT NULL, description TEXT);
        CREATE TABLE IF NOT EXISTS role_permissions(role_id TEXT NOT NULL, permission_id TEXT NOT NULL, PRIMARY KEY(role_id, permission_id));
        CREATE TABLE IF NOT EXISTS principal_roles(principal_id TEXT NOT NULL, role_id TEXT NOT NULL, scope_type TEXT NOT NULL DEFAULT 'global', scope_value TEXT NOT NULL DEFAULT '*', valid_from TEXT, valid_until TEXT, granted_by TEXT, granted_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(principal_id, role_id, scope_type, scope_value));
        CREATE TABLE IF NOT EXISTS authorization_decisions(decision_id TEXT PRIMARY KEY, invocation_id TEXT, principal_id TEXT, resource_type TEXT, resource_id TEXT, requested_action TEXT, resolved_roles TEXT, resolved_permissions TEXT, decision TEXT, reason_code TEXT, policy_version TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS mcp_servers(server_id TEXT PRIMARY KEY, name TEXT NOT NULL, transport TEXT NOT NULL, endpoint TEXT, command_reference TEXT, environment_reference TEXT, status TEXT NOT NULL, owner TEXT, risk_tier TEXT, auth_type TEXT, credential_reference TEXT, connect_timeout_seconds INTEGER DEFAULT 10, call_timeout_seconds INTEGER DEFAULT 30, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS mcp_tools(server_id TEXT NOT NULL, tool_name TEXT NOT NULL, description TEXT, input_schema TEXT NOT NULL, output_schema TEXT, risk_level TEXT, requires_approval INTEGER DEFAULT 0, discovered_at TEXT DEFAULT CURRENT_TIMESTAMP, schema_hash TEXT NOT NULL, enabled INTEGER DEFAULT 1, review_required INTEGER DEFAULT 0, previous_schema_hash TEXT, PRIMARY KEY(server_id, tool_name));
        CREATE TABLE IF NOT EXISTS mcp_invocations(invocation_id TEXT PRIMARY KEY, parent_agent_invocation_id TEXT, principal_id TEXT, server_id TEXT, tool_name TEXT, arguments_hash TEXT, decision TEXT, started_at TEXT, completed_at TEXT, duration_ms INTEGER, result_status TEXT, error_code TEXT);
        CREATE TABLE IF NOT EXISTS a2a_tasks(task_id TEXT PRIMARY KEY, context_id TEXT, agent_id TEXT NOT NULL, state TEXT NOT NULL, trace_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, task_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_usage_events_created_at ON usage_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_usage_events_agent_id ON usage_events(agent_id);
        CREATE INDEX IF NOT EXISTS idx_usage_events_model ON usage_events(model);
        CREATE INDEX IF NOT EXISTS idx_budget_usage_periods_agent ON budget_usage_periods(agent_id, period_type, period_start);
        CREATE INDEX IF NOT EXISTS idx_budget_reservations_trace ON budget_reservations(trace_id);
        CREATE INDEX IF NOT EXISTS idx_budget_events_agent ON budget_events(agent_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_invocations_trace_id ON agent_invocations(trace_id);
        CREATE INDEX IF NOT EXISTS idx_runtime_phase_events_invocation_id ON runtime_phase_events(invocation_id);
        CREATE INDEX IF NOT EXISTS idx_agent_principals_agent_id ON agent_principals(agent_id);
        CREATE INDEX IF NOT EXISTS idx_principal_roles_principal ON principal_roles(principal_id);
        CREATE INDEX IF NOT EXISTS idx_authorization_decisions_principal ON authorization_decisions(principal_id);
        CREATE INDEX IF NOT EXISTS idx_authorization_decisions_invocation ON authorization_decisions(invocation_id);
        CREATE INDEX IF NOT EXISTS idx_authorization_decisions_timestamp ON authorization_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_mcp_tools_server_id ON mcp_tools(server_id);
        CREATE INDEX IF NOT EXISTS idx_mcp_invocations_started_at ON mcp_invocations(started_at);
        CREATE INDEX IF NOT EXISTS idx_mcp_invocations_parent ON mcp_invocations(parent_agent_invocation_id);
        CREATE INDEX IF NOT EXISTS idx_a2a_tasks_agent_state ON a2a_tasks(agent_id, state);
        CREATE INDEX IF NOT EXISTS idx_a2a_tasks_context ON a2a_tasks(context_id);
        """)
        self._migrate_rag_evaluations()
        self._ensure_kill_switch_columns()
        self._ensure_tool_authorization_events_columns()
        with self.conn:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_evaluations_trace_id ON rag_evaluations(trace_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_evaluations_agent_id ON rag_evaluations(agent_id)")
        self._ensure_mcp_columns()
        self._ensure_budget_tables()
    def execute(self, sql, params=()):
        with self.lock, self.conn: return self.conn.execute(sql, params)
    def query(self, sql, params=()):
        with self.lock: return [dict(row) for row in self.conn.execute(sql, params).fetchall()]
    def transaction(self, fn):
        with self.lock, self.conn:
            return fn(self.conn)
    def add_event(self, event_type, trace_id, agent_id, payload): self.execute("INSERT INTO observability_events(trace_id,agent_id,event_type,payload_json) VALUES(?,?,?,?)", (trace_id, agent_id, event_type, json.dumps(payload, default=str)))
    def save_a2a_task(self, task):
        self.execute(
            "INSERT OR REPLACE INTO a2a_tasks(task_id,context_id,agent_id,state,trace_id,updated_at,task_json) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,?)",
            (task["id"], task.get("context_id"), task["agent_id"], task["status"]["state"], task.get("metadata", {}).get("trace_id"), json.dumps(task, default=str)),
        )
    def get_a2a_task(self, task_id):
        rows = self.query("SELECT * FROM a2a_tasks WHERE task_id=?", (task_id,))
        return rows[0] if rows else None
    def list_a2a_tasks(self, limit=100, agent_id=None, state=None):
        clauses, params = [], []
        if agent_id: clauses.append("agent_id=?"); params.append(agent_id)
        if state: clauses.append("state=?"); params.append(state)
        sql = "SELECT * FROM a2a_tasks" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC LIMIT ?"
        return self.query(sql, (*params, limit))
    def add_runtime_phase_event(self, invocation_id, trace_id, agent_id, phase, status, payload=None):
        payload = payload or {}
        self.execute("INSERT INTO runtime_phase_events(invocation_id,trace_id,agent_id,phase,status,payload_json) VALUES(?,?,?,?,?,?)", (invocation_id, trace_id, agent_id, phase, status, json.dumps(payload, default=str)))
        self.add_event("RUNTIME_PHASE_" + phase.upper(), trace_id, agent_id, {"invocation_id": invocation_id, "phase": phase, "status": status, **payload})
    def start_invocation(self, invocation_id, trace_id, agent_id, principal_id, action, lifecycle_status, started_at, request):
        self.execute("INSERT OR REPLACE INTO agent_invocations(invocation_id,trace_id,agent_id,principal_id,action,lifecycle_status,decision,started_at,request_json) VALUES(?,?,?,?,?,?,?,?,?)", (invocation_id, trace_id, agent_id, principal_id, action, lifecycle_status, "running", started_at, json.dumps(request, default=str)))
    def finish_invocation(self, invocation_id, decision, completed_at, duration_ms, error_code=None, result=None):
        self.execute("UPDATE agent_invocations SET decision=?,completed_at=?,duration_ms=?,error_code=?,result_json=? WHERE invocation_id=?", (decision, completed_at, duration_ms, error_code, json.dumps(result, default=str) if result is not None else None, invocation_id))
    def list_events(self, trace_id=None, limit=100): return self.query("SELECT * FROM observability_events WHERE trace_id=? ORDER BY id DESC LIMIT ?", (trace_id, limit)) if trace_id else self.query("SELECT * FROM observability_events ORDER BY id DESC LIMIT ?", (limit,))
    def start_run(self, trace_id, agent_id, payload, started_at): self.execute("INSERT INTO agent_runs(trace_id,agent_id,status,started_at,input_json) VALUES(?,?,?,?,?)", (trace_id, agent_id, "running", started_at, json.dumps(payload, default=str)))
    def finish_run(self, trace_id, status, completed_at, latency_ms, output=None, error=None, confidence=None): self.execute("UPDATE agent_runs SET status=?,completed_at=?,latency_ms=?,output_json=?,error=?,confidence=? WHERE trace_id=?", (status, completed_at, latency_ms, json.dumps(output, default=str) if output is not None else None, error, confidence, trace_id))
    def list_runs(self, trace_id=None, limit=100):
        if trace_id:
            rows = self.query("SELECT * FROM agent_runs WHERE trace_id=?", (trace_id,)); return rows[0] if rows else None
        return self.query("SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?", (limit,))
    def _migrate_rag_evaluations(self):
        """Replace the early demo schema that persisted raw queries with a redacted schema."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(rag_evaluations)")}
        if not columns or "query" not in columns:
            return
        with self.lock, self.conn:
            legacy_rows = self.conn.execute("SELECT * FROM rag_evaluations").fetchall()
            self.conn.execute("ALTER TABLE rag_evaluations RENAME TO rag_evaluations_legacy")
            self.conn.execute("CREATE TABLE rag_evaluations(evaluation_id TEXT PRIMARY KEY, trace_id TEXT, agent_id TEXT, query_hash TEXT, groundedness_score REAL, semantic_similarity_score REAL, llm_judge_score REAL, answer_relevance_score REAL, citation_coverage REAL, retrieved_chunk_count INTEGER, cited_chunk_count INTEGER, evaluator_method TEXT, evaluator_prompt_id TEXT, evaluator_prompt_version TEXT, reason TEXT, metadata_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_evaluations_trace_id ON rag_evaluations(trace_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_evaluations_agent_id ON rag_evaluations(agent_id)")
            for row in legacy_rows:
                row = dict(row)
                metadata = json.loads(row.get("evaluation_json") or "{}")
                self.conn.execute("INSERT INTO rag_evaluations(evaluation_id,trace_id,agent_id,query_hash,groundedness_score,semantic_similarity_score,llm_judge_score,answer_relevance_score,citation_coverage,retrieved_chunk_count,cited_chunk_count,evaluator_method,evaluator_prompt_id,evaluator_prompt_version,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), row.get("trace_id"), row.get("agent_id"), hashlib.sha256((row.get("query") or "").encode("utf-8")).hexdigest(), row.get("groundedness"), row.get("semantic_similarity"), row.get("llm_judge"), row.get("answer_relevance"), row.get("citation_coverage"), metadata.get("retrieved_chunk_count"), metadata.get("cited_chunk_count"), row.get("method"), metadata.get("evaluator_prompt_id"), metadata.get("evaluator_prompt_version"), row.get("reason"), json.dumps(metadata, default=str), row.get("created_at")))
            self.conn.execute("DROP TABLE rag_evaluations_legacy")
    def _ensure_kill_switch_columns(self):
        """Keep evidence fields available for databases created by earlier demos."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(kill_switch_events)")}
        with self.lock, self.conn:
            for name, definition in {
                "trace_id": "TEXT", "trigger": "TEXT", "severity": "TEXT", "approved_by": "TEXT", "override_type": "TEXT", "evidence_json": "TEXT",
            }.items():
                if name not in columns:
                    self.conn.execute(f"ALTER TABLE kill_switch_events ADD COLUMN {name} {definition}")
                    
    def _ensure_tool_authorization_events_columns(self):
        """Keep evidence fields available for databases created by earlier demos."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(tool_authorization_events)")}
        if not columns:
            return
        with self.lock, self.conn:
            for name, definition in {
                "llm_judge_status": "TEXT", "llm_judge_model": "TEXT", "llm_judge_score": "REAL", 
                "llm_judge_decision": "TEXT", "llm_judge_reasons": "TEXT", "llm_judge_prompt_version": "TEXT", 
                "llm_judge_latency_ms": "INTEGER", "llm_judge_detected_risks": "TEXT",
            }.items():
                if name not in columns:
                    self.conn.execute(f"ALTER TABLE tool_authorization_events ADD COLUMN {name} {definition}")
    def add_rag_evaluation(self, trace_id, agent_id, query, evaluation):
        query_hash = hashlib.sha256((query or "").encode("utf-8")).hexdigest()
        self.execute("INSERT INTO rag_evaluations(evaluation_id,trace_id,agent_id,query_hash,groundedness_score,semantic_similarity_score,llm_judge_score,answer_relevance_score,citation_coverage,retrieved_chunk_count,cited_chunk_count,evaluator_method,evaluator_prompt_id,evaluator_prompt_version,reason,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), trace_id, agent_id, query_hash, evaluation.get("groundedness_score"), evaluation.get("semantic_similarity_score"), evaluation.get("llm_judge_score"), evaluation.get("answer_relevance_score"), evaluation.get("citation_coverage"), evaluation.get("retrieved_chunk_count"), evaluation.get("cited_chunk_count"), evaluation.get("evaluator_method"), evaluation.get("evaluator_prompt_id"), evaluation.get("evaluator_prompt_version"), evaluation.get("reason"), json.dumps(evaluation, default=str)))
    def list_rag_evaluations(self, trace_id=None, limit=100, agent_id=None):
        clauses, params = [], []
        if trace_id: clauses.append("trace_id=?"); params.append(trace_id)
        if agent_id: clauses.append("agent_id=?"); params.append(agent_id)
        sql = "SELECT * FROM rag_evaluations" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.query(sql, params)
        for row in rows:
            row["rag_evaluation"] = json.loads(row.pop("metadata_json"))
        return rows

    def list_tool_authorization_events(self, limit=100, agent_id=None, decision=None, source=None):
        clauses, params = [], []
        if agent_id: clauses.append("agent_id=?"); params.append(agent_id)
        if decision: clauses.append("decision=?"); params.append(decision)
        if source: clauses.append("source=?"); params.append(source)
        sql = "SELECT * FROM tool_authorization_events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.query(sql, params)
        for row in rows:
            row["required_approval"] = bool(row.get("required_approval"))
            row["approval_satisfied"] = bool(row.get("approval_satisfied"))
            row["runtime_enforced"] = bool(row.get("runtime_enforced"))
            for key in ("guardrails_evaluated", "violations", "llm_judge_reasons", "llm_judge_detected_risks"):
                value = row.get(key)
                if isinstance(value, str):
                    try:
                        row[key] = json.loads(value)
                    except json.JSONDecodeError:
                        row[key] = [] if key != "guardrails_evaluated" else value
            row["llm_judge"] = {
                "status": row.get("llm_judge_status") or "not_run",
                "model": row.get("llm_judge_model"),
                "risk_score": row.get("llm_judge_score"),
                "recommended_decision": row.get("llm_judge_decision"),
                "detected_risks": row.get("llm_judge_detected_risks") or [],
                "reasons": row.get("llm_judge_reasons") or [],
                "prompt_version": row.get("llm_judge_prompt_version"),
                "latency_ms": row.get("llm_judge_latency_ms"),
            }
        return rows

    def list_principals(self):
        return self.query("SELECT * FROM agent_principals ORDER BY display_name")

    def get_principal(self, principal_id):
        rows = self.query("SELECT * FROM agent_principals WHERE principal_id=?", (principal_id,))
        return rows[0] if rows else None

    def list_roles(self):
        rows = self.query("SELECT * FROM roles ORDER BY role_name")
        for row in rows:
            row["system_role"] = bool(row.get("system_role"))
        return rows

    def list_authorization_decisions(self, limit=100, principal_id=None, decision=None):
        clauses, params = [], []
        if principal_id:
            clauses.append("principal_id=?")
            params.append(principal_id)
        if decision:
            clauses.append("decision=?")
            params.append(decision)
        sql = "SELECT * FROM authorization_decisions" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.query(sql, params)
        for row in rows:
            for key in ("resolved_roles", "resolved_permissions"):
                try:
                    row[key] = json.loads(row.get(key) or "[]")
                except json.JSONDecodeError:
                    row[key] = []
        return rows

    def _ensure_mcp_columns(self):
        """Keep MCP governance tables compatible with databases created before this feature."""
        if not {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_servers'")}:
            return
        with self.lock, self.conn:
            server_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(mcp_servers)")}
            for name, definition in {
                "endpoint": "TEXT",
                "command_reference": "TEXT",
                "environment_reference": "TEXT",
                "credential_reference": "TEXT",
                "connect_timeout_seconds": "INTEGER DEFAULT 10",
                "call_timeout_seconds": "INTEGER DEFAULT 30",
            }.items():
                if name not in server_columns:
                    self.conn.execute(f"ALTER TABLE mcp_servers ADD COLUMN {name} {definition}")
            tool_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(mcp_tools)")}
            for name, definition in {"review_required": "INTEGER DEFAULT 0", "previous_schema_hash": "TEXT"}.items():
                if name not in tool_columns:
                    self.conn.execute(f"ALTER TABLE mcp_tools ADD COLUMN {name} {definition}")

    def _ensure_budget_tables(self):
        with self.conn:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS budget_definitions(definition_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, policy_json TEXT NOT NULL, provider TEXT, model TEXT, currency TEXT DEFAULT 'USD', active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS budget_usage_periods(period_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, agent_id TEXT NOT NULL, period_type TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, input_tokens_used INTEGER DEFAULT 0, output_tokens_used INTEGER DEFAULT 0, total_tokens_used INTEGER DEFAULT 0, cost_used REAL DEFAULT 0, input_tokens_reserved INTEGER DEFAULT 0, output_tokens_reserved INTEGER DEFAULT 0, total_tokens_reserved INTEGER DEFAULT 0, cost_reserved REAL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(definition_id, period_type, period_start));
            CREATE TABLE IF NOT EXISTS budget_reservations(reservation_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, period_id TEXT NOT NULL, trace_id TEXT, invocation_id TEXT, agent_id TEXT NOT NULL, provider TEXT, model TEXT, status TEXT NOT NULL, estimated_input_tokens INTEGER DEFAULT 0, estimated_output_tokens INTEGER DEFAULT 0, estimated_total_tokens INTEGER DEFAULT 0, estimated_cost REAL DEFAULT 0, actual_input_tokens INTEGER, actual_output_tokens INTEGER, actual_total_tokens INTEGER, actual_cost REAL, usage_source TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, reconciled_at TEXT, metadata_json TEXT);
            CREATE TABLE IF NOT EXISTS budget_events(event_id TEXT PRIMARY KEY, definition_id TEXT, period_id TEXT, reservation_id TEXT, trace_id TEXT, invocation_id TEXT, agent_id TEXT NOT NULL, event_type TEXT NOT NULL, severity TEXT, threshold_pct REAL, message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, metadata_json TEXT, dedupe_key TEXT UNIQUE);
            """)

    def upsert_mcp_server(self, server):
        self.execute(
            """
            INSERT INTO mcp_servers(server_id,name,transport,endpoint,command_reference,environment_reference,status,owner,risk_tier,auth_type,credential_reference,connect_timeout_seconds,call_timeout_seconds)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(server_id) DO UPDATE SET
              name=excluded.name, transport=excluded.transport, endpoint=excluded.endpoint,
              command_reference=excluded.command_reference, environment_reference=excluded.environment_reference,
              status=excluded.status, owner=excluded.owner, risk_tier=excluded.risk_tier,
              auth_type=excluded.auth_type, credential_reference=excluded.credential_reference,
              connect_timeout_seconds=excluded.connect_timeout_seconds, call_timeout_seconds=excluded.call_timeout_seconds,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                server["server_id"], server["name"], server["transport"], server.get("endpoint"),
                json.dumps(server.get("command_reference"), default=str) if isinstance(server.get("command_reference"), (dict, list)) else server.get("command_reference"),
                server.get("environment_reference"), server.get("status", "registered"), server.get("owner"),
                server.get("risk_tier", "medium"), server.get("auth_type", "none"), server.get("credential_reference"),
                int(server.get("connect_timeout_seconds", 10)), int(server.get("call_timeout_seconds", 30)),
            ),
        )

    def list_mcp_servers(self):
        rows = self.query("SELECT * FROM mcp_servers ORDER BY name")
        for row in rows:
            if isinstance(row.get("command_reference"), str):
                try:
                    row["command_reference"] = json.loads(row["command_reference"])
                except json.JSONDecodeError:
                    pass
        return rows

    def get_mcp_server(self, server_id):
        rows = self.query("SELECT * FROM mcp_servers WHERE server_id=?", (server_id,))
        if not rows:
            return None
        row = rows[0]
        if isinstance(row.get("command_reference"), str):
            try:
                row["command_reference"] = json.loads(row["command_reference"])
            except json.JSONDecodeError:
                pass
        return row

    def upsert_mcp_tool(self, tool):
        existing = self.query("SELECT schema_hash,risk_level FROM mcp_tools WHERE server_id=? AND tool_name=?", (tool["server_id"], tool["tool_name"]))
        previous_hash = existing[0]["schema_hash"] if existing else None
        review_required = bool(previous_hash and previous_hash != tool["schema_hash"] and tool.get("risk_level") in {"high", "critical"})
        self.execute(
            """
            INSERT INTO mcp_tools(server_id,tool_name,description,input_schema,output_schema,risk_level,requires_approval,schema_hash,enabled,review_required,previous_schema_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(server_id,tool_name) DO UPDATE SET
              description=excluded.description, input_schema=excluded.input_schema, output_schema=excluded.output_schema,
              risk_level=excluded.risk_level, requires_approval=excluded.requires_approval,
              schema_hash=excluded.schema_hash, enabled=excluded.enabled,
              review_required=excluded.review_required, previous_schema_hash=excluded.previous_schema_hash,
              discovered_at=CURRENT_TIMESTAMP
            """,
            (
                tool["server_id"], tool["tool_name"], tool.get("description", ""),
                json.dumps(tool.get("input_schema") or {}, sort_keys=True),
                json.dumps(tool.get("output_schema"), sort_keys=True) if tool.get("output_schema") else None,
                tool.get("risk_level", "medium"), 1 if tool.get("requires_approval") else 0,
                tool["schema_hash"], 1 if tool.get("enabled", True) else 0,
                1 if review_required else 0, previous_hash,
            ),
        )
        return {"review_required": review_required, "previous_schema_hash": previous_hash}

    def list_mcp_tools(self, server_id=None):
        rows = self.query("SELECT * FROM mcp_tools WHERE server_id=? ORDER BY tool_name", (server_id,)) if server_id else self.query("SELECT * FROM mcp_tools ORDER BY server_id,tool_name")
        for row in rows:
            for key in ("input_schema", "output_schema"):
                if isinstance(row.get(key), str):
                    try:
                        row[key] = json.loads(row[key])
                    except json.JSONDecodeError:
                        row[key] = {}
            row["requires_approval"] = bool(row.get("requires_approval"))
            row["enabled"] = bool(row.get("enabled"))
            row["review_required"] = bool(row.get("review_required"))
        return rows

    def get_mcp_tool(self, server_id, tool_name):
        rows = self.list_mcp_tools(server_id)
        return next((row for row in rows if row["tool_name"] == tool_name), None)

    def start_mcp_invocation(self, invocation_id, parent_agent_invocation_id, principal_id, server_id, tool_name, arguments_hash, decision, started_at):
        self.execute(
            "INSERT INTO mcp_invocations(invocation_id,parent_agent_invocation_id,principal_id,server_id,tool_name,arguments_hash,decision,started_at,result_status) VALUES(?,?,?,?,?,?,?,?,?)",
            (invocation_id, parent_agent_invocation_id, principal_id, server_id, tool_name, arguments_hash, decision, started_at, "running"),
        )

    def finish_mcp_invocation(self, invocation_id, completed_at, duration_ms, result_status, error_code=None, decision=None):
        self.execute(
            "UPDATE mcp_invocations SET completed_at=?,duration_ms=?,result_status=?,error_code=?,decision=COALESCE(?,decision) WHERE invocation_id=?",
            (completed_at, duration_ms, result_status, error_code, decision, invocation_id),
        )

    def list_mcp_invocations(self, limit=100, server_id=None, tool_name=None, decision=None):
        clauses, params = [], []
        if server_id:
            clauses.append("server_id=?"); params.append(server_id)
        if tool_name:
            clauses.append("tool_name=?"); params.append(tool_name)
        if decision:
            clauses.append("decision=?"); params.append(decision)
        sql = "SELECT * FROM mcp_invocations" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)
