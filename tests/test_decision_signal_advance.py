# -*- coding: utf-8 -*-
"""Tests for DecisionSignal daily advancement logic (workflow B.2)."""

from __future__ import annotations

import unittest
from datetime import date

from src.schemas.decision_signal import DecisionSignal
from src.services.decision_signal_service import advance_signal_for_day


def _ohlc(o, h, low, c):
    return {"open": o, "high": h, "low": low, "close": c}


class AdvanceSignalForDayTestCase(unittest.TestCase):
    def _long(self, **overrides) -> DecisionSignal:
        payload = {
            "code": "600519",
            "direction": "long",
            "action": "buy",
            "entry_type": "precise",
            "entry_price": 1680.0,
            "stop_loss": 1600.0,
            "take_profit": 1800.0,
            "valid_until": date(2026, 6, 30),
            "state": "waiting_entry",
        }
        payload.update(overrides)
        return DecisionSignal(**payload)

    def test_waiting_entry_fills_when_price_reaches_entry(self) -> None:
        adv = advance_signal_for_day(self._long(), day=date(2026, 6, 11), ohlc=_ohlc(1700, 1705, 1675, 1690))
        self.assertEqual(adv.to_state, "entered")
        self.assertEqual(adv.entered_price, 1680.0)  # limit fill at entry level

    def test_waiting_entry_gap_down_fills_at_open(self) -> None:
        adv = advance_signal_for_day(self._long(), day=date(2026, 6, 11), ohlc=_ohlc(1650, 1660, 1640, 1655))
        self.assertEqual(adv.to_state, "entered")
        self.assertEqual(adv.entered_price, 1650.0)  # gapped below entry -> fill at open

    def test_waiting_entry_no_touch_stays(self) -> None:
        adv = advance_signal_for_day(self._long(), day=date(2026, 6, 11), ohlc=_ohlc(1720, 1740, 1700, 1730))
        self.assertIsNone(adv.to_state)

    def test_entered_stop_hit(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="entered"), day=date(2026, 6, 12), ohlc=_ohlc(1650, 1660, 1590, 1600)
        )
        self.assertEqual(adv.to_state, "stop_hit")
        self.assertEqual(adv.closed_price, 1600.0)

    def test_entered_target_hit(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="entered"), day=date(2026, 6, 12), ohlc=_ohlc(1750, 1810, 1740, 1800)
        )
        self.assertEqual(adv.to_state, "target_hit")
        self.assertEqual(adv.closed_price, 1800.0)

    def test_entered_same_day_both_is_stop_priority(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="entered"), day=date(2026, 6, 12), ohlc=_ohlc(1700, 1820, 1590, 1700)
        )
        self.assertEqual(adv.to_state, "stop_hit")
        self.assertEqual(adv.closed_price, 1600.0)

    def test_entered_gap_below_stop_closes_at_open(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="entered"), day=date(2026, 6, 12), ohlc=_ohlc(1550, 1560, 1540, 1545)
        )
        self.assertEqual(adv.to_state, "stop_hit")
        self.assertEqual(adv.closed_price, 1550.0)  # gapped below stop -> close at open

    def test_waiting_entry_expires_after_validity(self) -> None:
        adv = advance_signal_for_day(self._long(), day=date(2026, 7, 1), ohlc=_ohlc(1700, 1710, 1690, 1705))
        self.assertEqual(adv.to_state, "expired")

    def test_entered_expires_after_validity_closes_at_close(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="entered"), day=date(2026, 7, 1), ohlc=_ohlc(1700, 1710, 1690, 1705)
        )
        self.assertEqual(adv.to_state, "expired")
        self.assertEqual(adv.closed_price, 1705.0)

    def test_halt_day_no_change(self) -> None:
        adv = advance_signal_for_day(self._long(state="entered"), day=date(2026, 6, 12), ohlc=None)
        self.assertIsNone(adv.to_state)

    def test_market_entry_enters_at_open(self) -> None:
        sig = self._long(entry_type="market", entry_price=None, state="generated")
        adv = advance_signal_for_day(sig, day=date(2026, 6, 11), ohlc=_ohlc(1700, 1710, 1690, 1705))
        self.assertEqual(adv.to_state, "entered")
        self.assertEqual(adv.entered_price, 1700.0)

    def test_neutral_signal_only_expires(self) -> None:
        sig = DecisionSignal(code="600519", direction="neutral", entry_type="none", valid_until=date(2026, 6, 30))
        # before expiry: nothing happens
        self.assertIsNone(advance_signal_for_day(sig, day=date(2026, 6, 11), ohlc=_ohlc(10, 11, 9, 10)).to_state)
        # after expiry
        self.assertEqual(
            advance_signal_for_day(sig, day=date(2026, 7, 1), ohlc=_ohlc(10, 11, 9, 10)).to_state, "expired"
        )

    def test_terminal_state_no_change(self) -> None:
        adv = advance_signal_for_day(
            self._long(state="stop_hit"), day=date(2026, 6, 12), ohlc=_ohlc(1700, 1710, 1690, 1705)
        )
        self.assertIsNone(adv.to_state)


if __name__ == "__main__":
    unittest.main()
