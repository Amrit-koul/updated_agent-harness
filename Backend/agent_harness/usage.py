"""Generic, best-effort token, cost, and latency metering for agent runs."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)
_METER: "UsageMeter | None" = None
_CONTEXT = ContextVar("agent_harness_usage_context", default={})
_BUDGET_MANAGER = None


def configure_usage_meter(meter: "UsageMeter") -> None:
    global _METER
    _METER = meter


def get_usage_meter() -> "UsageMeter | None":
    return _METER


def configure_budget_manager(manager) -> None:
    global _BUDGET_MANAGER
    _BUDGET_MANAGER = manager


def get_budget_manager():
    return _BUDGET_MANAGER


def current_usage_context() -> dict:
    return dict(_CONTEXT.get() or {})


@contextmanager
def usage_context(**values):
    token = _CONTEXT.set({**_CONTEXT.get(), **{k: v for k, v in values.items() if v is not None}})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


class UsageMeter:
    """Persists provider-reported usage where possible and labels all estimates."""
    def __init__(self, store, pricing_path: str | Path | None = None):
        self.store = store
        self.pricing_path = Path(pricing_path) if pricing_path else None
        self.pricing = self._load_pricing()

    def _load_pricing(self) -> dict[tuple[str, str], dict]:
        if not self.pricing_path or not self.pricing_path.exists():
            return {}
        try:
            import yaml
            data = yaml.safe_load(self.pricing_path.read_text(encoding="utf-8")) or {}
            rows = data.get("models", data if isinstance(data, list) else [])
            return {(str(row["provider"]).lower(), str(row["model"])): row for row in rows}
        except Exception as exc:
            logger.warning("Usage pricing config could not be loaded: %s", exc)
            return {}

    @staticmethod
    def estimate_tokens(text: str | None) -> int:
        # Deliberately simple, language-agnostic fallback appropriate for demo telemetry.
        return max(0, (len(text or "") + 3) // 4)

    def estimate_cost(self, provider, model, prompt_tokens, completion_tokens):
        pricing = self.pricing.get((str(provider or "").lower(), str(model or "")))
        if not pricing or prompt_tokens is None or completion_tokens is None:
            return None, None, None, None
        input_cost = prompt_tokens * float(pricing.get("input_cost_per_1k_tokens", 0)) / 1000
        output_cost = completion_tokens * float(pricing.get("output_cost_per_1k_tokens", 0)) / 1000
        return input_cost, output_cost, input_cost + output_cost, str(pricing.get("effective_date", "configured"))

    @staticmethod
    def _field(value: Any, name: str):
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

    def record_llm_response(self, response: Any, *, provider: str, model: str, prompt: str, completion: str,
                            latency_ms: int, status="success", retry_count=0, fallback_used=False,
                            fallback_from_model=None, fallback_to_model=None, metadata=None, budget_reservation_id=None) -> dict:
        usage = self._field(response, "usage")
        prompt_tokens = self._field(usage, "prompt_tokens") if usage is not None else None
        completion_tokens = self._field(usage, "completion_tokens") if usage is not None else None
        total_tokens = self._field(usage, "total_tokens") if usage is not None else None
        provider_reported = prompt_tokens is not None or completion_tokens is not None or total_tokens is not None
        if not provider_reported:
            prompt_tokens, completion_tokens = self.estimate_tokens(prompt), self.estimate_tokens(completion)
            total_tokens = prompt_tokens + completion_tokens
        elif total_tokens is None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        return self.record_usage({
            **_CONTEXT.get(), "provider": provider, "model": model, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "total_tokens": total_tokens,
            "usage_source": "provider_reported" if provider_reported else "estimated",
            "estimated_method": "provider_usage" if provider_reported else "heuristic_token_estimate",
            "latency_ms": latency_ms, "retry_count": retry_count, "fallback_used": fallback_used,
            "fallback_from_model": fallback_from_model, "fallback_to_model": fallback_to_model,
            "status": status, "metadata": metadata or {},
            "budget_reservation_id": budget_reservation_id,
        })

    def record_usage(self, event: dict) -> dict:
        event = {**_CONTEXT.get(), **event}
        provider, model = event.get("provider"), event.get("model")
        prompt_tokens, completion_tokens = event.get("prompt_tokens"), event.get("completion_tokens")
        total_tokens = event.get("total_tokens")
        if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        input_cost, output_cost, total_cost, pricing_source = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
        result = {
            "usage_id": event.get("usage_id") or str(uuid4()), "trace_id": event.get("trace_id"),
            "run_id": event.get("run_id"), "agent_id": event.get("agent_id"), "agent_name": event.get("agent_name"),
            "business_function": event.get("business_function"), "provider": provider, "model": model,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens,
            "estimated_input_cost": input_cost, "estimated_output_cost": output_cost, "estimated_total_cost": total_cost,
            "currency": "USD", "pricing_source": pricing_source, "usage_source": event.get("usage_source", "unknown"),
            "estimated_method": event.get("estimated_method", "unavailable"), "latency_ms": event.get("latency_ms"),
            "retry_count": event.get("retry_count", 0), "fallback_used": bool(event.get("fallback_used", False)),
            "fallback_from_model": event.get("fallback_from_model"), "fallback_to_model": event.get("fallback_to_model"),
            "status": event.get("status", "success"), "created_at": event.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "metadata": event.get("metadata", {}),
        }
        reservation_id = event.get("budget_reservation_id") or event.get("reservation_id")
        if reservation_id and get_budget_manager():
            get_budget_manager().reconcile_reservation(reservation_id, result)
            result["budget_reservation_id"] = reservation_id
        try:
            self.store.execute("""INSERT INTO usage_events(usage_id,trace_id,run_id,agent_id,agent_name,business_function,provider,model,prompt_tokens,completion_tokens,total_tokens,estimated_input_cost,estimated_output_cost,estimated_total_cost,currency,pricing_source,usage_source,estimated_method,latency_ms,retry_count,fallback_used,fallback_from_model,fallback_to_model,status,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                result["usage_id"], result["trace_id"], result["run_id"], result["agent_id"], result["agent_name"], result["business_function"], result["provider"], result["model"], result["prompt_tokens"], result["completion_tokens"], result["total_tokens"], result["estimated_input_cost"], result["estimated_output_cost"], result["estimated_total_cost"], result["currency"], result["pricing_source"], result["usage_source"], result["estimated_method"], result["latency_ms"], result["retry_count"], int(result["fallback_used"]), result["fallback_from_model"], result["fallback_to_model"], result["status"], result["created_at"], json.dumps(result["metadata"], default=str)))
        except Exception:
            logger.exception("Usage event persistence failed; agent execution continues")
        return result

    def get_events(self, limit=100, agent_id=None, model=None, date_from=None, date_to=None):
        filters, params = [], []
        for column, value in (("agent_id", agent_id), ("model", model)):
            if value: filters.append(f"{column}=?"); params.append(value)
        if date_from: filters.append("created_at>=?"); params.append(date_from)
        if date_to: filters.append("created_at<=?"); params.append(date_to)
        where = f" WHERE {' AND '.join(filters)}" if filters else ""
        rows = self.store.query(f"SELECT * FROM usage_events{where} ORDER BY created_at DESC LIMIT ?", tuple(params + [max(1, min(int(limit), 500))]))
        for row in rows:
            row["fallback_used"] = bool(row["fallback_used"])
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return rows

    def get_summary(self):
        rows = self.store.query("SELECT * FROM usage_events")
        def grouped(key, field):
            values = {}
            for row in rows:
                name = row.get(key) or "unknown"
                values[name] = values.get(name, 0) + (row.get(field) or 0)
            return values
        latency = {}
        for row in rows:
            if row.get("latency_ms") is not None:
                latency.setdefault(row.get("agent_id") or "unknown", []).append(row["latency_ms"])
        source_breakdown = {}
        for row in rows:
            source = row.get("usage_source") or "unknown"
            source_breakdown[source] = source_breakdown.get(source, 0) + 1
        budgets = get_budget_manager().get_budget_status() if get_budget_manager() else {"definitions": [], "periods": [], "events": []}
        return {"total_runs": len({row.get("trace_id") or row["usage_id"] for row in rows}), "total_tokens": sum(row.get("total_tokens") or 0 for row in rows), "estimated_total_cost": sum(row.get("estimated_total_cost") or 0 for row in rows), "currency": "USD", "cost_label": "estimated", "cost_by_agent": grouped("agent_id", "estimated_total_cost"), "tokens_by_agent": grouped("agent_id", "total_tokens"), "cost_by_model": grouped("model", "estimated_total_cost"), "tokens_by_model": grouped("model", "total_tokens"), "daily_totals": self.store.query("SELECT substr(created_at,1,10) AS date, COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(estimated_total_cost),0) AS estimated_total_cost FROM usage_events GROUP BY substr(created_at,1,10) ORDER BY date DESC"), "average_latency_by_agent": {k: round(sum(v) / len(v), 2) for k, v in latency.items()}, "fallback_count": sum(1 for row in rows if row.get("fallback_used")), "usage_source_breakdown": source_breakdown, "budgets": budgets, "last_updated": datetime.now(timezone.utc).isoformat()}
