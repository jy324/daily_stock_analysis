# -*- coding: utf-8 -*-
"""Tests for the structured DecisionSignal schema (workflow B.1)."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.schemas.decision_signal import (
    DecisionSignal,
    build_signal_from_analysis_fields,
    direction_from_action,
)


class DirectionFromActionTestCase(unittest.TestCase):
    """The coarse signal direction must stay aligned with the existing
    long-only backtest semantics: bullish -> long, bearish -> short,
    no-view -> neutral. This is the contract workflow B.3 consumes."""

    def test_bullish_actions_map_to_long(self) -> None:
        for action in ("buy", "add", "hold"):
            self.assertEqual(direction_from_action(action), "long", action)

    def test_bearish_actions_map_to_short(self) -> None:
        for action in ("sell", "reduce"):
            self.assertEqual(direction_from_action(action), "short", action)

    def test_no_view_actions_map_to_neutral(self) -> None:
        for action in ("watch", "avoid", "alert"):
            self.assertEqual(direction_from_action(action), "neutral", action)

    def test_missing_or_unknown_action_maps_to_neutral(self) -> None:
        self.assertEqual(direction_from_action(None), "neutral")
        self.assertEqual(direction_from_action("nonsense"), "neutral")


class DecisionSignalModelTestCase(unittest.TestCase):
    def _base(self, **overrides):
        payload = {
            "code": "600519",
            "direction": "long",
            "action": "buy",
            "entry_type": "none",
        }
        payload.update(overrides)
        return payload

    def test_minimal_signal_round_trips(self) -> None:
        signal = DecisionSignal(**self._base())
        self.assertEqual(signal.code, "600519")
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.signal_version, 1)
        self.assertEqual(signal.state, "generated")
        self.assertEqual(signal.source, "llm_structured")
        self.assertEqual(signal.invalidation_conditions, [])
        # JSON round-trip keeps the structured contract intact.
        restored = DecisionSignal.model_validate(signal.model_dump(mode="json"))
        self.assertEqual(restored.code, "600519")

    def test_precise_entry_requires_entry_price(self) -> None:
        DecisionSignal(**self._base(entry_type="precise", entry_price=1680.0))
        with self.assertRaises(ValidationError):
            DecisionSignal(**self._base(entry_type="precise"))

    def test_zone_entry_requires_ordered_bounds(self) -> None:
        DecisionSignal(**self._base(entry_type="zone", entry_low=1600.0, entry_high=1650.0))
        with self.assertRaises(ValidationError):
            DecisionSignal(**self._base(entry_type="zone", entry_low=1650.0, entry_high=1600.0))
        with self.assertRaises(ValidationError):
            DecisionSignal(**self._base(entry_type="zone", entry_low=1600.0))

    def test_confidence_score_bounds(self) -> None:
        DecisionSignal(**self._base(confidence_score=0))
        DecisionSignal(**self._base(confidence_score=100))
        with self.assertRaises(ValidationError):
            DecisionSignal(**self._base(confidence_score=101))

    def test_valid_until_must_not_precede_valid_from(self) -> None:
        DecisionSignal(**self._base(valid_from="2026-06-10", valid_until="2026-06-13"))
        with self.assertRaises(ValidationError):
            DecisionSignal(**self._base(valid_from="2026-06-13", valid_until="2026-06-10"))


class BuildSignalFromAnalysisFieldsTestCase(unittest.TestCase):
    """Deterministic ``normalized_fallback`` generation from legacy fields."""

    def test_bullish_advice_with_single_price_is_precise_long(self) -> None:
        signal = build_signal_from_analysis_fields(
            code="600519",
            operation_advice="买入",
            confidence_level="高",
            ideal_buy=1680.0,
            stop_loss=1600.0,
            take_profit=1800.0,
        )
        self.assertEqual(signal.source, "normalized_fallback")
        self.assertEqual(signal.action, "buy")
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.entry_type, "precise")
        self.assertEqual(signal.entry_price, 1680.0)
        self.assertEqual(signal.stop_loss, 1600.0)
        self.assertEqual(signal.take_profit, 1800.0)
        self.assertEqual(signal.confidence_level, "high")
        self.assertEqual(signal.operation_advice, "买入")

    def test_bullish_advice_with_two_prices_is_zone(self) -> None:
        signal = build_signal_from_analysis_fields(
            code="600519",
            operation_advice="加仓",
            ideal_buy=1680.0,
            secondary_buy=1650.0,
        )
        self.assertEqual(signal.entry_type, "zone")
        self.assertEqual(signal.entry_low, 1650.0)
        self.assertEqual(signal.entry_high, 1680.0)

    def test_bearish_advice_has_no_entry_even_with_prices(self) -> None:
        signal = build_signal_from_analysis_fields(
            code="600519",
            operation_advice="卖出",
            ideal_buy=1680.0,
            stop_loss=1600.0,
        )
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.action, "sell")
        self.assertEqual(signal.entry_type, "none")
        self.assertIsNone(signal.entry_price)
        # Exit levels still pass through for evaluation.
        self.assertEqual(signal.stop_loss, 1600.0)

    def test_ambiguous_advice_is_neutral_no_entry(self) -> None:
        signal = build_signal_from_analysis_fields(
            code="600519",
            operation_advice="观望",
            ideal_buy=1680.0,
        )
        self.assertEqual(signal.direction, "neutral")
        self.assertEqual(signal.entry_type, "none")

    def test_explicit_action_overrides_text_inference(self) -> None:
        signal = build_signal_from_analysis_fields(
            code="600519",
            operation_advice="震荡偏强，可逢低关注",
            action="add",
            ideal_buy=1680.0,
        )
        self.assertEqual(signal.action, "add")
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.entry_type, "precise")


if __name__ == "__main__":
    unittest.main()
