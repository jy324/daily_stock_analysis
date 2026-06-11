# -*- coding: utf-8 -*-
"""Integration: generate_and_persist_signal applies quality-policy constraints (workflow C.2).

These tests do not mock the policy service: they drive the real engine off the
repo's default config/quality_policies.yaml via a persisted context snapshot.
"""

import json
import os
import tempfile
import types
import unittest
from datetime import datetime

from src.services.decision_signal_service import generate_and_persist_signal
from src.storage import AnalysisHistory, DatabaseManager


def _snapshot(quote_status="available", extra_blocks=None, phase="intraday"):
    blocks = [{"key": "quote", "status": quote_status, "label": "quote"}]
    for key, status in (extra_blocks or {}).items():
        blocks.append({"key": key, "status": status, "label": key})
    return json.dumps(
        {
            "analysis_context_pack_overview": {
                "subject": {"code": "600519"},
                "blocks": blocks,
                "data_quality": {"overall_score": 60},
            },
            "market_phase_summary": {"phase": phase, "market": "cn", "trigger_source": "api"},
        }
    )


def _result():
    return types.SimpleNamespace(
        code="600519",
        operation_advice="买入",
        action="buy",
        confidence_level="高",
        market="cn",
    )


class QualityPolicySignalIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "qp_signal.db")
        # Use the repo's shipped policy file explicitly.
        os.environ["QUALITY_POLICY_FILE"] = "config/quality_policies.yaml"
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        os.environ.pop("QUALITY_POLICY_FILE", None)
        self._tmp.cleanup()

    def _seed(self, *, query_id, snapshot, ideal_buy=100.0, secondary_buy=None):
        with self.db.get_session() as session:
            row = AnalysisHistory(
                query_id=query_id,
                code="600519",
                name="贵州茅台",
                report_type="simple",
                sentiment_score=80,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="t",
                ideal_buy=ideal_buy,
                secondary_buy=secondary_buy,
                stop_loss=90.0,
                take_profit=120.0,
                created_at=datetime(2024, 1, 1),
                context_snapshot=snapshot,
            )
            session.add(row)
            session.commit()
            return row.id

    def test_stale_quote_downgrades_precise_entry(self):
        self._seed(query_id="q1", snapshot=_snapshot(quote_status="stale"))
        record = generate_and_persist_signal(self.db, result=_result(), query_id="q1", market="cn")

        self.assertIsNotNone(record)
        self.assertEqual(record.entry_type, "none")
        self.assertIsNone(record.entry_price)
        self.assertIn("quote_degraded_no_precise_entry", record.quality_constraints.get("policies", []))

    def test_healthy_quote_keeps_precise_entry(self):
        self._seed(query_id="q2", snapshot=_snapshot(quote_status="available"))
        record = generate_and_persist_signal(self.db, result=_result(), query_id="q2", market="cn")

        self.assertEqual(record.entry_type, "precise")
        self.assertEqual(record.entry_price, 100.0)
        self.assertEqual(record.quality_constraints, {})

    def test_two_degraded_core_blocks_force_observation_only(self):
        snapshot = _snapshot(quote_status="stale", extra_blocks={"daily_bars": "fetch_failed"})
        self._seed(query_id="q3", snapshot=snapshot)
        record = generate_and_persist_signal(self.db, result=_result(), query_id="q3", market="cn")

        self.assertEqual(record.direction, "neutral")
        self.assertEqual(record.entry_type, "none")
        self.assertIn("core_blocks_observation_only", record.quality_constraints.get("policies", []))


if __name__ == "__main__":
    unittest.main()
