# -*- coding: utf-8 -*-
"""Integration: run_backtest consumes a structured DecisionSignal when present (workflow B.3)."""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime

from src.config import Config
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal
from src.services.backtest_service import BacktestService
from src.storage import AnalysisHistory, BacktestResult, DatabaseManager, StockDaily


class BacktestSignalIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "test_signal_bt.db")
        os.environ["BACKTEST_EVAL_WINDOW_DAYS"] = "3"
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _seed_analysis(self, *, query_id: str, advice: str = "买入") -> int:
        with self.db.get_session() as session:
            row = AnalysisHistory(
                query_id=query_id,
                code="600519",
                name="贵州茅台",
                report_type="simple",
                sentiment_score=70,
                operation_advice=advice,
                trend_prediction="看多",
                analysis_summary="t",
                stop_loss=95.0,
                take_profit=130.0,
                created_at=datetime(2024, 1, 1),
                context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-01"}}),
            )
            session.add(row)
            session.add(StockDaily(code="600519", date=date(2024, 1, 1), open=100.0, high=100.0, low=100.0, close=100.0))
            session.add_all([
                StockDaily(code="600519", date=date(2024, 1, 2), open=100.0, high=103.0, low=101.0, close=102.0),
                StockDaily(code="600519", date=date(2024, 1, 3), open=102.0, high=105.0, low=103.0, close=104.0),
                StockDaily(code="600519", date=date(2024, 1, 4), open=104.0, high=106.0, low=104.0, close=105.0),
            ])
            session.commit()
            return row.id

    def _result_for(self, analysis_id: int) -> BacktestResult:
        with self.db.get_session() as session:
            return session.query(BacktestResult).filter(
                BacktestResult.analysis_history_id == analysis_id
            ).one()

    def test_run_backtest_uses_signal_path_when_signal_exists(self) -> None:
        analysis_id = self._seed_analysis(query_id="q-sig")
        DecisionSignalRepository(self.db).save_signal(
            DecisionSignal(
                code="600519",
                analysis_history_id=analysis_id,
                direction="long",
                action="buy",
                entry_type="market",
                stop_loss=95.0,
                take_profit=130.0,
                valid_until=date(2024, 12, 31),
            )
        )

        out = BacktestService(self.db).run_backtest(code="600519", force=True, min_age_days=0)
        self.assertGreaterEqual(out["saved"], 1)

        result = self._result_for(analysis_id)
        self.assertTrue(result.signal_based)
        self.assertEqual(result.eval_status, "completed")
        self.assertEqual(result.position_recommendation, "long")
        # Market fill at day-2 open, held to window-end close.
        self.assertEqual(result.simulated_entry_price, 100.0)
        self.assertEqual(result.simulated_return_pct, 5.0)

    def test_run_backtest_falls_back_to_keyword_when_no_signal(self) -> None:
        analysis_id = self._seed_analysis(query_id="q-nosig")

        BacktestService(self.db).run_backtest(code="600519", force=True, min_age_days=0)

        result = self._result_for(analysis_id)
        self.assertFalse(result.signal_based)
        self.assertEqual(result.eval_status, "completed")
        self.assertEqual(result.position_recommendation, "long")


class BacktestSignalColumnMigrationTestCase(unittest.TestCase):
    """An existing backtest_results table must gain the signal_based column."""

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_existing_table_gains_signal_based_defaulting_false(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_bt.db"
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
                conn.execute(
                    "INSERT INTO backtest_results (analysis_history_id, code) VALUES (1, '600519')"
                )
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            conn = sqlite3.connect(db_path)
            try:
                cols = {str(r[1]) for r in conn.execute('PRAGMA table_info("backtest_results")').fetchall()}
                self.assertIn("signal_based", cols)
                value = conn.execute("SELECT signal_based FROM backtest_results WHERE id = 1").fetchone()[0]
                self.assertEqual(value, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
