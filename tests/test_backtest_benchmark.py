# -*- coding: utf-8 -*-
"""Tests for benchmark excess-return in the backtest engine (workflow D.1c)."""

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


_CFG = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0, engine_version="v2")
_BARS = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])


class EvaluateSingleBenchmarkTestCase(unittest.TestCase):
    def _eval(self, **kw):
        return BacktestEngine.evaluate_single(
            operation_advice="买入", analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=_BARS, stop_loss=None, take_profit=None, config=_CFG, **kw,
        )

    def test_excess_is_simulated_minus_benchmark(self):
        res = self._eval(benchmark_code="000300", benchmark_return_pct=2.0)
        self.assertEqual(res["benchmark_code"], "000300")
        self.assertEqual(res["benchmark_return_pct"], 2.0)
        # gross long return +5% (v2 cost 0 here since rates default 0) -> excess 5 - 2 = 3
        self.assertAlmostEqual(res["excess_return_pct"], res["simulated_return_pct"] - 2.0, places=6)

    def test_no_benchmark_yields_none(self):
        res = self._eval()
        self.assertIsNone(res["benchmark_code"])
        self.assertIsNone(res["benchmark_return_pct"])
        self.assertIsNone(res["excess_return_pct"])

    def test_benchmark_code_kept_when_return_unavailable(self):
        res = self._eval(benchmark_code="000300", benchmark_return_pct=None)
        self.assertEqual(res["benchmark_code"], "000300")
        self.assertIsNone(res["benchmark_return_pct"])
        self.assertIsNone(res["excess_return_pct"])


class EvaluateFromSignalBenchmarkTestCase(unittest.TestCase):
    def test_signal_path_excess(self):
        signal = DecisionSignal(
            code="600519", analysis_history_id=1, direction="long", action="buy",
            entry_type="market", valid_until=date(2024, 12, 31),
        )
        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal, analysis_date=date(2024, 1, 1), start_price=100.0,
            forward_bars=_BARS, config=_CFG, benchmark_code="000300", benchmark_return_pct=1.5,
        )
        self.assertEqual(res["benchmark_code"], "000300")
        self.assertAlmostEqual(res["excess_return_pct"], res["simulated_return_pct"] - 1.5, places=6)


class BenchmarkServiceIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from src.config import Config
        from src.storage import DatabaseManager

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "bench.db")
        os.environ["BACKTEST_EVAL_WINDOW_DAYS"] = "3"
        os.environ["BACKTEST_ENGINE_VERSION"] = "v2"
        # Isolate benchmark from cost.
        os.environ["BACKTEST_COMMISSION_RATE"] = "0"
        os.environ["BACKTEST_STAMP_TAX_RATE"] = "0"
        os.environ["BACKTEST_SLIPPAGE_BP"] = "0"
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self):
        import os

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        for key in (
            "BACKTEST_ENGINE_VERSION", "BACKTEST_COMMISSION_RATE",
            "BACKTEST_STAMP_TAX_RATE", "BACKTEST_SLIPPAGE_BP", "BACKTEST_EVAL_WINDOW_DAYS",
        ):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def test_run_backtest_v2_records_benchmark_and_excess(self):
        import json
        from datetime import datetime

        from src.services.backtest_service import BacktestService
        from src.storage import AnalysisHistory, BacktestResult, StockDaily

        with self.db.get_session() as session:
            session.add(AnalysisHistory(
                query_id="q1", code="600519", name="x", report_type="simple",
                operation_advice="买入", stop_loss=None, take_profit=None,
                created_at=datetime(2024, 1, 1),
                context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-01"}}),
            ))
            # Stock: start 100 -> window-end 105 (+5%).
            session.add(StockDaily(code="600519", date=date(2024, 1, 1), open=100, high=100, low=100, close=100))
            session.add_all([
                StockDaily(code="600519", date=date(2024, 1, 2), open=100, high=103, low=101, close=102),
                StockDaily(code="600519", date=date(2024, 1, 3), open=102, high=105, low=103, close=104),
                StockDaily(code="600519", date=date(2024, 1, 4), open=104, high=106, low=104, close=105),
            ])
            # Benchmark index 000300: start 4000 -> window-end 4080 (+2%).
            session.add(StockDaily(code="000300", date=date(2024, 1, 1), open=4000, high=4000, low=4000, close=4000))
            session.add_all([
                StockDaily(code="000300", date=date(2024, 1, 2), open=4000, high=4030, low=3990, close=4020),
                StockDaily(code="000300", date=date(2024, 1, 3), open=4020, high=4060, low=4010, close=4050),
                StockDaily(code="000300", date=date(2024, 1, 4), open=4050, high=4090, low=4040, close=4080),
            ])
            session.commit()

        BacktestService(self.db).run_backtest(code="600519", force=True, min_age_days=0)

        with self.db.get_session() as session:
            row = session.query(BacktestResult).filter(
                BacktestResult.code == "600519", BacktestResult.eval_status == "completed"
            ).one()
            self.assertEqual(row.benchmark_code, "000300")
            self.assertAlmostEqual(row.benchmark_return_pct, 2.0, places=4)
            self.assertAlmostEqual(row.excess_return_pct, row.simulated_return_pct - 2.0, places=4)


class BenchmarkColumnMigrationTestCase(unittest.TestCase):
    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()

    def test_existing_results_table_gains_benchmark_columns(self):
        import sqlite3
        import tempfile

        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_bench.db"
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
                for col in ("benchmark_code", "benchmark_return_pct", "excess_return_pct"):
                    self.assertIn(col, cols, col)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
