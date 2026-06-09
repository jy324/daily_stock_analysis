# -*- coding: utf-8 -*-
"""A-share intelligence API contract tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_risk_events_endpoint_returns_service_result(self) -> None:
        temp_dir, client = _client()
        risk_result = _result("partial")
        risk_result.capability = "risk_events"
        risk_result.data = {"events": []}
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch.object(AShareIntelligenceService, "get_risk_events", return_value=risk_result) as call:
                    response = client.get("/api/v1/stocks/600519/risk-events?lookback=20")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(call.call_args.kwargs["code"], "600519")
        self.assertEqual(call.call_args.kwargs["lookback"], 20)

    def test_ashare_review_rejects_when_feature_disabled(self) -> None:
        temp_dir, client = _client()
        try:
            response = client.post("/api/v1/market/ashare/review", json={"send_notification": False})
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "feature_disabled")

    def test_ashare_review_accepts_background_task_for_cn_region(self) -> None:
        temp_dir, client = _client()
        captured_kwargs = {}

        def _submit_background_task(_task_fn, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                trace_id=kwargs["task_id"],
            )

        task_queue = SimpleNamespace(
            get_task=lambda _task_id: None,
            submit_background_task=_submit_background_task,
        )
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=object()), \
                        patch("api.v1.endpoints.ashare_intelligence.get_task_queue", return_value=task_queue), \
                        patch("api.v1.endpoints.ashare_intelligence._try_acquire_market_review_lock", return_value=object()):
                    response = client.post(
                        "/api/v1/market/ashare/review",
                        json={"send_notification": False, "reportLanguage": "en"},
                        headers={"Idempotency-Key": "review-key"},
                    )
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertFalse(body["send_notification"])
        self.assertTrue(body["task_id"].startswith("ashare-review-"))
        self.assertIsNotNone(captured_kwargs["idempotency_key_hash"])
        self.assertIsNotNone(captured_kwargs["request_body_hash"])

    def test_ashare_review_idempotency_key_reuses_existing_task(self) -> None:
        temp_dir, client = _client()
        existing_task = SimpleNamespace(task_id="ashare-review-existing", trace_id="trace-existing")
        task_queue = SimpleNamespace(
            get_task=lambda _task_id: existing_task,
            submit_background_task=lambda *args, **kwargs: self.fail("must not submit duplicate task"),
        )
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=object()), \
                        patch("api.v1.endpoints.ashare_intelligence.get_task_queue", return_value=task_queue):
                    response = client.post(
                        "/api/v1/market/ashare/review",
                        headers={"Idempotency-Key": "review-key"},
                    )
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["task_id"], "ashare-review-existing")
        self.assertEqual(body["trace_id"], "trace-existing")

    def test_ashare_review_idempotency_key_rejects_different_body(self) -> None:
        from api.v1.endpoints.ashare_intelligence import _market_review_request_hash
        from api.v1.schemas.analysis import MarketReviewRequest

        temp_dir, client = _client()
        existing_task = SimpleNamespace(
            task_id="ashare-review-existing",
            trace_id="trace-existing",
            request_body_hash=_market_review_request_hash(
                MarketReviewRequest(send_notification=True)
            ),
        )
        task_queue = SimpleNamespace(
            get_task=lambda _task_id: existing_task,
            submit_background_task=lambda *args, **kwargs: self.fail("must not submit conflicting task"),
        )
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=object()), \
                        patch("api.v1.endpoints.ashare_intelligence.get_task_queue", return_value=task_queue):
                    response = client.post(
                        "/api/v1/market/ashare/review",
                        json={"send_notification": False},
                        headers={"Idempotency-Key": "review-key"},
                    )
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "idempotency_conflict")


if __name__ == "__main__":
    unittest.main()
