# -*- coding: utf-8 -*-
"""Unit tests for applying quality-policy constraints to a DecisionSignal (workflow C.2)."""

import unittest

from src.schemas.decision_signal import DecisionSignal
from src.schemas.quality_policy import PolicyAction, PolicyMatch, QualityPolicyDecision
from src.services.decision_signal_service import constrain_signal_with_quality_policy


def _decision(*actions, policy_id="p", reason="r"):
    return QualityPolicyDecision(
        matched=[
            PolicyMatch(
                policy_id=policy_id,
                reason=reason,
                actions=[PolicyAction(type=t, params=p) for (t, p) in actions],
            )
        ]
    )


class ConstrainSignalTestCase(unittest.TestCase):
    def _precise_long(self):
        return DecisionSignal(
            code="600519", direction="long", action="buy", entry_type="precise", entry_price=100.0,
            confidence_level="high", stop_loss=90.0, take_profit=120.0,
        )

    def _zone_long(self):
        return DecisionSignal(
            code="600519", direction="long", action="buy", entry_type="zone",
            entry_low=95.0, entry_high=100.0, confidence_level="high",
        )

    def test_empty_decision_leaves_signal_unchanged(self):
        original = self._precise_long()
        out = constrain_signal_with_quality_policy(original, QualityPolicyDecision())
        self.assertEqual(out.entry_type, "precise")
        self.assertEqual(out.entry_price, 100.0)
        self.assertEqual(out.quality_constraints, {})

    def test_prohibit_precise_entry_downgrades_precise_to_none(self):
        out = constrain_signal_with_quality_policy(
            self._precise_long(), _decision(("prohibit_precise_entry", {}), policy_id="quote_degraded")
        )
        self.assertEqual(out.entry_type, "none")
        self.assertIsNone(out.entry_price)
        self.assertIn("quote_degraded", out.quality_constraints.get("policies", []))
        self.assertTrue(out.quality_constraints.get("effects"))

    def test_prohibit_precise_entry_keeps_zone_entry(self):
        out = constrain_signal_with_quality_policy(
            self._zone_long(), _decision(("prohibit_precise_entry", {}))
        )
        self.assertEqual(out.entry_type, "zone")
        self.assertEqual(out.entry_low, 95.0)
        self.assertEqual(out.entry_high, 100.0)

    def test_observation_only_makes_signal_non_executable(self):
        out = constrain_signal_with_quality_policy(
            self._precise_long(), _decision(("observation_only", {}), policy_id="core_degraded")
        )
        self.assertEqual(out.direction, "neutral")
        self.assertEqual(out.action, "watch")
        self.assertEqual(out.entry_type, "none")
        self.assertIsNone(out.entry_price)
        self.assertIsNone(out.entry_low)
        self.assertIsNone(out.entry_high)
        self.assertIsNone(out.position_size_pct)
        self.assertIsNone(out.stop_loss)
        self.assertIsNone(out.take_profit)
        self.assertIn("core_degraded", out.quality_constraints.get("policies", []))

    def test_cap_confidence_lowers_high_to_medium(self):
        out = constrain_signal_with_quality_policy(
            self._precise_long(), _decision(("cap_confidence", {"max_level": "medium"}))
        )
        self.assertEqual(out.confidence_level, "medium")

    def test_cap_confidence_does_not_raise_already_low(self):
        sig = self._precise_long()
        sig.confidence_level = "low"
        out = constrain_signal_with_quality_policy(
            sig, _decision(("cap_confidence", {"max_level": "medium"}))
        )
        self.assertEqual(out.confidence_level, "low")

    def test_observation_only_takes_precedence_over_precise_downgrade(self):
        out = constrain_signal_with_quality_policy(
            self._precise_long(),
            _decision(
                ("prohibit_precise_entry", {}),
                ("observation_only", {}),
            ),
        )
        self.assertEqual(out.direction, "neutral")
        self.assertEqual(out.action, "watch")
        self.assertEqual(out.entry_type, "none")


if __name__ == "__main__":
    unittest.main()
