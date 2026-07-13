"""Canonical model gateway with budget reservation and usage reconciliation."""
from __future__ import annotations

from time import perf_counter

from .budget import BudgetExceeded
from .invocation import RuntimeErrorCode, RuntimeInvocationError
from .usage import current_usage_context, get_budget_manager, get_usage_meter


class ModelGateway:
    def chat_completions_create(self, client, *, provider, model, messages, agent_id=None, budget_policy=None, model_policy=None,
                                trace_id=None, invocation_id=None, high_risk=False, fallback_from_model=None, **kwargs):
        meter = get_usage_meter()
        manager = get_budget_manager()
        context = current_usage_context()
        agent_id = agent_id or context.get("agent_id")
        budget_policy = budget_policy or context.get("budget_policy") or {}
        model_policy = model_policy or context.get("model_policy") or {}
        trace_id = trace_id or context.get("trace_id")
        invocation_id = invocation_id or context.get("invocation_id")
        high_risk = high_risk or context.get("risk_tier") in {"high", "critical"}
        metadata = kwargs.pop("budget_metadata", {}) or {}
        if fallback_from_model:
            allowed_contract = set(model_policy.get("allowed_fallbacks") or [])
            allowed_budget = set(budget_policy.get("allowed_fallback_deployments") or [])
            if high_risk:
                raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, "Fallback downgrade requires human review for high-risk tasks")
            if budget_policy.get("fallback_action") not in {"smaller_model", "none", None}:
                raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, "Budget policy does not allow automatic model fallback")
            if model not in allowed_contract or (allowed_budget and model not in allowed_budget):
                raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, "Fallback deployment is not declared and budget-approved")
            if meter:
                primary = meter.pricing.get((str(provider).lower(), str(fallback_from_model)))
                fallback = meter.pricing.get((str(provider).lower(), str(model)))
                if not primary or not fallback:
                    raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, "Fallback pricing is not configured")
                primary_rate = float(primary.get("input_cost_per_1k_tokens", 0)) + float(primary.get("output_cost_per_1k_tokens", 0))
                fallback_rate = float(fallback.get("input_cost_per_1k_tokens", 0)) + float(fallback.get("output_cost_per_1k_tokens", 0))
                if fallback_rate >= primary_rate:
                    raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, "Fallback deployment is not cheaper than the original model")
        reservation = None
        if manager and budget_policy and agent_id:
            projected = manager.projected_usage(budget_policy, provider, model, messages=messages, max_output_tokens=kwargs.get("max_tokens") or kwargs.get("max_completion_tokens"))
            try:
                reservation = manager.reserve(agent_id=agent_id, policy=budget_policy, provider=provider, model=model, trace_id=trace_id, invocation_id=invocation_id, projected=projected, metadata=metadata)
            except BudgetExceeded as exc:
                raise RuntimeInvocationError(RuntimeErrorCode.BUDGET_EXCEEDED, str(exc), original=exc) from exc
        started = perf_counter()
        try:
            response = client.chat.completions.create(model=model, messages=messages, **kwargs)
        except Exception:
            if reservation and manager:
                manager.release_reservation(reservation["reservation_id"], "failed")
            raise
        if meter:
            prompt = "\n".join(str(message.get("content", "")) for message in messages)
            completion = getattr(response.choices[0].message, "content", "") if getattr(response, "choices", None) else ""
            usage = meter.record_llm_response(
                response, provider=provider, model=model, prompt=prompt, completion=completion,
                latency_ms=int((perf_counter() - started) * 1000),
                fallback_used=bool(fallback_from_model), fallback_from_model=fallback_from_model,
                fallback_to_model=model if fallback_from_model else None,
                budget_reservation_id=reservation["reservation_id"] if reservation else None,
                metadata={**metadata, "budget_reservation_id": reservation["reservation_id"] if reservation else None, "fallback_audit": {"from": fallback_from_model, "to": model} if fallback_from_model else None},
            )
            try:
                setattr(response, "_agent_harness_usage", usage)
            except Exception:
                pass
        return response


_GATEWAY = ModelGateway()


def get_model_gateway():
    return _GATEWAY
