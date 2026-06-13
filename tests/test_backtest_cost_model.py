# -*- coding: utf-8 -*-
"""Tests for the v2 trading-cost model (workflow D.1b)."""

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


# A-share default round trip: 2*0.00025 commission + 0.0005 stamp + 0 slippage = 0.001 -> 0.1%
_V2 = EvaluationConfig(
    eval_window_days=3, neutral_band_pct=2.0, engine_version="v2",
    commission_rate=0.00025, stamp_tax_rate=0.0005, slippage_bp=0.0,
)
_V1 = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0, engine_version="v1")


class RoundTripCostTestCase(unittest.TestCase):
    def test_round_trip_cost_pct_exact(self):
        self.assertAlmostEqual(BacktestEngine.round_trip_cost_pct(_V2), 0.1, places=6)

    def test_slippage_adds_both_sides(self):
        cfg = EvaluationConfig(
            eval_window_days=3, engine_version="v2",
            commission_rate=0.0, stamp_tax_rate=0.0, slippage_bp=10.0,  # 10bp/side -> 0.2%
        )
        self.assertAlmostEqual(BacktestEngine.round_trip_cost_pct(cfg), 0.2, places=6)

    def test_v1_has_zero_cost(self):
        self.assertEqual(BacktestEngine.round_trip_cost_pct(_V1), 0.0)


class EvaluateSingleCostTestCase(unittest.TestCase):
    def setUp(self):
        # Long "买入", no targets hit, window-end close 105 from start 100 -> gross +5%.
        self.bars = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])

    def _eval(self, cfg):
        return BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=self.bars, stop_loss=None, take_profit=None, config=cfg,
        )

    def test_v2_applies_round_trip_cost(self):
        res = self._eval(_V2)
        self.assertAlmostEqual(res["cost_pct"], 0.1, places=6)
        self.assertAlmostEqual(res["simulated_return_pct"], 5.0 - 0.1, places=6)

    def test_v1_is_unchanged_gross(self):
        res = self._eval(_V1)
        self.assertEqual(res["cost_pct"], 0.0)
        self.assertAlmostEqual(res["simulated_return_pct"], 5.0, places=6)

    def test_cash_trade_has_no_cost(self):
        res = BacktestEngine.evaluate_single(
            operation_advice="卖出", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=self.bars, stop_loss=None, take_profit=None, config=_V2,
        )
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["cost_pct"], 0.0)
        self.assertEqual(res["simulated_return_pct"], 0.0)


class EvaluateFromSignalCostTestCase(unittest.TestCase):
    def test_v2_signal_path_applies_cost(self):
        bars = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])
        signal = DecisionSignal(
            code="600519", analysis_history_id=1, direction="long", action="buy",
            entry_type="market", valid_until=date(2024, 12, 31),
        )
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal, analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, config=_V2,
        )
        self.assertAlmostEqual(res["cost_pct"], 0.1, places=6)
        self.assertAlmostEqual(res["simulated_return_pct"], 5.0 - 0.1, places=6)

    def test_not_entered_signal_has_no_cost(self):
        bars = _bars(date(2024, 1, 1), [(99, 100, 96, 99), (100, 101, 97, 100), (101, 102, 98, 101)])
        signal = DecisionSignal(
            code="600519", analysis_history_id=1, direction="long", action="buy",
            entry_type="zone", entry_low=90.0, entry_high=92.0, valid_until=date(2024, 12, 31),
        )
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal, analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=bars, config=_V2,
        )
        self.assertFalse(res["entered"])
        self.assertEqual(res["cost_pct"], 0.0)
        self.assertEqual(res["simulated_return_pct"], 0.0)


class CostColumnMigrationTestCase(unittest.TestCase):
    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()

    def test_existing_results_table_gains_cost_pct(self):
        import sqlite3
        import tempfile

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_cost.db"
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
                self.assertIn("cost_pct", cols)
                self.assertIn("signal_based", cols)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
