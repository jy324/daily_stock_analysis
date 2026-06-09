# -*- coding: utf-8 -*-
"""A-share risk event aggregation contract tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from data_provider.intelligence.base import AShareProviderUnavailable
from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareSourceMetadata
from src.services.ashare_intelligence_service import AShareIntelligenceService


def _result(capability: str, data, status: str = "ok") -> AShareIntelligenceResult:
    return AShareIntelligenceResult(
        capability=capability,
        provider="fake",
        status=status,
        data=data,
        source=AShareSourceMetadata(
            provider="fake",
            status=status,
            as_of="2026-06-08T10:30:00+08:00",
        ),
        coverage={"coverage_ratio": 1.0 if status == "ok" else 0.0},
        cache_hit=False,
    )


class FakeManager:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get_capability(self, capability, **kwargs):
        self.calls.append((capability, kwargs))
        result = self.results[capability]
        if isinstance(result, Exception):
            raise result
        return result


class AShareRiskEventsServiceTestCase(unittest.TestCase):
    def test_risk_events_normalize_and_dedupe_structured_events(self) -> None:
        manager = FakeManager(
            {
                "announcements": _result(
                    "announcements",
                    [
                        {
                            "announcement_id": "ann-1",
                            "date": "2026-06-08",
                            "title": "董事会公告",
                            "url": "https://example.com/a#fragment",
                        },
                        {
                            "id": "ann-1",
                            "date": "2026-06-08",
                            "title": "董事会公告",
                            "url": "https://example.com/a",
                        },
                    ],
                ),
                "lockup": _result(
                    "lockup",
                    [
                        {"code": "000001", "date": "2026-06-09", "title": "其他公司解禁"},
                        {"code": "600519", "date": "2026-06-09", "title": "限售股解禁", "unlock_shares": "100万股"},
                    ],
                ),
                "dragon_tiger_stock": _result(
                    "dragon_tiger_stock",
                    [{"trade_date": "2026-06-08", "reason": "日涨幅偏离值达7%"}],
                ),
            }
        )
        service = AShareIntelligenceService(SimpleNamespace(ashare_intelligence_enabled=True))

        result = service.get_risk_events(
            code="600519",
            trade_date="2026-06-08",
            lookback=30,
            manager=manager,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.capability, "risk_events")
        events = result.data["events"]
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["event_type"], "announcement")
        self.assertEqual(events[0]["normalized_url"], "https://example.com/a")
        self.assertEqual(events[1]["event_type"], "lockup_expiry")
        self.assertTrue(all(event["code"] == "600519" for event in events))
        self.assertEqual(events[2]["event_type"], "dragon_tiger")
        self.assertEqual(result.coverage["covered_count"], 3)
        self.assertEqual(result.coverage["coverage_ratio"], 1.0)
        self.assertEqual(manager.calls[0][1]["start_date"], "2026-05-09")

    def test_risk_events_returns_partial_when_one_source_fails(self) -> None:
        manager = FakeManager(
            {
                "announcements": _result("announcements", []),
                "lockup": AShareProviderUnavailable("lockup unavailable"),
                "dragon_tiger_stock": _result("dragon_tiger_stock", []),
            }
        )
        service = AShareIntelligenceService(SimpleNamespace(ashare_intelligence_enabled=True))

        result = service.get_risk_events(
            code="600519",
            trade_date="2026-06-08",
            manager=manager,
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.source.status, "partial")
        self.assertIn("lockup:lockup unavailable", result.coverage["warnings"])

    def test_risk_events_raises_when_all_sources_are_unavailable(self) -> None:
        manager = FakeManager(
            {
                "announcements": AShareProviderUnavailable("ann unavailable"),
                "lockup": AShareProviderUnavailable("lockup unavailable"),
                "dragon_tiger_stock": AShareProviderUnavailable("lt unavailable"),
            }
        )
        service = AShareIntelligenceService(SimpleNamespace(ashare_intelligence_enabled=True))

        with self.assertRaises(AShareProviderUnavailable):
            service.get_risk_events(
                code="600519",
                trade_date="2026-06-08",
                manager=manager,
            )


if __name__ == "__main__":
    unittest.main()
