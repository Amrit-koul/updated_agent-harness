import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_harness.budget import BudgetExceeded, BudgetManager
from agent_harness.invocation import RuntimeInvocationError
from agent_harness.model_gateway import ModelGateway
from agent_harness.store import ControlPlaneStore
from agent_harness.usage import UsageMeter, configure_budget_manager, configure_usage_meter, usage_context


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _Message:
    content = "ok"


class _Choice:
    message = _Message()


class _Response:
    usage = _Usage()
    choices = [_Choice()]


class _ChatCompletions:
    def __init__(self, error=None):
        self.error = error

    def create(self, **_kwargs):
        if self.error:
            raise self.error
        return _Response()


class _Chat:
    def __init__(self, error=None):
        self.completions = _ChatCompletions(error)


class _Client:
    def __init__(self, error=None):
        self.chat = _Chat(error)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ControlPlaneStore(Path(tmp.name) / "control_plane.db")
        self.addCleanup(self.store.conn.close)
        self.meter = UsageMeter(self.store)
        self.manager = BudgetManager(self.store, self.meter)
        configure_usage_meter(self.meter)
        configure_budget_manager(self.manager)

    def reserve(self, policy=None, projected=None, agent_id="agent_1"):
        return self.manager.reserve(
            agent_id=agent_id,
            policy=policy or {"period": "day", "max_total_tokens": 100, "warning_threshold_pct": 80, "enforcement_mode": "hard_block"},
            provider="groq",
            model="small",
            trace_id="trace",
            invocation_id="inv",
            projected=projected or {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "cost": 0},
        )

    def test_under_budget_reserves(self):
        reservation = self.reserve()
        self.assertTrue(reservation["reservation_id"])
        row = self.store.query("SELECT total_tokens_reserved FROM budget_usage_periods")[0]
        self.assertEqual(row["total_tokens_reserved"], 30)

    def test_warning_threshold_event_created_once(self):
        policy = {"period": "day", "max_total_tokens": 100, "warning_threshold_pct": 50, "enforcement_mode": "warn"}
        self.reserve(policy, {"input_tokens": 10, "output_tokens": 45, "total_tokens": 55, "cost": 0})
        self.reserve(policy, {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "cost": 0})
        events = self.store.query("SELECT * FROM budget_events WHERE event_type='budget_threshold_crossed'")
        self.assertEqual(len(events), 1)

    def test_hard_block(self):
        with self.assertRaises(BudgetExceeded):
            self.reserve(projected={"input_tokens": 1, "output_tokens": 200, "total_tokens": 201, "cost": 0})

    def test_concurrent_reservations_do_not_overspend(self):
        policy = {"period": "day", "max_total_tokens": 100, "enforcement_mode": "hard_block"}
        def attempt(_):
            try:
                self.reserve(policy, {"input_tokens": 0, "output_tokens": 30, "total_tokens": 30, "cost": 0})
                return True
            except BudgetExceeded:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(results.count(True), 3)
        row = self.store.query("SELECT total_tokens_reserved FROM budget_usage_periods")[0]
        self.assertEqual(row["total_tokens_reserved"], 90)

    def test_provider_actual_less_than_reserved_releases_unused(self):
        reservation = self.reserve(projected={"input_tokens": 50, "output_tokens": 30, "total_tokens": 80, "cost": 0})
        self.manager.reconcile_reservation(reservation["reservation_id"], {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "estimated_total_cost": 0, "usage_source": "provider_reported"})
        row = self.store.query("SELECT total_tokens_reserved,total_tokens_used FROM budget_usage_periods")[0]
        self.assertEqual((row["total_tokens_reserved"], row["total_tokens_used"]), (0, 15))

    def test_provider_actual_greater_than_reserved_is_persisted(self):
        reservation = self.reserve(projected={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "cost": 0})
        self.manager.reconcile_reservation(reservation["reservation_id"], {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120, "estimated_total_cost": 0, "usage_source": "provider_reported"})
        row = self.store.query("SELECT total_tokens_reserved,total_tokens_used FROM budget_usage_periods")[0]
        self.assertEqual((row["total_tokens_reserved"], row["total_tokens_used"]), (0, 120))

    def test_failure_releases_reservation(self):
        gateway = ModelGateway()
        with usage_context(agent_id="agent_1", trace_id="trace", invocation_id="inv", budget_policy={"period": "day", "max_total_tokens": 100, "max_output_tokens": 20, "enforcement_mode": "hard_block"}, model_policy={"allowed_fallbacks": []}):
            with self.assertRaises(ValueError):
                gateway.chat_completions_create(_Client(ValueError("boom")), provider="groq", model="small", messages=[{"role": "user", "content": "hello"}])
        row = self.store.query("SELECT total_tokens_reserved FROM budget_usage_periods")[0]
        self.assertEqual(row["total_tokens_reserved"], 0)

    def test_daily_period_reset(self):
        with patch("agent_harness.budget._now") as now:
            from datetime import datetime, timezone
            now.return_value = datetime(2026, 7, 8, 10, tzinfo=timezone.utc)
            self.reserve()
            now.return_value = datetime(2026, 7, 9, 10, tzinfo=timezone.utc)
            self.reserve()
        self.assertEqual(self.store.query("SELECT COUNT(*) AS n FROM budget_usage_periods")[0]["n"], 2)

    def test_monthly_period_reset(self):
        policy = {"period": "month", "max_total_tokens": 1000, "enforcement_mode": "hard_block"}
        with patch("agent_harness.budget._now") as now:
            from datetime import datetime, timezone
            now.return_value = datetime(2026, 7, 31, 10, tzinfo=timezone.utc)
            self.reserve(policy)
            now.return_value = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
            self.reserve(policy)
        self.assertEqual(self.store.query("SELECT COUNT(*) AS n FROM budget_usage_periods")[0]["n"], 2)

    def test_undeclared_fallback_rejected(self):
        gateway = ModelGateway()
        with usage_context(agent_id="agent_1", budget_policy={"period": "day", "allowed_fallback_deployments": ["small"]}, model_policy={"allowed_fallbacks": ["small"]}):
            with self.assertRaises(RuntimeInvocationError):
                gateway.chat_completions_create(_Client(), provider="groq", model="other", messages=[], fallback_from_model="large")

    def test_monitor_mode_does_not_block(self):
        reservation = self.reserve({"period": "day", "max_total_tokens": 1, "enforcement_mode": "monitor"}, {"input_tokens": 1, "output_tokens": 5, "total_tokens": 6, "cost": 0})
        self.assertTrue(reservation["reservation_id"])

    def test_usage_ui_payload_matches_database(self):
        self.reserve()
        status = self.manager.get_budget_status()
        self.assertEqual(len(status["definitions"]), self.store.query("SELECT COUNT(*) AS n FROM budget_definitions")[0]["n"])
        self.assertEqual(len(status["periods"]), self.store.query("SELECT COUNT(*) AS n FROM budget_usage_periods")[0]["n"])


if __name__ == "__main__":
    unittest.main()
