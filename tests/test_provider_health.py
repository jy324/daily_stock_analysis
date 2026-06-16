# -*- coding: utf-8 -*-
"""Tests for the provider-health aggregation surface.

Aggregates already-persisted per-trace provider runs (stored in
``AnalysisHistory.context_snapshot.diagnostics.provider_runs``) plus the live
circuit-breaker state into a single observability snapshot. No new storage.
"""

import json
import unittest
from datetime import date, datetime, timedelta


class AggregateProviderRunsTestCase(unittest.TestCase):
    """The pure aggregator is DB-agnostic and deterministic."""

    def setUp(self):
        from src.services.provider_health_service import ProviderHealthService

        self.aggregate = ProviderHealthService.aggregate_provider_runs

    def test_success_fallback_stale_and_latency(self):
        runs = [
            {"provider": "efinance", "success": True, "latency_ms": 100, "created_at": "2024-01-01T09:00:00"},
            {"provider": "efinance", "success": False, "latency_ms": 300, "error_type": "Timeout",
             "fallback_to": "akshare", "created_at": "2024-01-01T09:01:00"},
            {"provider": "akshare", "success": True, "latency_ms": 200, "stale_seconds": 120,
             "fallback_from": "efinance", "created_at": "2024-01-01T09:02:00"},
        ]
        out = {row["provider"]: row for row in self.aggregate(runs)}

        self.assertEqual(out["efinance"]["attempts"], 2)
        self.assertEqual(out["efinance"]["success_count"], 1)
        self.assertEqual(out["efinance"]["success_rate_pct"], 50.0)
        self.assertEqual(out["efinance"]["fallback_count"], 1)
        self.assertEqual(out["efinance"]["avg_latency_ms"], 200)  # mean(100, 300)
        self.assertEqual(out["efinance"]["last_error_type"], "Timeout")

        self.assertEqual(out["akshare"]["attempts"], 1)
        self.assertEqual(out["akshare"]["success_rate_pct"], 100.0)
        self.assertEqual(out["akshare"]["fallback_count"], 1)  # fallback_from counts
        self.assertEqual(out["akshare"]["stale_count"], 1)

    def test_sorted_by_attempts_desc(self):
        runs = [
            {"provider": "a", "success": True},
            {"provider": "b", "success": True},
            {"provider": "b", "success": True},
        ]
        result = self.aggregate(runs)
        self.assertEqual([r["provider"] for r in result], ["b", "a"])

    def test_runs_without_provider_are_skipped(self):
        runs = [{"success": True}, {"provider": "", "success": True}, {"provider": "x", "success": True}]
        result = self.aggregate(runs)
        self.assertEqual([r["provider"] for r in result], ["x"])

    def test_empty_input(self):
        self.assertEqual(self.aggregate([]), [])


class CircuitBreakerDescribeTestCase(unittest.TestCase):
    """describe() is a read-only snapshot: it must not transition state."""

    def _breaker(self):
        from data_provider.realtime_types import CircuitBreaker

        return CircuitBreaker(failure_threshold=2, cooldown_seconds=300.0)

    def test_closed_source(self):
        cb = self._breaker()
        cb.record_success("efinance")
        desc = cb.describe()
        self.assertEqual(desc["efinance"]["state"], "closed")
        self.assertEqual(desc["efinance"]["failures"], 0)

    def test_open_reports_cooldown_without_mutation(self):
        cb = self._breaker()
        cb.record_failure("akshare")
        cb.record_failure("akshare")  # threshold=2 -> OPEN
        desc1 = cb.describe()
        self.assertEqual(desc1["akshare"]["state"], "open")
        self.assertEqual(desc1["akshare"]["failures"], 2)
        self.assertIsNotNone(desc1["akshare"]["cooldown_remaining_seconds"])
        # describe must be side-effect free: state stays open across calls.
        desc2 = cb.describe()
        self.assertEqual(desc2["akshare"]["state"], "open")


class ProviderHealthServiceIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from src.config import Config
        from src.storage import DatabaseManager

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "ph.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        self._tmp.cleanup()

    def _add_record(self, *, query_id, code, created_at, provider_runs):
        from src.storage import AnalysisHistory

        with self.db.get_session() as session:
            session.add(AnalysisHistory(
                query_id=query_id, code=code, name="x", report_type="simple",
                created_at=created_at,
                context_snapshot=json.dumps({"diagnostics": {"provider_runs": provider_runs}}),
            ))
            session.commit()

    def test_aggregates_recent_records_and_filters_window(self):
        from src.services.provider_health_service import ProviderHealthService

        now = datetime.now()
        self._add_record(
            query_id="recent", code="600519", created_at=now - timedelta(hours=1),
            provider_runs=[
                {"provider": "efinance", "success": True, "latency_ms": 100},
                {"provider": "efinance", "success": False, "error_type": "HTTPError"},
            ],
        )
        # Outside the 24h window -> must be excluded.
        self._add_record(
            query_id="old", code="600519", created_at=now - timedelta(hours=48),
            provider_runs=[{"provider": "efinance", "success": False}],
        )

        result = ProviderHealthService(self.db).get_provider_health(window_hours=24)
        providers = {p["provider"]: p for p in result["providers"]}
        self.assertIn("efinance", providers)
        self.assertEqual(providers["efinance"]["attempts"], 2)  # old record excluded
        self.assertEqual(providers["efinance"]["success_rate_pct"], 50.0)
        self.assertEqual(result["records_scanned"], 1)
        self.assertIn("circuit_breakers", result)
        self.assertIn("generated_at", result)


class ProviderHealthApiTestCase(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from src.config import Config
        from src.storage import DatabaseManager

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "ph_api.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        DatabaseManager.get_instance()

    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        self._tmp.cleanup()

    def test_endpoint_returns_shape(self):
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app)
        resp = client.get("/api/v1/providers/health?window_hours=24")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("window_hours", "generated_at", "records_scanned", "providers", "circuit_breakers"):
            self.assertIn(key, body)
        self.assertEqual(body["window_hours"], 24)
        self.assertIsInstance(body["providers"], list)
        self.assertIsInstance(body["circuit_breakers"], list)


if __name__ == "__main__":
    unittest.main()
