# -*- coding: utf-8 -*-
"""Tests for the daily OHLC provider adapter used by signal advancement (B.2)."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.services.decision_signal_service import build_daily_ohlc_provider


class _FakeFetcher:
    def __init__(self, frame):
        self._frame = frame
        self.calls = []

    def get_daily_data(self, code, days=5):
        self.calls.append((code, days))
        return self._frame, "fake"


class BuildDailyOhlcProviderTestCase(unittest.TestCase):
    def test_maps_latest_bar_to_ohlc(self) -> None:
        frame = pd.DataFrame(
            [
                {"date": "2026-06-10", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
                {"date": "2026-06-11", "open": 1700, "high": 1705, "low": 1675, "close": 1690},
            ]
        )
        provider = build_daily_ohlc_provider(_FakeFetcher(frame))
        bar = provider("600519", date(2026, 6, 11))
        self.assertEqual(bar, {"open": 1700.0, "high": 1705.0, "low": 1675.0, "close": 1690.0})

    def test_empty_frame_returns_none(self) -> None:
        provider = build_daily_ohlc_provider(_FakeFetcher(pd.DataFrame()))
        self.assertIsNone(provider("600519", date(2026, 6, 11)))

    def test_none_frame_returns_none(self) -> None:
        provider = build_daily_ohlc_provider(_FakeFetcher(None))
        self.assertIsNone(provider("600519", date(2026, 6, 11)))


if __name__ == "__main__":
    unittest.main()
