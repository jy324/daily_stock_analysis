# -*- coding: utf-8 -*-
"""Tests for AnalysisHistory version-attribution columns (workflow D.2)."""

import sqlite3
import tempfile
import unittest

from src.analyzer import AnalysisResult
from src.storage import DatabaseManager


def _result():
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=80,
        trend_prediction="看多",
        operation_advice="买入",
    )
    result.model_used = "gemini/gemini-3.1-pro"
    result.prompt_version_hash = "abc123def4567890"
    result.strategy_version = "v2"
    return result


class SaveAttributionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_save_persists_attribution_columns(self):
        n = self.db.save_analysis_history(
            _result(), query_id="q1", report_type="simple", news_content=None, context_snapshot=None
        )
        self.assertEqual(n, 1)

        rows = self.db.get_analysis_history(code="600519", limit=1)
        row = rows[0]
        self.assertEqual(row.model_used, "gemini/gemini-3.1-pro")
        self.assertEqual(row.prompt_version_hash, "abc123def4567890")
        self.assertEqual(row.strategy_version, "v2")

    def test_to_dict_exposes_attribution(self):
        self.db.save_analysis_history(
            _result(), query_id="q1", report_type="simple", news_content=None, context_snapshot=None
        )
        row = self.db.get_analysis_history(code="600519", limit=1)[0]
        payload = row.to_dict()
        self.assertEqual(payload["model_used"], "gemini/gemini-3.1-pro")
        self.assertEqual(payload["prompt_version_hash"], "abc123def4567890")
        self.assertEqual(payload["strategy_version"], "v2")

    def test_missing_attribution_persists_as_null(self):
        result = AnalysisResult(
            code="000001", name="平安银行", sentiment_score=50, trend_prediction="震荡", operation_advice="持有"
        )
        # model_used/prompt_version_hash/strategy_version left at defaults (None)
        self.db.save_analysis_history(
            result, query_id="q2", report_type="simple", news_content=None, context_snapshot=None
        )
        row = self.db.get_analysis_history(code="000001", limit=1)[0]
        self.assertIsNone(row.model_used)
        self.assertIsNone(row.prompt_version_hash)
        self.assertIsNone(row.strategy_version)


class AttributionMigrationTestCase(unittest.TestCase):
    """An existing analysis_history table must gain the attribution columns."""

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_existing_table_gains_columns_defaulting_null(self):
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/legacy_hist.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE analysis_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code VARCHAR(10) NOT NULL,
                        created_at DATETIME
                    )
                    """
                )
                conn.execute("INSERT INTO analysis_history (code) VALUES ('600519')")
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            conn = sqlite3.connect(db_path)
            try:
                cols = {str(r[1]) for r in conn.execute('PRAGMA table_info("analysis_history")').fetchall()}
                for col in ("model_used", "prompt_version_hash", "strategy_version"):
                    self.assertIn(col, cols, col)
                values = conn.execute(
                    "SELECT model_used, prompt_version_hash, strategy_version FROM analysis_history WHERE id = 1"
                ).fetchone()
                self.assertEqual(values, (None, None, None))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
