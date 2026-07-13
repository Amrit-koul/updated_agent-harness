"""Generic lifecycle state service; source interpretation belongs to the app."""
from .contracts import AgentStatus


MANUAL_SOURCES = {"manual", "manual_admin", "admin_validation"}
ALLOWED_MANUAL_TRANSITIONS = {
    ("review", "active"),
    ("quarantined", "review"),
    ("disabled", "review"),
    ("active", "review"),
    ("active", "disabled"),
    ("active", "quarantined"),
}
REACTIVATION_OVERRIDE_TYPES = {"reactivate_after_review", "break_glass_expiring"}


class KillSwitchService:
    def __init__(self, registry, store): self.registry, self.store = registry, store
    def change_status(self, agent_id, new_status, source, reason, triggered_by="control-plane", *, trace_id=None, severity=None, approved_by=None, override_type=None, evidence=None, change_ticket=None, second_approved_by=None):
        import json
        if not reason or not str(reason).strip():
            raise ValueError("reason is required for lifecycle transitions")
        try:
            new_status = AgentStatus(new_status).value
        except ValueError as exc:
            allowed = ", ".join(status.value for status in AgentStatus)
            raise ValueError(f"invalid target status '{new_status}'. Allowed statuses: {allowed}") from exc

        old = self.registry.get_contract(agent_id).status.value
        manual = source in MANUAL_SOURCES
        if manual:
            missing = [name for name, value in {
                "approved_by": approved_by,
                "override_type": override_type,
                "reason": reason,
                "change_ticket": change_ticket,
            }.items() if not value or not str(value).strip()]
            if new_status == AgentStatus.ACTIVE.value:
                if not second_approved_by or not str(second_approved_by).strip():
                    missing.append("second_approved_by")
                if override_type not in REACTIVATION_OVERRIDE_TYPES:
                    raise ValueError(
                        "reactivation requires override_type "
                        f"{', '.join(sorted(REACTIVATION_OVERRIDE_TYPES))}"
                    )
                if approved_by and second_approved_by and str(approved_by).strip().lower() == str(second_approved_by).strip().lower():
                    raise ValueError("reactivation requires two distinct approvers")
            if missing:
                raise ValueError(f"manual lifecycle transition requires: {', '.join(missing)}")
            if (old, new_status) not in ALLOWED_MANUAL_TRANSITIONS:
                raise ValueError(f"manual lifecycle transition {old} -> {new_status} is not allowed; route through review before reactivation")

        self.registry.set_status(agent_id, new_status)
        if manual and new_status == AgentStatus.ACTIVE.value and hasattr(self.registry, "reset_runtime_health"):
            self.registry.reset_runtime_health(agent_id)
        lifecycle_evidence = {
            **(evidence or {}),
            "change_ticket": change_ticket,
            "second_approved_by": second_approved_by,
            "transition_policy": "bank-manual-lifecycle-v2" if manual else "bank-automatic-lifecycle-v1",
        }
        cursor = self.store.execute("INSERT INTO kill_switch_events(agent_id,old_status,new_status,source,reason,triggered_by,trace_id,trigger,severity,approved_by,override_type,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (agent_id, old, new_status, source, reason, triggered_by, trace_id, source, severity, approved_by, override_type, json.dumps(lifecycle_evidence, default=str)))
        payload = {"event_id": cursor.lastrowid, "agent_id": agent_id, "previous_status": old, "new_status": new_status, "source": source, "reason": reason, "trigger": source, "severity": severity, "trace_id": trace_id, "approved_by": approved_by, "override_type": override_type, "change_ticket": change_ticket, "second_approved_by": second_approved_by, "evidence": lifecycle_evidence}
        self.store.add_event("KILL_SWITCH_EVENT", trace_id or "", agent_id, payload)
        self.store.add_event("LIFECYCLE_STATUS_CHANGED", trace_id or "", agent_id, payload)
        return payload
