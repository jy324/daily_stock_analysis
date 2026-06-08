# -*- coding: utf-8 -*-
"""A-share scoring contract tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.services.ashare_scoring_service import AShareScoringService


class AShareScoringServiceTestCase(unittest.TestCase):
    def test_scoring_is_disabled_by_default(self) -> None:
        service = AShareScoringService(SimpleNamespace(ashare_scoring_enabled=False))

        result = service.score_signals({"net_inflow_strength": 0.8}, coverage=1.0)

        self.assertIsNone(result.score)
        self.assertIsNone(result.risk_pressure_score)
        self.assertEqual(result.coverage, 0.0)
        self.assertIn("scoring_disabled", result.warnings)

    def test_low_coverage_suppresses_score(self) -> None:
        service = AShareScoringService(SimpleNamespace(ashare_scoring_enabled=True))

        result = service.score_signals({"net_inflow_strength": 0.8}, coverage=0.59)

        self.assertIsNone(result.score)
        self.assertIsNone(result.risk_pressure_score)
        self.assertEqual(result.coverage, 0.59)
        self.assertIn("coverage_below_threshold", result.warnings)

    def test_scores_only_structured_features(self) -> None:
        service = AShareScoringService(SimpleNamespace(ashare_scoring_enabled=True))

        result = service.score_signals(
            {
                "net_inflow_strength": 0.7,
                "sector_breadth": 0.5,
                "dragon_tiger_risk": 0.8,
                "llm_interpretation": "very bullish",
            },
            coverage=0.9,
        )

        self.assertGreater(result.score, 0)
        self.assertGreater(result.risk_pressure_score, 0)
        self.assertNotIn("llm_interpretation", result.features)
        self.assertEqual(result.features["net_inflow_strength"], 0.7)

    def test_risk_pressure_score_increases_with_risk_features(self) -> None:
        service = AShareScoringService(SimpleNamespace(ashare_scoring_enabled=True))

        low = service.score_signals({"dragon_tiger_risk": 0.1, "unlock_pressure": 0.0}, coverage=1.0)
        high = service.score_signals({"dragon_tiger_risk": 0.8, "unlock_pressure": 0.7}, coverage=1.0)

        self.assertLess(low.risk_pressure_score, high.risk_pressure_score)

    def test_persistence_requires_real_history(self) -> None:
        service = AShareScoringService(SimpleNamespace(ashare_scoring_enabled=True))

        result = service.persistence_score([0.4, 0.6], window=3)

        self.assertIsNone(result.value)
        self.assertEqual(result.window, 3)
        self.assertIn("insufficient_history", result.warnings)


if __name__ == "__main__":
    unittest.main()
