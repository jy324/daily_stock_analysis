# -*- coding: utf-8 -*-
"""Tests for backtest evaluation driven by a structured DecisionSignal (workflow B.3)."""

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


def _bars(start: date, rows):
    """rows: list of (open, high, low, close)."""
    return [
        Bar(date=start + timedelta(days=i + 1), open=o, high=h, low=lo, close=c)
        for i, (o, h, lo, c) in enumerate(rows)
    ]


class EvaluateFromDecisionSignalTestCase(unittest.TestCase):
    def test_market_long_enters_at_first_open_and_holds_to_window_end(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="buy",
            entry_type="market",
            stop_loss=95.0,
            take_profit=110.0,
            valid_until=date(2024, 12, 31),
        )
        bars = _bars(date(2024, 1, 1), [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["eval_status"], "completed")
        self.assertTrue(res["signal_based"])
        self.assertEqual(res["position_recommendation"], "long")
        self.assertEqual(res["direction_expected"], "up")
        # Market fill at the first forward bar's open, held to window-end close.
        self.assertEqual(res["simulated_entry_price"], 100.0)
        self.assertEqual(res["simulated_exit_price"], 105.0)
        self.assertEqual(res["simulated_return_pct"], 5.0)
        self.assertEqual(res["stock_return_pct"], 5.0)
        self.assertEqual(res["outcome"], "win")
        self.assertTrue(res["direction_correct"])


    def test_zone_entry_not_triggered_is_not_entered_with_zero_pnl(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="buy",
            entry_type="zone",
            entry_low=90.0,
            entry_high=92.0,
            valid_until=date(2024, 12, 31),
        )
        # Lows never reach the 92 zone top, so the entry never fills.
        bars = _bars(date(2024, 1, 1), [(99, 100, 96, 99), (100, 101, 97, 100), (101, 102, 98, 101)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["eval_status"], "completed")
        self.assertFalse(res["entered"])
        self.assertEqual(res["first_hit"], "not_entered")
        self.assertIsNone(res["simulated_entry_price"])
        self.assertEqual(res["simulated_return_pct"], 0.0)
        # The directional call is still scored on the underlying stock move.
        self.assertEqual(res["stock_return_pct"], 1.0)
        self.assertEqual(res["position_recommendation"], "long")

    def test_zone_entry_triggers_then_stop_hit(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="buy",
            entry_type="zone",
            entry_low=95.0,
            entry_high=97.0,
            stop_loss=90.0,
            take_profit=120.0,
            valid_until=date(2024, 12, 31),
        )
        bars = _bars(
            date(2024, 1, 1),
            [(100, 101, 99, 100), (98, 99, 96, 97), (96, 97, 89, 90)],
        )

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertTrue(res["entered"])
        self.assertEqual(res["simulated_entry_price"], 97.0)  # filled at zone top on day 2
        self.assertEqual(res["simulated_exit_price"], 90.0)  # stop on day 3
        self.assertEqual(res["simulated_exit_reason"], "stop_loss")
        self.assertEqual(res["first_hit"], "stop_loss")
        self.assertEqual(res["first_hit_trading_days"], 3)
        self.assertTrue(res["hit_stop_loss"])
        self.assertAlmostEqual(res["simulated_return_pct"], (90 - 97) / 97 * 100, places=6)

    def test_short_signal_is_cash_with_zero_pnl(self):
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="short",
            action="sell",
            entry_type="none",
        )
        bars = _bars(date(2024, 1, 1), [(100, 101, 95, 96), (96, 97, 92, 93), (93, 94, 89, 90)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["direction_expected"], "down")
        self.assertEqual(res["simulated_return_pct"], 0.0)
        self.assertEqual(res["first_hit"], "not_applicable")
        self.assertFalse(res["entered"])
        # Stock fell 10%, a down call -> win.
        self.assertEqual(res["outcome"], "win")

    def test_neutral_signal_is_flat_cash(self):
        cfg = EvaluationConfig(eval_window_days=2, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="neutral",
            action="watch",
            entry_type="none",
        )
        bars = _bars(date(2024, 1, 1), [(100, 101, 99, 100), (100, 101, 99, 100)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["direction_expected"], "flat")
        self.assertEqual(res["position_recommendation"], "cash")

    def test_hold_action_maps_to_not_down(self):
        cfg = EvaluationConfig(eval_window_days=2, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="hold",
            entry_type="none",
        )
        bars = _bars(date(2024, 1, 1), [(100, 101, 99, 100), (100, 101, 99, 100)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["direction_expected"], "not_down")

    def test_insufficient_forward_bars(self):
        cfg = EvaluationConfig(eval_window_days=5, neutral_band_pct=2.0)
        signal = DecisionSignal(
            code="600519", analysis_history_id=1, direction="long", action="buy", entry_type="market"
        )
        bars = _bars(date(2024, 1, 1), [(100, 101, 99, 100), (100, 101, 99, 100)])

        res = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(res["eval_status"], "insufficient_data")
        self.assertTrue(res["signal_based"])

    def test_dual_path_market_entry_matches_keyword_path(self):
        """A market signal with no targets hit reproduces the keyword path's P&L."""
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        rows = [(100, 103, 101, 102), (102, 105, 103, 104), (104, 106, 104, 105)]
        bars = _bars(date(2024, 1, 1), rows)

        keyword = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            stop_loss=95.0,
            take_profit=110.0,
            config=cfg,
        )
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="buy",
            entry_type="market",
            stop_loss=95.0,
            take_profit=110.0,
            valid_until=date(2024, 12, 31),
        )
        signal_based = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        self.assertEqual(keyword["stock_return_pct"], signal_based["stock_return_pct"])
        self.assertEqual(keyword["simulated_entry_price"], signal_based["simulated_entry_price"])
        self.assertEqual(keyword["simulated_return_pct"], signal_based["simulated_return_pct"])
        self.assertFalse(keyword.get("signal_based", False))
        self.assertTrue(signal_based["signal_based"])

    def test_dual_path_diverges_when_limit_entry_never_fills(self):
        """Explicit divergence: keyword assumes entry at start; a precise limit may never fill."""
        cfg = EvaluationConfig(eval_window_days=3, neutral_band_pct=2.0)
        rows = [(100, 103, 100, 102), (102, 105, 102, 104), (104, 106, 104, 105)]
        bars = _bars(date(2024, 1, 1), rows)

        keyword = BacktestEngine.evaluate_single(
            operation_advice="买入",
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            stop_loss=70.0,
            take_profit=130.0,
            config=cfg,
        )
        signal = DecisionSignal(
            code="600519",
            analysis_history_id=1,
            direction="long",
            action="buy",
            entry_type="precise",
            entry_price=80.0,  # market never drops this low
            stop_loss=70.0,
            take_profit=130.0,
            valid_until=date(2024, 12, 31),
        )
        signal_based = BacktestEngine.evaluate_from_decision_signal(
            signal=signal,
            analysis_date=date(2024, 1, 1),
            start_price=100.0,
            forward_bars=bars,
            config=cfg,
        )

        # Same underlying stock move, but different realized P&L: keyword "enters",
        # the unfilled limit does not.
        self.assertEqual(keyword["stock_return_pct"], signal_based["stock_return_pct"])
        self.assertGreater(keyword["simulated_return_pct"], 0.0)
        self.assertEqual(signal_based["simulated_return_pct"], 0.0)
        self.assertFalse(signal_based["entered"])


if __name__ == "__main__":
    unittest.main()
