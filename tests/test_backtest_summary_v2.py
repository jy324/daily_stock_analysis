# -*- coding: utf-8 -*-
"""Tests for v2 tradability metrics aggregated into the backtest summary.

#12 added per-result v2 fields (benchmark/excess/unfillable/cost); this rolls
them up into the summary so they are usable at the portfolio / attribution
level. Values are asserted exactly on a deterministic synthetic sample.
"""

import unittest
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.core.backtest_engine import BacktestEngine


@dataclass
class V2Row:
    eval_status: str = "completed"
    position_recommendation: str = "long"
    outcome: Optional[str] = None
    direction_correct: Optional[bool] = None
    stock_return_pct: Optional[float] = None
    simulated_return_pct: Optional[float] = None
    hit_stop_loss: Optional[bool] = None
    hit_take_profit: Optional[bool] = None
    first_hit: Optional[str] = None
    first_hit_trading_days: Optional[int] = None
    operation_advice: Optional[str] = "买入"
    analysis_date: Optional[date] = None
    # v2 fields
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None
    unfillable: Optional[bool] = None
    cost_pct: Optional[float] = None


class ComputeSummaryV2MetricsTestCase(unittest.TestCase):
    def setUp(self):
        self.rows = [
            V2Row(outcome="win", simulated_return_pct=10.0, benchmark_return_pct=2.0,
                  excess_return_pct=8.0, unfillable=False, cost_pct=0.3, analysis_date=date(2024, 1, 1)),
            V2Row(outcome="loss", simulated_return_pct=-5.0, benchmark_return_pct=2.0,
                  excess_return_pct=-7.0, unfillable=True, cost_pct=0.3, analysis_date=date(2024, 1, 2)),
            V2Row(outcome="win", simulated_return_pct=4.0, benchmark_return_pct=None,
                  excess_return_pct=None, unfillable=False, cost_pct=0.3, analysis_date=date(2024, 1, 3)),
            V2Row(position_recommendation="cash", outcome="neutral", simulated_return_pct=0.0,
                  benchmark_return_pct=1.0, excess_return_pct=-1.0, unfillable=None, cost_pct=None,
                  analysis_date=date(2024, 1, 4)),
        ]
        self.summary = BacktestEngine.compute_summary(
            results=self.rows, scope="overall", code=None, eval_window_days=10, engine_version="v2"
        )

    def test_benchmark_coverage(self):
        # 3 of 4 completed rows carry a benchmark return.
        self.assertEqual(self.summary["benchmark_coverage_pct"], 75.0)

    def test_avg_excess_and_alpha_hit_rate(self):
        # excess over {8, -7, -1} -> mean 0; one of three positive -> 33.33%.
        self.assertEqual(self.summary["avg_excess_return_pct"], 0.0)
        self.assertEqual(self.summary["alpha_hit_rate_pct"], 33.33)

    def test_avg_cost(self):
        # three long trades each 0.3%.
        self.assertEqual(self.summary["avg_cost_pct"], 0.3)

    def test_unfillable_rate(self):
        # one of three evaluated long trades is unfillable.
        self.assertEqual(self.summary["unfillable_rate_pct"], 33.33)

    def test_tradable_win_rate_excludes_unfillable(self):
        # Normal win rate is 2/3; the single loss is unfillable, so the tradable
        # win rate over fillable trades is 2/2 = 100%.
        self.assertEqual(self.summary["win_rate_pct"], 66.67)
        self.assertEqual(self.summary["tradable_win_rate_pct"], 100.0)

    def test_v1_rows_yield_none_v2_metrics(self):
        v1_rows = [
            V2Row(outcome="win", simulated_return_pct=5.0, analysis_date=date(2024, 1, 1)),
            V2Row(outcome="loss", simulated_return_pct=-2.0, analysis_date=date(2024, 1, 2)),
        ]
        summary = BacktestEngine.compute_summary(
            results=v1_rows, scope="overall", code=None, eval_window_days=10, engine_version="v1"
        )
        self.assertIsNone(summary["avg_excess_return_pct"])
        self.assertIsNone(summary["alpha_hit_rate_pct"])
        self.assertIsNone(summary["unfillable_rate_pct"])
        self.assertEqual(summary["benchmark_coverage_pct"], 0.0)


class BacktestSummaryV2ColumnMigrationTestCase(unittest.TestCase):
    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()

    def test_existing_summary_table_gains_v2_columns(self):
        import sqlite3
        import tempfile

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_summary_v2.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE backtest_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scope VARCHAR(16) NOT NULL,
                        code VARCHAR(16),
                        eval_window_days INTEGER NOT NULL DEFAULT 10,
                        engine_version VARCHAR(16) NOT NULL DEFAULT 'v1'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            conn = sqlite3.connect(db_path)
            try:
                cols = {str(r[1]) for r in conn.execute('PRAGMA table_info("backtest_summaries")').fetchall()}
                for col in (
                    "benchmark_coverage_pct", "avg_excess_return_pct", "alpha_hit_rate_pct",
                    "avg_cost_pct", "unfillable_rate_pct", "tradable_win_rate_pct",
                ):
                    self.assertIn(col, cols, col)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
