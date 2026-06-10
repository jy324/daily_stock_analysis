# -*- coding: utf-8 -*-
"""Tests for decision signal generation wiring (workflow B.1)."""

from __future__ import annotations

import types
import unittest
from datetime import datetime

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.services.decision_signal_service import generate_and_persist_signal
from src.storage import AnalysisHistory, DatabaseManager


class GenerateAndPersistSignalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def _insert_history(self, **overrides) -> int:
        fields = {
            "query_id": "q-1",
            "code": "600519",
            "name": "贵州茅台",
            "report_type": "single",
            "operation_advice": "买入",
            "ideal_buy": 1680.0,
            "stop_loss": 1600.0,
            "take_profit": 1800.0,
            "created_at": datetime.now(),
        }
        fields.update(overrides)
        session = self.db.get_session()
        try:
            row = AnalysisHistory(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            row_id = row.id
        finally:
            session.close()
        return row_id

    def _result(self, **overrides):
        payload = {
            "code": "600519",
            "operation_advice": "买入",
            "action": "buy",
            "confidence_level": "高",
        }
        payload.update(overrides)
        return types.SimpleNamespace(**payload)

    def test_generates_and_links_signal_to_history(self) -> None:
        history_id = self._insert_history()
        record = generate_and_persist_signal(self.db, result=self._result(), query_id="q-1")

        self.assertIsNotNone(record)
        self.assertEqual(record.analysis_history_id, history_id)
        self.assertEqual(record.direction, "long")
        self.assertEqual(record.action, "buy")
        self.assertEqual(record.entry_type, "precise")
        self.assertEqual(record.entry_price, 1680.0)
        self.assertEqual(record.stop_loss, 1600.0)
        self.assertEqual(record.source, "normalized_fallback")

        # Persisted and retrievable.
        latest = DecisionSignalRepository(self.db).get_latest_for_analysis(history_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, record.id)

    def test_returns_none_when_no_matching_history(self) -> None:
        record = generate_and_persist_signal(self.db, result=self._result(), query_id="missing")
        self.assertIsNone(record)

    def test_picks_history_for_the_right_code_in_a_batch(self) -> None:
        # Same query_id, two stocks: must link to the matching code's row.
        self._insert_history(code="000001", name="平安银行", ideal_buy=11.0)
        target_id = self._insert_history(code="600519", ideal_buy=1680.0)

        record = generate_and_persist_signal(self.db, result=self._result(code="600519"), query_id="q-1")
        self.assertEqual(record.analysis_history_id, target_id)
        self.assertEqual(record.entry_price, 1680.0)


if __name__ == "__main__":
    unittest.main()
