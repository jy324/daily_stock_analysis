# -*- coding: utf-8 -*-
"""Tests for the DecisionSignal persistence repository (workflow B.1)."""

from __future__ import annotations

import unittest

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal
from src.storage import DatabaseManager


class DecisionSignalRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.repo = DecisionSignalRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def _signal(self, **overrides) -> DecisionSignal:
        payload = {
            "code": "600519",
            "analysis_history_id": 42,
            "direction": "long",
            "action": "buy",
            "entry_type": "zone",
            "entry_low": 1650.0,
            "entry_high": 1680.0,
            "stop_loss": 1600.0,
            "take_profit": 1800.0,
            "confidence_level": "high",
            "confidence_score": 72,
            "operation_advice": "买入",
            "invalidation_conditions": ["跌破1600", "放量破位"],
            "applicable_phases": ["intraday"],
            "quality_constraints": {"prohibit_precise_entry": False},
        }
        payload.update(overrides)
        return DecisionSignal(**payload)

    def test_save_and_read_round_trip(self) -> None:
        saved = self.repo.save_signal(self._signal())
        self.assertIsNotNone(saved.id)

        found = self.repo.get_latest_for_analysis(42)
        self.assertIsNotNone(found)
        self.assertEqual(found.code, "600519")
        self.assertEqual(found.direction, "long")
        self.assertEqual(found.action, "buy")
        self.assertEqual(found.entry_type, "zone")
        self.assertEqual(found.entry_low, 1650.0)
        self.assertEqual(found.entry_high, 1680.0)
        self.assertEqual(found.confidence_score, 72)
        self.assertEqual(found.state, "generated")
        # JSON-encoded structures survive the round trip.
        self.assertEqual(found.invalidation_conditions, ["跌破1600", "放量破位"])
        self.assertEqual(found.applicable_phases, ["intraday"])
        self.assertEqual(found.quality_constraints, {"prohibit_precise_entry": False})

    def test_to_signal_reconstructs_schema(self) -> None:
        self.repo.save_signal(self._signal())
        record = self.repo.get_latest_for_analysis(42)
        restored = record.to_signal()
        self.assertIsInstance(restored, DecisionSignal)
        self.assertEqual(restored.entry_high, 1680.0)
        self.assertEqual(restored.invalidation_conditions, ["跌破1600", "放量破位"])

    def test_latest_returns_highest_version(self) -> None:
        self.repo.save_signal(self._signal(signal_version=1))
        self.repo.save_signal(self._signal(signal_version=2, action="add"))
        latest = self.repo.get_latest_for_analysis(42)
        self.assertEqual(latest.signal_version, 2)
        self.assertEqual(latest.action, "add")

    def test_missing_analysis_returns_none(self) -> None:
        self.assertIsNone(self.repo.get_latest_for_analysis(999))


if __name__ == "__main__":
    unittest.main()
