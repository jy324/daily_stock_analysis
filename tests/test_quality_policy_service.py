# -*- coding: utf-8 -*-
"""Tests for the data-quality policy engine (workflow C.1)."""

import os
import tempfile
import unittest

from src.services.quality_policy_service import QualityPolicyService

_POLICY_YAML = """
version: 1
policies:
  - id: quote_degraded_no_precise_entry
    description: quote stale/fallback/failed -> no precise entry
    trigger:
      block_status_in:
        quote: [stale, fallback, fetch_failed]
    actions:
      - type: prohibit_precise_entry
  - id: fundamentals_missing_cap_confidence
    description: fundamentals missing/failed -> cap confidence at medium
    trigger:
      block_status_in:
        fundamentals: [fetch_failed, missing]
    actions:
      - type: cap_confidence
        params:
          max_level: medium
  - id: news_partial_downgrade_event
    description: news missing/partial -> downgrade event signal
    trigger:
      block_status_in:
        news: [missing, partial]
    actions:
      - type: downgrade_event_signal
  - id: core_blocks_observation_only
    description: two or more degraded core blocks means observation only
    trigger:
      min_degraded_core_blocks: 2
    actions:
      - type: observation_only
  - id: premarket_low_score_cap
    description: low overall score in premarket -> cap confidence low
    trigger:
      overall_score_below: 40
      phase_in: [premarket]
    actions:
      - type: cap_confidence
        params:
          max_level: low
"""


def _overview(blocks=None, overall_score=None):
    return {
        "blocks": [{"key": k, "status": s} for k, s in (blocks or {}).items()],
        "data_quality": {"overall_score": overall_score},
    }


class QualityPolicyServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.policy_file = os.path.join(self._tmp.name, "policies.yaml")
        with open(self.policy_file, "w", encoding="utf-8") as fh:
            fh.write(_POLICY_YAML)
        self.service = QualityPolicyService(policy_file=self.policy_file)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_quote_degraded_prohibits_precise_entry(self):
        decision = self.service.evaluate(_overview(blocks={"quote": "stale"}))
        self.assertTrue(decision.prohibit_precise_entry)
        self.assertIn("quote_degraded_no_precise_entry", decision.matched_policy_ids)
        self.assertTrue(decision.reasons)

    def test_healthy_quote_matches_nothing(self):
        decision = self.service.evaluate(_overview(blocks={"quote": "available"}))
        self.assertTrue(decision.is_empty)
        self.assertFalse(decision.prohibit_precise_entry)

    def test_fundamentals_missing_caps_confidence_medium(self):
        decision = self.service.evaluate(_overview(blocks={"fundamentals": "missing"}))
        self.assertEqual(decision.confidence_cap, "medium")

    def test_news_partial_downgrades_event_signal(self):
        decision = self.service.evaluate(_overview(blocks={"news": "partial"}))
        self.assertTrue(decision.downgrade_event_signal)

    def test_two_degraded_core_blocks_trigger_observation_only(self):
        decision = self.service.evaluate(
            _overview(blocks={"quote": "stale", "daily_bars": "fetch_failed", "technical": "available"})
        )
        self.assertTrue(decision.observation_only)

    def test_single_degraded_core_block_does_not_trigger_observation_only(self):
        decision = self.service.evaluate(_overview(blocks={"quote": "stale", "daily_bars": "available"}))
        self.assertFalse(decision.observation_only)

    def test_policies_stack(self):
        decision = self.service.evaluate(
            _overview(blocks={"quote": "fallback", "fundamentals": "fetch_failed"})
        )
        self.assertTrue(decision.prohibit_precise_entry)
        self.assertEqual(decision.confidence_cap, "medium")
        self.assertEqual(len(decision.matched_policy_ids), 2)

    def test_tightest_confidence_cap_wins(self):
        # low-score premarket cap (low) + fundamentals cap (medium) -> low is tighter.
        decision = self.service.evaluate(
            _overview(blocks={"fundamentals": "missing"}, overall_score=30),
            phase="premarket",
        )
        self.assertEqual(decision.confidence_cap, "low")

    def test_phase_gate_blocks_when_phase_differs(self):
        decision = self.service.evaluate(
            _overview(blocks={}, overall_score=30),
            phase="intraday",
        )
        # premarket-only policy must not fire intraday.
        self.assertNotIn("premarket_low_score_cap", decision.matched_policy_ids)

    def test_missing_overall_score_does_not_trigger_score_policy(self):
        decision = self.service.evaluate(_overview(blocks={}, overall_score=None), phase="premarket")
        self.assertNotIn("premarket_low_score_cap", decision.matched_policy_ids)

    def test_missing_policy_file_disables_all_policies(self):
        service = QualityPolicyService(policy_file=os.path.join(self._tmp.name, "nope.yaml"))
        decision = service.evaluate(_overview(blocks={"quote": "stale"}))
        self.assertTrue(decision.is_empty)

    def test_corrupt_policy_file_disables_all_policies(self):
        bad = os.path.join(self._tmp.name, "bad.yaml")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("version: 1\npolicies: [this is : not : valid\n")
        service = QualityPolicyService(policy_file=bad)
        decision = service.evaluate(_overview(blocks={"quote": "stale"}))
        self.assertTrue(decision.is_empty)

    def test_decision_to_dict_round_trip_is_json_safe(self):
        decision = self.service.evaluate(_overview(blocks={"quote": "stale"}))
        payload = decision.to_dict()
        self.assertIn("matched", payload)
        self.assertIn("action_types", payload)
        import json

        json.dumps(payload)  # must not raise


class ShippedQualityPolicyConfigTestCase(unittest.TestCase):
    """The repo's default policy file must load and behave as documented."""

    def test_default_config_prohibits_precise_entry_on_stale_quote(self):
        service = QualityPolicyService(policy_file="config/quality_policies.yaml")
        decision = service.evaluate(_overview(blocks={"quote": "stale"}))
        self.assertTrue(decision.prohibit_precise_entry)


if __name__ == "__main__":
    unittest.main()
