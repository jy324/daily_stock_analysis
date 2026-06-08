# -*- coding: utf-8 -*-
"""A-share intelligence API contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareSourceMetadata
from src.services.ashare_intelligence_service import AShareIntelligenceService


def _client() -> tuple[tempfile.TemporaryDirectory[str], TestClient]:
    temp_dir = tempfile.TemporaryDirectory()
    return temp_dir, TestClient(create_app(static_dir=Path(temp_dir.name)))


def _result(status: str = "empty") -> AShareIntelligenceResult:
    return AShareIntelligenceResult(
        capability="sector_fund_flow",
        provider="fake",
        status=status,
        data=[],
        source=AShareSourceMetadata(
            provider="fake",
            status=status,
            as_of="2026-06-08T10:30:00+08:00",
            is_partial=False,
        ),
        coverage={"coverage_ratio": 0.0},
        cache_hit=False,
    )


class AShareIntelligenceApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()

    def tearDown(self) -> None:
        Config.reset_instance()

    def test_market_endpoint_rejects_when_feature_disabled(self) -> None:
        temp_dir, client = _client()
        try:
            response = client.get("/api/v1/market/ashare/sector-flow")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "feature_disabled")

    def test_stock_endpoint_reports_missing_dependency_when_enabled(self) -> None:
        temp_dir, client = _client()
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=None):
                    response = client.get("/api/v1/stocks/600519/capital-flow")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "dependency_unavailable")

    def test_market_endpoint_returns_empty_status_from_service(self) -> None:
        temp_dir, client = _client()
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch.object(AShareIntelligenceService, "get_capability", return_value=_result("empty")) as call:
                    response = client.get("/api/v1/market/ashare/sector-flow?trade_date=2026-06-08&limit=3")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "empty")
        self.assertFalse(body["cache_hit"])
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], "sector_fund_flow")
        self.assertEqual(call.call_args.kwargs["trade_date"], "2026-06-08")
        self.assertEqual(call.call_args.kwargs["limit"], 3)

    def test_stock_capital_flow_endpoint_returns_partial_status_from_service(self) -> None:
        temp_dir, client = _client()
        partial = _result("partial")
        partial.capability = "capital_flow_daily"
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch.object(AShareIntelligenceService, "get_capability", return_value=partial) as call:
                    response = client.get("/api/v1/stocks/600519/capital-flow?lookback=20")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(call.call_args.args[0], "capital_flow_daily")
        self.assertEqual(call.call_args.kwargs["code"], "600519")
        self.assertEqual(call.call_args.kwargs["lookback"], 20)


if __name__ == "__main__":
    unittest.main()
