# -*- coding: utf-8 -*-
"""A-share intelligence service snapshot write tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.repositories.ashare_snapshot_repo import AShareSnapshotRepository
from src.schemas.ashare_intelligence import (
    AShareIntelligenceResult,
    AShareSourceMetadata,
)
from src.services.ashare_intelligence_service import AShareIntelligenceService
from src.storage import DatabaseManager


class FakeManager:
    def __init__(self) -> None:
        self.calls = 0

    def get_capability(self, capability: str, **query):
        self.calls += 1
        return AShareIntelligenceResult(
            capability=capability,
            provider="fake",
            status="ok",
            data={"rows": [{"code": query["code"]}]},
            source=AShareSourceMetadata(
                provider="fake",
                status="ok",
                as_of="2026-06-08T10:30:00+08:00",
                is_partial=False,
            ),
            coverage={"coverage_ratio": 0.75},
            cache_hit=False,
        )


class AShareIntelligenceServiceSnapshotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_get_capability_can_persist_snapshot(self) -> None:
        config = SimpleNamespace(
            ashare_intelligence_enabled=True,
            ashare_provider_priority="fake",
            ashare_cache_dir="./unused",
            ashare_config_file="missing.yaml",
        )
        repo = AShareSnapshotRepository(self.db)
        manager = FakeManager()

        with patch("src.services.ashare_intelligence_service.is_astock_data_installed", return_value=True):
            result = AShareIntelligenceService(config, snapshot_repository=repo).get_capability(
                "capital_flow_minute",
                code="600519",
                trade_date="2026-06-08",
                as_of_bucket="2026-06-08-am",
                run_id="run-1",
                config_hash="cfg-1",
                manager=manager,
            )

        snapshot = repo.get_snapshot(
            snapshot_type="capital_flow_minute",
            trade_date="2026-06-08",
            as_of_bucket="2026-06-08-am",
            schema_version="v1",
            provider_set="fake",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(manager.calls, 1)
        self.assertIsNotNone(snapshot)
        self.assertEqual(result.snapshot_id, snapshot["snapshot_id"])
        self.assertEqual(result.snapshot_revision, 1)
        self.assertEqual(snapshot["payload"]["data"]["rows"][0]["code"], "600519")
        self.assertEqual(snapshot["coverage_ratio"], 0.75)


if __name__ == "__main__":
    unittest.main()
