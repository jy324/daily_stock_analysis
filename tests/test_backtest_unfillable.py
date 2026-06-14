# -*- coding: utf-8 -*-
"""Tests for the v2 unfillable (sealed limit board) flag (workflow D.1c)."""

import unittest
from dataclasses import dataclass
from datetime import date, timedelta

from src.core.backtest_engine import BacktestEngine, EvaluationConfig
from src.schemas.decision_signal import DecisionSignal


@dataclass
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float


def _bars(start, rows):
    return [Bar(date=start + timedelta(days=i + 1), open=o, high=h, low=lo, close=c)
            for i, (o, h, lo, c) in enumerate(rows)]


_V2 = EvaluationConfig(eval_window_days=3, engine_version="v2")
_V1 = EvaluationConfig(eval_window_days=3, engine_version="v1")


class SignalUnfillableTestCase(unittest.TestCase):
    def _signal(self):
        return DecisionSignal(
            code="600519", analysis_history_id=1, direction="long", action="buy",
            entry_type="market", valid_until=date(2024, 12, 31),
        )

    def test_entry_on_sealed_board_is_unfillable(self):
        # Day 1 is a one-price sealed board (limit-up): market entry cannot really fill.
        bars = _bars(date(2024, 1, 1), [(100, 100, 100, 100), (100, 103, 101, 102), (102, 105, 103, 104)])
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=self._signal(), analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, config=_V2,
        )
        self.assertTrue(res["entered"])
        self.assertTrue(res["unfillable"])

    def test_normal_bars_are_fillable(self):
        bars = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=self._signal(), analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, config=_V2,
        )
        self.assertFalse(res["unfillable"])

    def test_v1_does_not_compute_unfillable(self):
        bars = _bars(date(2024, 1, 1), [(100, 100, 100, 100), (100, 103, 101, 102), (102, 105, 103, 104)])
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=self._signal(), analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, config=_V1,
        )
        self.assertIsNone(res["unfillable"])


class EvaluateSingleUnfillableTestCase(unittest.TestCase):
    def test_exit_on_sealed_board_is_unfillable(self):
        # Day 2 is a sealed limit-down board where the stop triggers but can't sell.
        bars = _bars(date(2024, 1, 1), [(100, 101, 99, 100), (90, 90, 90, 90), (90, 91, 89, 90)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, stop_loss=95.0, take_profit=None, config=_V2,
        )
        self.assertEqual(res["first_hit"], "stop_loss")
        self.assertTrue(res["unfillable"])

    def test_window_end_exit_not_unfillable(self):
        bars = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, stop_loss=None, take_profit=None, config=_V2,
        )
        self.assertFalse(res["unfillable"])

    def test_v1_exit_unfillable_is_none(self):
        bars = _bars(date(2024, 1, 1), [(100, 101, 99, 100), (90, 90, 90, 90), (90, 91, 89, 90)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, stop_loss=95.0, take_profit=None, config=_V1,
        )
        self.assertIsNone(res["unfillable"])

    def test_entry_day_sealed_board_is_unfillable(self):
        # The analysis/entry day itself was a one-price sealed board (limit-up): the
        # legacy keyword path assumes entry at start_price, but that fill was impossible.
        bars = _bars(date(2024, 1, 1), [(102, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            start_high=100.0, start_low=100.0,
            forward_bars=bars, stop_loss=None, take_profit=None, config=_V2,
        )
        self.assertTrue(res["unfillable"])

    def test_entry_day_normal_not_unfillable(self):
        bars = _bars(date(2024, 1, 1), [(102, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            start_high=101.0, start_low=99.0,
            forward_bars=bars, stop_loss=None, take_profit=None, config=_V2,
        )
        self.assertFalse(res["unfillable"])

    def test_v1_entry_day_sealed_unfillable_is_none(self):
        bars = _bars(date(2024, 1, 1), [(102, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            start_high=100.0, start_low=100.0,
            forward_bars=bars, stop_loss=None, take_profit=None, config=_V1,
        )
        self.assertIsNone(res["unfillable"])

    def test_cash_position_entry_day_sealed_not_unfillable(self):
        # No long position taken -> nothing to fill, so a sealed entry day is irrelevant.
        bars = _bars(date(2024, 1, 1), [(102, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        res = BacktestEngine.evaluate_single(
            operation_advice="卖出", analysis_date=date(2024, 1, 1), start_price=100.0,
            start_high=100.0, start_low=100.0,
            forward_bars=bars, stop_loss=None, take_profit=None, config=_V2,
        )
        self.assertFalse(res["unfillable"])


class UnfillableColumnMigrationTestCase(unittest.TestCase):
    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()

    def test_existing_results_table_gains_unfillable(self):
        import sqlite3
        import tempfile

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_unfill.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE backtest_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        analysis_history_id INTEGER NOT NULL,
                        code VARCHAR(10) NOT NULL,
                        eval_window_days INTEGER NOT NULL DEFAULT 10,
                        engine_version VARCHAR(16) NOT NULL DEFAULT 'v1',
                        eval_status VARCHAR(16) NOT NULL DEFAULT 'completed'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            conn = sqlite3.connect(db_path)
            try:
                cols = {str(r[1]) for r in conn.execute('PRAGMA table_info("backtest_results")').fetchall()}
                self.assertIn("unfillable", cols)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
