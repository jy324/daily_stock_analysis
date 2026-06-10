# -*- coding: utf-8 -*-
"""Tests for the daily advancement orchestration (workflow B.2)."""

from __future__ import annotations

import unittest
from datetime import date

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal
from src.services.decision_signal_service import advance_active_signals
from src.storage import DatabaseManager


class AdvanceActiveSignalsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.repo = DecisionSignalRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def _save(self, **overrides):
        payload = {
            "code": "600519",
            "analysis_history_id": 1,
            "direction": "long",
            "action": "buy",
            "entry_type": "precise",
            "entry_price": 1680.0,
            "stop_loss": 1600.0,
            "take_profit": 1800.0,
            "valid_until": date(2026, 6, 30),
            "state": "waiting_entry",
        }
        payload.update(overrides)
        return self.repo.save_signal(DecisionSignal(**payload))

    def test_entry_fill_is_persisted_with_history(self) -> None:
        rec = self._save()

        def provider(code, day):
            return {"open": 1700, "high": 1705, "low": 1675, "close": 1690}

        summary = advance_active_signals(self.db, today=date(2026, 6, 11), ohlc_provider=provider)

        self.assertEqual(summary["scanned"], 1)
        self.assertEqual(summary["transitioned"], 1)
        updated = self.repo.get_latest_for_analysis(rec.analysis_history_id)
        self.assertEqual(updated.state, "entered")
        self.assertEqual(updated.entered_price, 1680.0)
        self.assertEqual(updated.entered_date, date(2026, 6, 11))
        self.assertEqual(updated.state_history[-1]["to"], "entered")
        self.assertEqual(updated.state_history[-1]["from"], "waiting_entry")

    def test_no_trigger_leaves_signal_unchanged(self) -> None:
        rec = self._save()

        def provider(code, day):
            return {"open": 1720, "high": 1740, "low": 1700, "close": 1730}

        summary = advance_active_signals(self.db, today=date(2026, 6, 11), ohlc_provider=provider)
        self.assertEqual(summary["transitioned"], 0)
        self.assertEqual(self.repo.get_latest_for_analysis(rec.analysis_history_id).state, "waiting_entry")

    def test_stop_hit_records_close(self) -> None:
        rec = self._save(state="entered")

        def provider(code, day):
            return {"open": 1650, "high": 1660, "low": 1590, "close": 1600}

        advance_active_signals(self.db, today=date(2026, 6, 12), ohlc_provider=provider)
        updated = self.repo.get_latest_for_analysis(rec.analysis_history_id)
        self.assertEqual(updated.state, "stop_hit")
        self.assertEqual(updated.closed_price, 1600.0)
        self.assertEqual(updated.closed_date, date(2026, 6, 12))

    def test_provider_error_is_isolated(self) -> None:
        good = self._save(analysis_history_id=1, code="600519")
        bad = self._save(analysis_history_id=2, code="000001", entry_price=11.0, stop_loss=9.0, take_profit=13.0)

        def provider(code, day):
            if code == "000001":
                raise RuntimeError("data fetch failed")
            return {"open": 1700, "high": 1705, "low": 1675, "close": 1690}

        summary = advance_active_signals(self.db, today=date(2026, 6, 11), ohlc_provider=provider)
        self.assertEqual(summary["scanned"], 2)
        self.assertEqual(summary["transitioned"], 1)
        self.assertEqual(summary["errors"], 1)
        # The healthy signal still advanced.
        self.assertEqual(self.repo.get_latest_for_analysis(good.analysis_history_id).state, "entered")
        # The failed one is untouched.
        self.assertEqual(self.repo.get_latest_for_analysis(bad.analysis_history_id).state, "waiting_entry")


if __name__ == "__main__":
    unittest.main()
