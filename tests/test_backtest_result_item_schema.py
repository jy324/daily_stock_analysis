# -*- coding: utf-8 -*-
"""The v2 result fields must survive BacktestResultItem validation (workflow D.1).

Pydantic drops undeclared extras by default, so a field that ``_result_to_dict``
emits but the schema does not declare would silently never reach API clients.
"""

import unittest

from api.v1.schemas.backtest import BacktestResultItem

_V2_FIELDS = (
    "signal_based",
    "cost_pct",
    "benchmark_code",
    "benchmark_return_pct",
    "excess_return_pct",
    "unfillable",
)


class BacktestResultItemV2FieldsTestCase(unittest.TestCase):
    def test_v2_fields_survive_validation(self):
        payload = {
            "analysis_history_id": 1,
            "code": "600519",
            "eval_window_days": 10,
            "engine_version": "v2",
            "eval_status": "completed",
            "signal_based": True,
            "cost_pct": 0.15,
            "benchmark_code": "000300",
            "benchmark_return_pct": 2.0,
            "excess_return_pct": 3.0,
            "unfillable": False,
        }
        item = BacktestResultItem.model_validate(payload)
        dumped = item.model_dump()
        for field in _V2_FIELDS:
            self.assertIn(field, dumped, field)
        self.assertEqual(dumped["signal_based"], True)
        self.assertEqual(dumped["cost_pct"], 0.15)
        self.assertEqual(dumped["benchmark_code"], "000300")
        self.assertEqual(dumped["benchmark_return_pct"], 2.0)
        self.assertEqual(dumped["excess_return_pct"], 3.0)
        self.assertEqual(dumped["unfillable"], False)

    def test_v1_payload_leaves_v2_fields_none(self):
        payload = {
            "analysis_history_id": 2,
            "code": "600519",
            "eval_window_days": 10,
            "engine_version": "v1",
            "eval_status": "completed",
        }
        dumped = BacktestResultItem.model_validate(payload).model_dump()
        for field in _V2_FIELDS:
            self.assertIsNone(dumped[field], field)


if __name__ == "__main__":
    unittest.main()
