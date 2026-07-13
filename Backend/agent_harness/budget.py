"""Prospective model-token and cost budget enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import calendar
import json
from uuid import uuid4


class BudgetExceeded(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _period_bounds(period, at=None):
    at = at or _now()
    if period == "month":
        start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days = calendar.monthrange(start.year, start.month)[1]
        return start, start + timedelta(days=days)
    if period == "day":
        start = at.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    return at, at + timedelta(microseconds=1)


def _num(value, default=0):
    if value is None or value == "":
        return default
    return float(value)


class BudgetManager:
    def __init__(self, store, usage_meter):
        self.store = store
        self.usage_meter = usage_meter

    def estimate_input_tokens(self, provider, model, messages=None, prompt=None):
        text = prompt if prompt is not None else "\n".join(str(m.get("content", "")) for m in messages or [])
        try:
            import tiktoken
            encoding = tiktoken.encoding_for_model(str(model))
            return len(encoding.encode(text or "")), "tiktoken"
        except Exception:
            return self.usage_meter.estimate_tokens(text), "heuristic_token_estimate"

    def projected_usage(self, policy, provider, model, messages=None, prompt=None, max_output_tokens=None):
        input_tokens, method = self.estimate_input_tokens(provider, model, messages, prompt)
        output_tokens = int(max_output_tokens or policy.get("max_output_tokens") or 0)
        total_tokens = input_tokens + output_tokens
        _, _, cost, pricing_source = self.usage_meter.estimate_cost(provider, model, input_tokens, output_tokens)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost": cost or 0,
            "tokenizer": method,
            "pricing_source": pricing_source,
        }

    def reserve(self, *, agent_id, policy, provider, model, trace_id=None, invocation_id=None, projected=None, metadata=None):
        policy = policy or {}
        if not policy:
            return None
        mode = str(policy.get("enforcement_mode") or "monitor")
        period = str(policy.get("period") or "invocation")
        projected = projected or {}
        definition_id = f"{agent_id}:{period}"
        start, end = _period_bounds(period)
        period_start, period_end = _iso(start), _iso(end)
        reservation_id = str(uuid4())

        def tx(conn):
            conn.execute(
                "INSERT OR REPLACE INTO budget_definitions(definition_id,agent_id,policy_json,provider,model,currency,active,updated_at) VALUES(?,?,?,?,?,'USD',1,CURRENT_TIMESTAMP)",
                (definition_id, agent_id, json.dumps(policy, default=str), provider, model),
            )
            period_id = f"{definition_id}:{period_start}"
            conn.execute(
                "INSERT OR IGNORE INTO budget_usage_periods(period_id,definition_id,agent_id,period_type,period_start,period_end) VALUES(?,?,?,?,?,?)",
                (period_id, definition_id, agent_id, period, period_start, period_end),
            )
            row = dict(conn.execute("SELECT * FROM budget_usage_periods WHERE period_id=?", (period_id,)).fetchone())
            requested = {
                "input": int(projected.get("input_tokens") or 0),
                "output": int(projected.get("output_tokens") or 0),
                "total": int(projected.get("total_tokens") or 0),
                "cost": float(projected.get("cost") or 0),
            }
            breaches = []
            checks = [
                ("max_input_tokens", row["input_tokens_used"] + row["input_tokens_reserved"], requested["input"], "input tokens"),
                ("max_output_tokens", row["output_tokens_used"] + row["output_tokens_reserved"], requested["output"], "output tokens"),
                ("max_total_tokens", row["total_tokens_used"] + row["total_tokens_reserved"], requested["total"], "total tokens"),
                ("max_cost", row["cost_used"] + row["cost_reserved"], requested["cost"], "cost"),
            ]
            for key, committed, add, label in checks:
                if policy.get(key) is not None and committed + add > _num(policy.get(key)):
                    breaches.append({"field": key, "label": label, "limit": _num(policy.get(key)), "projected": committed + add})
            if breaches:
                self._event(conn, definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, "budget_block" if mode in {"hard_block", "enforce"} else "budget_overrun_monitor", "block" if mode in {"hard_block", "enforce"} else "warning", None, "Projected usage exceeds configured budget", {"breaches": breaches, "projected": projected, "policy": policy})
                if mode in {"hard_block", "enforce"}:
                    raise BudgetExceeded("Projected usage exceeds configured budget")
            conn.execute(
                "UPDATE budget_usage_periods SET input_tokens_reserved=input_tokens_reserved+?, output_tokens_reserved=output_tokens_reserved+?, total_tokens_reserved=total_tokens_reserved+?, cost_reserved=cost_reserved+?, updated_at=CURRENT_TIMESTAMP WHERE period_id=?",
                (requested["input"], requested["output"], requested["total"], requested["cost"], period_id),
            )
            conn.execute(
                "INSERT INTO budget_reservations(reservation_id,definition_id,period_id,trace_id,invocation_id,agent_id,provider,model,status,estimated_input_tokens,estimated_output_tokens,estimated_total_tokens,estimated_cost,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (reservation_id, definition_id, period_id, trace_id, invocation_id, agent_id, provider, model, "reserved", requested["input"], requested["output"], requested["total"], requested["cost"], json.dumps(metadata or {}, default=str)),
            )
            self._maybe_threshold_event(conn, definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, policy)
            return {"reservation_id": reservation_id, "definition_id": definition_id, "period_id": period_id, "projected": projected}
        return self.store.transaction(tx)

    def reconcile_reservation(self, reservation_id, usage):
        def tx(conn):
            row = conn.execute("SELECT * FROM budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if not row or row["status"] != "reserved":
                return None
            row = dict(row)
            actual = {
                "input": int(usage.get("prompt_tokens") or 0),
                "output": int(usage.get("completion_tokens") or 0),
                "total": int(usage.get("total_tokens") or 0),
                "cost": float(usage.get("estimated_total_cost") or 0),
            }
            conn.execute(
                """UPDATE budget_usage_periods SET
                   input_tokens_reserved=max(0,input_tokens_reserved-?), output_tokens_reserved=max(0,output_tokens_reserved-?),
                   total_tokens_reserved=max(0,total_tokens_reserved-?), cost_reserved=max(0,cost_reserved-?),
                   input_tokens_used=input_tokens_used+?, output_tokens_used=output_tokens_used+?,
                   total_tokens_used=total_tokens_used+?, cost_used=cost_used+?, updated_at=CURRENT_TIMESTAMP
                   WHERE period_id=?""",
                (row["estimated_input_tokens"], row["estimated_output_tokens"], row["estimated_total_tokens"], row["estimated_cost"], actual["input"], actual["output"], actual["total"], actual["cost"], row["period_id"]),
            )
            conn.execute(
                "UPDATE budget_reservations SET status='reconciled', actual_input_tokens=?, actual_output_tokens=?, actual_total_tokens=?, actual_cost=?, usage_source=?, reconciled_at=CURRENT_TIMESTAMP WHERE reservation_id=?",
                (actual["input"], actual["output"], actual["total"], actual["cost"], usage.get("usage_source"), reservation_id),
            )
            policy = json.loads(conn.execute("SELECT policy_json FROM budget_definitions WHERE definition_id=?", (row["definition_id"],)).fetchone()["policy_json"])
            self._maybe_threshold_event(conn, row["definition_id"], row["period_id"], reservation_id, row["trace_id"], row["invocation_id"], row["agent_id"], policy, actual=True)
            return True
        return self.store.transaction(tx)

    def release_reservation(self, reservation_id, reason="released"):
        def tx(conn):
            row = conn.execute("SELECT * FROM budget_reservations WHERE reservation_id=?", (reservation_id,)).fetchone()
            if not row or row["status"] != "reserved":
                return None
            row = dict(row)
            conn.execute(
                "UPDATE budget_usage_periods SET input_tokens_reserved=max(0,input_tokens_reserved-?), output_tokens_reserved=max(0,output_tokens_reserved-?), total_tokens_reserved=max(0,total_tokens_reserved-?), cost_reserved=max(0,cost_reserved-?), updated_at=CURRENT_TIMESTAMP WHERE period_id=?",
                (row["estimated_input_tokens"], row["estimated_output_tokens"], row["estimated_total_tokens"], row["estimated_cost"], row["period_id"]),
            )
            conn.execute("UPDATE budget_reservations SET status=?, reconciled_at=CURRENT_TIMESTAMP WHERE reservation_id=?", (reason, reservation_id))
            return True
        return self.store.transaction(tx)

    def _event(self, conn, definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, event_type, severity, threshold_pct, message, metadata, dedupe_key=None):
        conn.execute(
            "INSERT OR IGNORE INTO budget_events(event_id,definition_id,period_id,reservation_id,trace_id,invocation_id,agent_id,event_type,severity,threshold_pct,message,metadata_json,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, event_type, severity, threshold_pct, message, json.dumps(metadata or {}, default=str), dedupe_key or f"{definition_id}:{period_id}:{event_type}:{threshold_pct}"),
        )

    def _maybe_threshold_event(self, conn, definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, policy, actual=False):
        threshold = policy.get("warning_threshold_pct")
        if threshold is None:
            return
        threshold = float(threshold)
        row = dict(conn.execute("SELECT * FROM budget_usage_periods WHERE period_id=?", (period_id,)).fetchone())
        max_total = policy.get("max_total_tokens")
        pct = None
        if max_total:
            pct = 100 * (row["total_tokens_used"] + row["total_tokens_reserved"]) / float(max_total)
        elif policy.get("max_cost"):
            pct = 100 * (row["cost_used"] + row["cost_reserved"]) / float(policy["max_cost"])
        if pct is not None and pct >= threshold:
            self._event(conn, definition_id, period_id, reservation_id, trace_id, invocation_id, agent_id, "budget_threshold_crossed", "warning", threshold, "Budget warning threshold crossed", {"usage_pct": pct, "actual": actual, "policy": policy}, f"{definition_id}:{period_id}:threshold:{threshold}")

    def get_budget_status(self):
        definitions = self.store.query("SELECT * FROM budget_definitions WHERE active=1 ORDER BY agent_id")
        for item in definitions:
            item["policy"] = json.loads(item.pop("policy_json") or "{}")
        periods = self.store.query("SELECT * FROM budget_usage_periods ORDER BY period_start DESC")
        events = self.store.query("SELECT * FROM budget_events ORDER BY created_at DESC LIMIT 100")
        for event in events:
            event["metadata"] = json.loads(event.pop("metadata_json") or "{}")
        return {"definitions": definitions, "periods": periods, "events": events}
