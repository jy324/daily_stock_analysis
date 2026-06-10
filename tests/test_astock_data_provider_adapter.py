# -*- coding: utf-8 -*-
"""Adapter tests for the real astock_data facade contract."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from data_provider.intelligence.astock_data_provider import create_astock_data_provider


class FakeAStockDataClient:
    used_from_defaults = False

    @classmethod
    def from_defaults(cls):
        cls.used_from_defaults = True
        return cls()

    def get_stock_flow_history(self, code, *, trade_date=None, lookback=120):
        return {
            "data": [
                {"code": "000001", "trade_date": "2026-06-09", "value": "wrong"},
                {"code": code, "trade_date": "2026-06-07", "value": 7},
                {"code": code, "trade_date": "2026-06-09", "value": 9},
                {"code": code, "trade_date": "2026-06-08", "value": 8},
            ],
            "meta": {
                "provider": "fake",
                "capability": "stock_flow_history",
                "endpoint": "fixture",
                "status": "ok",
                "as_of": "2026-06-09T15:00:00+08:00",
            },
            "coverage": {"provider_count": 4},
        }

    def get_lockup_events(self, code, *, trade_date=None, limit=None):
        return {
            "data": [
                {"code": code, "unlock_date": "2026-06-10"},
                {"code": "000001", "unlock_date": "2026-06-10"},
            ],
            "meta": {
                "provider": "fake",
                "capability": "lockup_events",
                "endpoint": "fixture",
                "status": "ok",
                "as_of": "2026-06-09T15:00:00+08:00",
            },
        }


class AStockDataProviderAdapterTestCase(unittest.TestCase):
    def test_adapter_uses_public_facade_and_applies_lookback(self) -> None:
        FakeAStockDataClient.used_from_defaults = False
        module = types.SimpleNamespace(AStockDataClient=FakeAStockDataClient)

        with patch.dict(sys.modules, {"astock_data": module}):
            provider = create_astock_data_provider()
            result = provider.fetch(
                "capital_flow_daily",
                {"code": "600519", "trade_date": "2026-06-09", "lookback": 2},
            )

        self.assertEqual(result.status, "ok")
        self.assertTrue(FakeAStockDataClient.used_from_defaults)
        self.assertEqual([row["value"] for row in result.data], [9, 8])
        self.assertEqual(result.coverage["filtered_code"], "600519")
        self.assertEqual(result.coverage["requested_lookback"], 2)

    def test_adapter_filters_lockup_rows_to_requested_stock(self) -> None:
        module = types.SimpleNamespace(AStockDataClient=FakeAStockDataClient)

        with patch.dict(sys.modules, {"astock_data": module}):
            provider = create_astock_data_provider()
            result = provider.fetch(
                "lockup",
                {"code": "600519", "trade_date": "2026-06-09", "limit": 100},
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0]["code"], "600519")


if __name__ == "__main__":
    unittest.main()
