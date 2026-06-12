# -*- coding: utf-8 -*-
"""Exact-value tests for backtest risk/return metrics (workflow D.1a)."""

import math
import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from src.core.backtest_engine import BacktestEngine


@dataclass
class R:
    simulated_return_pct: Optional[float]
    analysis_date: date
    eval_status: str = "completed"
    first_hit_trading_days: Optional[int] = None


def _series(returns, start=date(2024, 1, 1)):
    return [R(simulated_return_pct=r, analysis_date=start + timedelta(days=i)) for i, r in enumerate(returns)]


class RiskMetricsTestCase(unittest.TestCase):
    def setUp(self):
        # Hand-computed reference series (percent per-trade returns), in date order.
        self.metrics = BacktestEngine.compute_risk_metrics(_series([10, -5, 20, -10, 5]))

    def test_volatility_is_sample_std(self):
        # sample variance = 570/4 = 142.5 -> std = sqrt(142.5)
        self.assertAlmostEqual(self.metrics["volatility_pct"], math.sqrt(142.5), places=4)

    def test_sharpe_is_mean_over_sample_std(self):
        self.assertAlmostEqual(self.metrics["sharpe"], 4.0 / math.sqrt(142.5), places=4)

    def test_sortino_uses_downside_deviation_to_zero(self):
        # downside squared mean = (25 + 100) / 5 = 25 -> dev = 5.0 ; mean = 4.0
        self.assertAlmostEqual(self.metrics["sortino"], 4.0 / 5.0, places=4)

    def test_max_drawdown_pct_from_compounded_equity_curve(self):
        # peak 1.254 -> 1.1286 = 10.0% drawdown
        self.assertAlmostEqual(self.metrics["max_drawdown_pct"], 10.0, places=4)

    def test_calmar_is_total_return_over_max_drawdown(self):
        # final equity 1.18503 -> total return 18.503% / 10.0
        self.assertAlmostEqual(self.metrics["calmar"], 18.503 / 10.0, places=4)

    def test_profit_factor_is_gross_win_over_gross_loss(self):
        self.assertAlmostEqual(self.metrics["profit_factor"], 35.0 / 15.0, places=4)

    def test_payoff_ratio_is_avg_win_over_avg_loss(self):
        self.assertAlmostEqual(self.metrics["payoff_ratio"], (35.0 / 3.0) / (15.0 / 2.0), places=4)


class RiskMetricsEdgeCaseTestCase(unittest.TestCase):
    def test_single_trade_has_no_volatility_or_sharpe(self):
        m = BacktestEngine.compute_risk_metrics(_series([7]))
        self.assertIsNone(m["volatility_pct"])
        self.assertIsNone(m["sharpe"])
        self.assertIsNone(m["sortino"])  # no downside
        self.assertEqual(m["max_drawdown_pct"], 0.0)

    def test_no_losses_means_no_profit_factor_or_payoff(self):
        m = BacktestEngine.compute_risk_metrics(_series([3, 4, 5]))
        self.assertIsNone(m["profit_factor"])
        self.assertIsNone(m["payoff_ratio"])

    def test_empty_results_yield_all_none(self):
        m = BacktestEngine.compute_risk_metrics([])
        for key in ("volatility_pct", "sharpe", "sortino", "calmar", "profit_factor", "payoff_ratio"):
            self.assertIsNone(m[key], key)
        self.assertEqual(m["max_drawdown_pct"], 0.0)
        self.assertEqual(m["holding_period_stats"], {})

    def test_non_completed_and_null_returns_are_excluded(self):
        rows = _series([10, -5])
        rows.append(R(simulated_return_pct=999.0, analysis_date=date(2024, 2, 1), eval_status="insufficient_data"))
        rows.append(R(simulated_return_pct=None, analysis_date=date(2024, 2, 2)))
        m = BacktestEngine.compute_risk_metrics(rows)
        # Only [10, -5] count -> profit_factor = 10/5 = 2.0
        self.assertAlmostEqual(m["profit_factor"], 2.0, places=4)

    def test_holding_period_stats_from_first_hit_days(self):
        rows = [
            R(simulated_return_pct=5.0, analysis_date=date(2024, 1, 1), first_hit_trading_days=3),
            R(simulated_return_pct=-2.0, analysis_date=date(2024, 1, 2), first_hit_trading_days=7),
            R(simulated_return_pct=1.0, analysis_date=date(2024, 1, 3), first_hit_trading_days=None),
        ]
        stats = BacktestEngine.compute_risk_metrics(rows)["holding_period_stats"]
        self.assertEqual(stats["count"], 2)
        self.assertAlmostEqual(stats["avg"], 5.0, places=4)
        self.assertEqual(stats["min"], 3)
        self.assertEqual(stats["max"], 7)


@dataclass
class SummaryRow:
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


class ComputeSummaryRiskMetricsTestCase(unittest.TestCase):
    def test_summary_includes_risk_metrics(self):
        rows = [
            SummaryRow(simulated_return_pct=10.0, outcome="win", analysis_date=date(2024, 1, 1), first_hit_trading_days=2),
            SummaryRow(simulated_return_pct=-5.0, outcome="loss", analysis_date=date(2024, 1, 2), first_hit_trading_days=4),
        ]
        summary = BacktestEngine.compute_summary(
            results=rows, scope="overall", code=None, eval_window_days=10, engine_version="v1"
        )
        self.assertAlmostEqual(summary["profit_factor"], 2.0, places=4)
        self.assertEqual(summary["max_drawdown_pct"], 5.0)
        self.assertEqual(summary["holding_period_stats"]["count"], 2)
        self.assertIn("sharpe", summary)


class BacktestSummaryRiskColumnMigrationTestCase(unittest.TestCase):
    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()

    def test_existing_summary_table_gains_risk_columns(self):
        import sqlite3
        import tempfile

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_summary.db"
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
                conn.execute("INSERT INTO backtest_summaries (scope) VALUES ('overall')")
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            conn = sqlite3.connect(db_path)
            try:
                cols = {str(r[1]) for r in conn.execute('PRAGMA table_info("backtest_summaries")').fetchall()}
                for col in (
                    "max_drawdown_pct", "volatility_pct", "sharpe", "sortino",
                    "calmar", "profit_factor", "payoff_ratio", "holding_period_stats_json",
                ):
                    self.assertIn(col, cols, col)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
