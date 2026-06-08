# -*- coding: utf-8 -*-
"""A-share intelligence DB snapshot repository tests."""

from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.sql import func

from src.repositories.ashare_snapshot_repo import AShareSnapshotRepository
from src.storage import AShareIntelligenceSnapshot, DatabaseManager


class AShareSnapshotRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.repo = AShareSnapshotRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_snapshot_table_is_registered_with_metadata_create_all(self) -> None:
        with self.db.get_session() as session:
            count = session.execute(
                select(func.count()).select_from(AShareIntelligenceSnapshot)
            ).scalar_one()

        self.assertEqual(count, 0)

    def test_save_and_read_snapshot_round_trip(self) -> None:
        saved = self.repo.save_snapshot(
            snapshot_type="capital_flow_minute",
            trade_date="2026-06-08",
            as_of="2026-06-08T10:30:00+08:00",
            as_of_bucket="2026-06-08-am",
            run_id="run-1",
            provider_set="astock_data",
            is_final=False,
            coverage_ratio=0.85,
            payload={"status": "ok", "rows": [{"code": "600519"}]},
            schema_version="v1",
            config_hash="cfg-1",
        )

        found = self.repo.get_snapshot(
            snapshot_type="capital_flow_minute",
            trade_date="2026-06-08",
            as_of_bucket="2026-06-08-am",
            schema_version="v1",
            provider_set="astock_data",
        )

        self.assertIsNotNone(found)
        self.assertEqual(found["snapshot_id"], saved.snapshot_id)
        self.assertEqual(found["revision"], 1)
        self.assertEqual(found["payload"]["status"], "ok")
        self.assertEqual(found["coverage_ratio"], 0.85)
        self.assertEqual(found["source_hash"], saved.source_hash)
        self.assertEqual(found["generated_at"].date(), datetime.now().date())

    def test_same_unique_snapshot_slot_updates_revision(self) -> None:
        first = self.repo.save_snapshot(
            snapshot_type="dragon_tiger_market",
            trade_date="2026-06-08",
            as_of="2026-06-08T18:00:00+08:00",
            as_of_bucket="2026-06-08-final",
            run_id="run-1",
            provider_set="astock_data",
            is_final=True,
            coverage_ratio=1.0,
            payload={"status": "empty", "rows": []},
            schema_version="v1",
            config_hash="cfg-1",
        )
        second = self.repo.save_snapshot(
            snapshot_type="dragon_tiger_market",
            trade_date="2026-06-08",
            as_of="2026-06-08T18:05:00+08:00",
            as_of_bucket="2026-06-08-final",
            run_id="run-2",
            provider_set="astock_data",
            is_final=True,
            coverage_ratio=0.5,
            payload={"status": "partial", "rows": [{"code": "000001"}]},
            schema_version="v1",
            config_hash="cfg-2",
        )

        with self.db.get_session() as session:
            count = session.execute(
                select(func.count()).select_from(AShareIntelligenceSnapshot)
            ).scalar_one()

        found = self.repo.get_snapshot(
            snapshot_type="dragon_tiger_market",
            trade_date="2026-06-08",
            as_of_bucket="2026-06-08-final",
            schema_version="v1",
            provider_set="astock_data",
        )

        self.assertEqual(count, 1)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(second.revision, 2)
        self.assertEqual(found["revision"], 2)
        self.assertEqual(found["payload"]["status"], "partial")
        self.assertEqual(found["run_id"], "run-2")

    def test_provider_set_is_part_of_unique_snapshot_slot(self) -> None:
        base_kwargs = {
            "snapshot_type": "announcements",
            "trade_date": "2026-06-08",
            "as_of": "2026-06-08T20:00:00+08:00",
            "as_of_bucket": "2026-06-08-final",
            "run_id": "run-1",
            "is_final": True,
            "coverage_ratio": 1.0,
            "payload": {"status": "ok"},
            "schema_version": "v1",
            "config_hash": "cfg-1",
        }

        self.repo.save_snapshot(provider_set="astock_data", **base_kwargs)
        self.repo.save_snapshot(provider_set="custom,astock_data", **base_kwargs)

        with self.db.get_session() as session:
            count = session.execute(
                select(func.count()).select_from(AShareIntelligenceSnapshot)
            ).scalar_one()

        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
