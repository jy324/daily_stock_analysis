# -*- coding: utf-8 -*-
"""Market review payload tests for optional A-share intelligence evidence."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.core.market_profile import get_profile
from src.market_analyzer import MarketAnalyzer, MarketOverview
from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareSourceMetadata


class FakeIntelligenceService:
    def __init__(self) -> None:
        self.calls = []

    def get_capability(self, capability: str, **kwargs):
        self.calls.append((capability, kwargs))
        return AShareIntelligenceResult(
            capability=capability,
            provider="fake",
            status="partial",
            data=[
                {
                    "sector_name": "半导体",
                    "sector_type": "concept",
                    "provider_sector_code": "BK1036",
                    "taxonomy": "eastmoney",
                    "main_net_inflow": {"amount": 123400000.0, "unit": "CNY"},
                    "change_pct": 1.23,
                }
            ],
            source=AShareSourceMetadata(
                provider="fake",
                status="partial",
                as_of="2026-06-08T10:30:00+08:00",
                is_partial=True,
            ),
            coverage={"coverage_ratio": 0.5},
            cache_hit=False,
        )


def _analyzer(*, region: str, enabled: bool, service=None) -> MarketAnalyzer:
    analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
    analyzer.config = SimpleNamespace(
        report_language="zh",
        ashare_intelligence_enabled=enabled,
        ashare_config_file="missing.yaml",
    )
    analyzer.region = region
    analyzer.profile = get_profile(region)
    analyzer.intelligence_service = service
    return analyzer


class MarketReviewAShareIntelligencePayloadTestCase(unittest.TestCase):
    def test_init_builds_default_service_only_for_enabled_cn_market(self) -> None:
        with patch("src.market_analyzer.DataFetcherManager"), \
                patch("src.services.ashare_intelligence_service.is_ashare_feature_section_enabled") as enabled:
            enabled.side_effect = lambda config, section: bool(getattr(config, "ashare_intelligence_enabled", False)) and section == "report"
            disabled = MarketAnalyzer(config=SimpleNamespace(ashare_intelligence_enabled=False), region="cn")
            us = MarketAnalyzer(config=SimpleNamespace(ashare_intelligence_enabled=True), region="us")
            cn = MarketAnalyzer(config=SimpleNamespace(ashare_intelligence_enabled=True), region="cn")

        self.assertIsNone(disabled.intelligence_service)
        self.assertIsNone(us.intelligence_service)
        self.assertIsNotNone(cn.intelligence_service)

    def test_disabled_gate_preserves_payload_without_service_call(self) -> None:
        service = FakeIntelligenceService()
        analyzer = _analyzer(region="cn", enabled=False, service=service)

        payload = analyzer.build_market_review_payload(
            MarketOverview(date="2026-06-08"),
            [],
            "## 2026-06-08 大盘复盘\n\n### 四、资金与情绪\nLLM 解读。",
            {"dimensions": {}},
        )

        self.assertEqual(service.calls, [])
        self.assertNotIn("ashare_intelligence", payload)
        self.assertFalse(any(section["key"] == "ashare_capital_evidence" for section in payload["sections"]))

    def test_cn_enabled_payload_adds_objective_evidence_and_interpretation_sections(self) -> None:
        service = FakeIntelligenceService()
        analyzer = _analyzer(region="cn", enabled=True, service=service)

        with patch("src.services.ashare_intelligence_service.is_ashare_feature_section_enabled", return_value=True):
            evidence = analyzer._build_ashare_capital_evidence(MarketOverview(date="2026-06-08"))
            payload = analyzer.build_market_review_payload(
                MarketOverview(date="2026-06-08"),
                [],
                "## 2026-06-08 大盘复盘\n\n### 四、资金与情绪\nLLM 解读。",
                {"dimensions": {}},
                ashare_evidence=evidence,
            )

        self.assertEqual(service.calls[0][0], "sector_fund_flow")
        self.assertEqual(service.calls[0][1]["trade_date"], "2026-06-08")
        self.assertEqual(payload["ashare_intelligence"]["capital_evidence"]["status"], "partial")

        sections = payload["sections"]
        evidence = next(section for section in sections if section["key"] == "ashare_capital_evidence")
        interpretation = next(section for section in sections if section["key"] == "llm_interpretation")
        self.assertEqual(evidence["title"], "资金与情绪：客观数据")
        self.assertIn("半导体", evidence["markdown"])
        self.assertIn("partial", evidence["markdown"])
        self.assertEqual(interpretation["title"], "资金与情绪：分析解读")
        self.assertIn("LLM 解读", interpretation["markdown"])

    def test_payload_builder_reuses_evidence_without_fetching_provider(self) -> None:
        service = FakeIntelligenceService()
        analyzer = _analyzer(region="cn", enabled=True, service=service)
        evidence = {
            "result": {
                "capability": "sector_fund_flow",
                "provider": "fake",
                "status": "unavailable",
                "data": [],
                "source": {
                    "provider": "fake",
                    "status": "unavailable",
                    "as_of": "2026-06-08T10:30:00+08:00",
                    "is_partial": False,
                },
                "coverage": {"warnings": ["provider down"]},
                "cache_hit": False,
            },
            "markdown": "- 数据状态：`unavailable`",
        }

        payload = analyzer.build_market_review_payload(
            MarketOverview(date="2026-06-08"),
            [],
            "## 2026-06-08 大盘复盘\n\n### 四、资金与情绪\nLLM 解读。",
            {"dimensions": {}},
            ashare_evidence=evidence,
        )

        self.assertEqual(service.calls, [])
        self.assertEqual(payload["ashare_intelligence"]["capital_evidence"]["status"], "unavailable")

    def test_non_cn_market_does_not_call_ashare_service(self) -> None:
        service = FakeIntelligenceService()
        analyzer = _analyzer(region="us", enabled=True, service=service)

        payload = analyzer.build_market_review_payload(
            MarketOverview(date="2026-06-08"),
            [],
            "## 2026-06-08 US Market Recap\n\n### 4. Sector Highlights\nLLM text.",
            {"dimensions": {}},
        )

        self.assertEqual(service.calls, [])
        self.assertNotIn("ashare_intelligence", payload)


if __name__ == "__main__":
    unittest.main()
