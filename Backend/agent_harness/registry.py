"""Generic manifest-driven registry with compatibility metrics operations."""
from collections import deque
import json
from threading import RLock

from .config_loader import load_agent_contracts
from .contract_validator import ContractValidator
from .contracts import AgentStatus
from .exceptions import AgentNotFoundError
from .plugin_loader import build_adapter


class AgentRegistry:
    def __init__(self, services=None):
        self.services = services
        self._contracts, self._adapters, self._metrics, self._legacy = {}, {}, {}, {}
        self._events, self._lock = [], RLock()

    def load(self, config_dir):
        validator = ContractValidator.from_config_dir(config_dir)
        contracts = load_agent_contracts(config_dir)
        if not contracts: raise RuntimeError(f"No agent manifests found in {config_dir}")
        for contract in contracts:
            validator.validate_or_raise(contract)
            with self._lock:
                if contract.agent_id in self._contracts: raise ValueError(f"Duplicate agent_id: {contract.agent_id}")
                # Lifecycle state is operational data, not manifest configuration.
                # Restore a persisted quarantine/review state on restart instead of
                # silently returning the agent to its manifest default.
                persisted = []
                if self.services and getattr(self.services, "store", None):
                    persisted = self.services.store.query("SELECT status FROM agents WHERE agent_id=?", (contract.agent_id,))
                if persisted and persisted[0].get("status"):
                    contract.status = AgentStatus(persisted[0]["status"])
                self._contracts[contract.agent_id] = contract
                self._metrics[contract.agent_id] = {"runs": 0, "failures": 0, "policy_blocks": 0, "recent": deque(maxlen=5)}
                if self.services and getattr(self.services, "store", None):
                    self.services.store.execute("INSERT OR IGNORE INTO agents(agent_id,name,status,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)", (contract.agent_id, contract.name, contract.status.value))
                    self.services.store.execute("UPDATE agents SET name=? WHERE agent_id=?", (contract.name, contract.agent_id))
                    self.services.store.execute("INSERT OR REPLACE INTO agent_contracts(agent_id,contract_json,source_file,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)", (contract.agent_id, json.dumps(contract.effective_contract()), contract.metadata.get("source_file", "")))
        return len(contracts)

    def list_agents(self): return [{**contract.to_dict(), "metrics": self.metrics(contract.agent_id)} for contract in self._contracts.values()]
    def exists(self, agent_id): return agent_id in self._contracts
    def get_contract(self, agent_id):
        if agent_id not in self._contracts: raise AgentNotFoundError(f"Agent '{agent_id}' is not registered")
        return self._contracts[agent_id]
    def get_adapter(self, agent_id):
        with self._lock:
            if agent_id not in self._adapters: self._adapters[agent_id] = build_adapter(self.get_contract(agent_id), self.services)
            return self._adapters[agent_id]
    def set_status(self, agent_id, status):
        status = AgentStatus(status)
        self.get_contract(agent_id).status = status
        if self.services and getattr(self.services, "store", None): self.services.store.execute("UPDATE agents SET status=?,updated_at=CURRENT_TIMESTAMP WHERE agent_id=?", (status.value, agent_id))
    def record_run(self, agent_id, success, latency_ms, confidence=None):
        metric = self._metrics[agent_id]; metric["runs"] += 1; metric["failures"] += int(not success); metric["recent"].append({"success": success, "latency_ms": latency_ms, "confidence": confidence})
    def record_block(self, agent_id): self._metrics[agent_id]["policy_blocks"] += 1
    def reset_runtime_health(self, agent_id):
        if agent_id in self._metrics:
            self._metrics[agent_id] = {"runs": 0, "failures": 0, "policy_blocks": 0, "recent": deque(maxlen=5)}
    def metrics(self, agent_id): return {**self._metrics[agent_id], "recent": list(self._metrics[agent_id]["recent"])}

    def registry_contract_view(self, agent_id):
        contract = self.get_contract(agent_id)
        latest_evidence = {}
        if self.services and getattr(self.services, "store", None):
            for key, sql in {
                "kill_switch": "SELECT * FROM kill_switch_events WHERE agent_id=? ORDER BY id DESC LIMIT 1",
                "rag_evaluation": "SELECT * FROM rag_evaluations WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
                "guardrail_event": "SELECT * FROM guardrail_events WHERE agent_id=? ORDER BY id DESC LIMIT 1",
                "policy_decision": "SELECT * FROM policy_decisions WHERE agent_id=? ORDER BY id DESC LIMIT 1",
                "usage_event": "SELECT * FROM usage_events WHERE agent_id=? ORDER BY created_at DESC LIMIT 1",
            }.items():
                rows = self.services.store.query(sql, (agent_id,))
                latest_evidence[key] = rows[0] if rows else None
        effective = contract.effective_contract()
        return {
            "agent_id": agent_id,
            "effective_resolved_contract": effective,
            "contract": effective,
            "original_contract_version": contract.original_contract_version,
            "validation_result": contract.validation_result,
            "unresolved_references": contract.unresolved_references,
            "active_runtime": {
                "runtime_type": contract.runtime_type,
                "execution_mode": contract.execution_mode,
                "adapter_type": contract.adapter_type,
                "status": contract.status.value,
            },
            "model_deployment": effective["model_policy"].get("deployment"),
            "budget_policy": effective["budget_policy"],
            "permissions": effective["permissions"],
            "observability_requirements": effective["observability"],
            "latest_evidence": latest_evidence,
            "source_file": contract.metadata.get("source_file") or None,
            "_demo": bool(contract.metadata.get("demo", False)),
        }

    # Compatibility surface for existing application routes; definitions are injected by the app.
    def register_runtime_agent(self, name, definition): self._legacy[name] = {"calls": 0, "errors": 0, "total_latency_ms": 0, "last_called": None, "last_error": None, **definition}
    def is_enabled(self, name): return self._legacy.get(name, {}).get("enabled", True)
    def toggle(self, name, enabled, triggered_by="dashboard"):
        if name not in self._legacy: raise KeyError(name)
        if not self._legacy[name].get("killable", True): raise ValueError(f"Agent '{name}' cannot be toggled")
        self._legacy[name]["enabled"] = enabled
        event = {"agent": name, "action": "enabled" if enabled else "disabled", "triggered_by": triggered_by}
        self._events.append(event)
        return self._legacy_dict(name)
    def record_call(self, name, latency_ms, error=False):
        from datetime import datetime, timezone
        if name not in self._legacy: return
        item = self._legacy[name]; item["calls"] += 1; item["errors"] += int(error); item["total_latency_ms"] += latency_ms; item["last_called"] = datetime.now(timezone.utc).isoformat()
    def get_all(self): return [self._legacy_dict(name) for name in self._legacy]
    def get_agent(self, name): return self._legacy_dict(name) if name in self._legacy else None
    def get_kill_switch_log(self, limit=50): return list(reversed(self._events[-limit:]))
    def _legacy_dict(self, name):
        item = self._legacy[name]; calls = item["calls"]
        return {"tool_name": name, **item, "avg_latency_ms": round(item["total_latency_ms"] / calls) if calls else 0}


agent_registry = AgentRegistry()
