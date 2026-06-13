# -*- coding: utf-8 -*-
"""Tests for backtest performance attribution by model/prompt/strategy (workflow D.3)."""

import os
import tempfile
import unittest
from datetime import date, datetime

from src.config import Config
from src.services.backtest_service import BacktestService
from src.storage import AnalysisHistory, BacktestResult, DatabaseManager


class BacktestAttributionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "attribution.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.service = BacktestService(self.db)
        self._seed()

    def tearDown(self):
        DatabaseManager.reset_instance()
        self._tmp.cleanup()

    def _seed(self):
        with self.db.get_session() as session:
            specs = [
                # (id, model_used, strategy_version, prompt_version_hash, eval_window_days, outcome, sim_return)
                ("m1", "s1", "p1", 10, "win", 10.0),
                ("m2", "s1", "p2", 10, "loss", -5.0),
                (None, None, None, 10, "win", 3.0),  # unknown attribution
                ("m1", "s1", "p1", 30, "loss", -20.0),
            ]
            for i, (model, strat, prompt, window, outcome, ret) in enumerate(specs, start=1):
                session.add(
                    AnalysisHistory(
                        id=i, query_id=f"q{i}", code="600519", name="x",
                        report_type="simple", operation_advice="买入",
                        model_used=model, strategy_version=strat, prompt_version_hash=prompt,
                        created_at=datetime(2024, 1, 1),
                    )
                )
                session.add(
                    BacktestResult(
                        analysis_history_id=i, code="600519", analysis_date=date(2024, 1, 1),
                        eval_window_days=window, engine_version="v1", eval_status="completed",
                        operation_advice="买入", position_recommendation="long",
                        outcome=outcome, direction_correct=(outcome == "win"),
                        stock_return_pct=ret, simulated_return_pct=ret,
                    )
                )
            session.commit()

    def test_group_by_model(self):
        result = self.service.get_performance_by_attribution("model")
        self.assertEqual(result["dimension"], "model")
        groups = {g["key"]: g for g in result["groups"]}
        self.assertEqual(set(groups), {"m1", "m2", "unknown"})
        self.assertEqual(groups["m1"]["total_evaluations"], 1)
        self.assertEqual(groups["m1"]["win_count"], 1)
        self.assertEqual(groups["m1"]["eval_window_days"], 10)
        self.assertEqual(groups["m2"]["loss_count"], 1)
        self.assertEqual(groups["unknown"]["win_count"], 1)

    def test_default_eval_window_does_not_mix_multiple_windows(self):
        result = self.service.get_performance_by_attribution("model")
        groups = {g["key"]: g for g in result["groups"]}

        self.assertEqual(groups["m1"]["eval_window_days"], 10)
        self.assertEqual(groups["m1"]["total_evaluations"], 1)
        self.assertEqual(groups["m1"]["win_count"], 1)

        result_30d = self.service.get_performance_by_attribution("model", eval_window_days=30)
        groups_30d = {g["key"]: g for g in result_30d["groups"]}
        self.assertEqual(set(groups_30d), {"m1"})
        self.assertEqual(groups_30d["m1"]["eval_window_days"], 30)
        self.assertEqual(groups_30d["m1"]["total_evaluations"], 1)
        self.assertEqual(groups_30d["m1"]["loss_count"], 1)

    def test_group_by_strategy_aggregates(self):
        result = self.service.get_performance_by_attribution("strategy")
        groups = {g["key"]: g for g in result["groups"]}
        self.assertEqual(set(groups), {"s1", "unknown"})
        # s1 spans m1 (win) + m2 (loss) -> 2 evaluations.
        self.assertEqual(groups["s1"]["total_evaluations"], 2)
        self.assertEqual(groups["s1"]["win_count"], 1)
        self.assertEqual(groups["s1"]["loss_count"], 1)

    def test_group_by_prompt(self):
        result = self.service.get_performance_by_attribution("prompt")
        groups = {g["key"]: g for g in result["groups"]}
        self.assertEqual(set(groups), {"p1", "p2", "unknown"})

    def test_invalid_dimension_raises(self):
        with self.assertRaises(ValueError):
            self.service.get_performance_by_attribution("sector")

    def test_api_endpoint_returns_groups(self):
        from pathlib import Path

        from fastapi.testclient import TestClient

        from api.app import create_app

        app = create_app(static_dir=Path(self._tmp.name))
        client = TestClient(app)

        resp = client.get("/api/v1/backtest/performance/by/model")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["dimension"], "model")
        keys = {g["key"] for g in body["groups"]}
        self.assertEqual(keys, {"m1", "m2", "unknown"})

        # Unknown dimension is rejected by the path enum (422).
        self.assertEqual(client.get("/api/v1/backtest/performance/by/sector").status_code, 422)


if __name__ == "__main__":
    unittest.main()
