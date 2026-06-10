# -*- coding: utf-8 -*-
"""A-share intelligence DB snapshot repository tests."""

from __future__ import annotations

import unittest
import sqlite3
import tempfile
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

    def test_same_snapshot_slot_appends_revision(self) -> None:
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

        self.assertEqual(count, 2)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(second.revision, 2)
        self.assertEqual(found["revision"], 2)
        self.assertEqual(found["payload"]["status"], "partial")
        self.assertEqual(found["run_id"], "run-2")

    def test_provider_set_order_is_normalized_for_snapshot_slot(self) -> None:
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

        first = self.repo.save_snapshot(provider_set="astock_data,custom", **base_kwargs)
        second = self.repo.save_snapshot(provider_set="custom,astock_data", **base_kwargs)

        with self.db.get_session() as session:
            count = session.execute(
                select(func.count()).select_from(AShareIntelligenceSnapshot)
            ).scalar_one()

        self.assertEqual(count, 2)
        self.assertEqual(first.provider_set, "astock_data,custom")
        self.assertEqual(second.provider_set, "astock_data,custom")
        self.assertEqual(first.provider_set_hash, second.provider_set_hash)
        self.assertEqual(second.revision, 2)

    def test_legacy_sqlite_snapshot_table_is_migrated_to_append_only(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/legacy.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE ashare_intelligence_snapshot (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        snapshot_id VARCHAR(64) NOT NULL UNIQUE,
                        snapshot_type VARCHAR(64) NOT NULL,
                        trade_date DATE NOT NULL,
                        as_of DATETIME NOT NULL,
                        as_of_bucket VARCHAR(64) NOT NULL,
                        run_id VARCHAR(64),
                        provider_set VARCHAR(128) NOT NULL,
                        is_final BOOLEAN NOT NULL,
                        revision INTEGER NOT NULL,
                        coverage_ratio FLOAT,
                        payload_json TEXT NOT NULL,
                        schema_version VARCHAR(32) NOT NULL,
                        source_hash VARCHAR(64) NOT NULL,
                        config_hash VARCHAR(64),
                        generated_at DATETIME NOT NULL,
                        CONSTRAINT uix_ashare_snapshot_slot UNIQUE (
                            snapshot_type,
                            trade_date,
                            as_of_bucket,
                            schema_version,
                            provider_set
                        )
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO ashare_intelligence_snapshot (
                        snapshot_id,
                        snapshot_type,
                        trade_date,
                        as_of,
                        as_of_bucket,
                        run_id,
                        provider_set,
                        is_final,
                        revision,
                        coverage_ratio,
                        payload_json,
                        schema_version,
                        source_hash,
                        config_hash,
                        generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-1",
                        "sector_fund_flow",
                        "2026-06-08",
                        "2026-06-08 10:00:00",
                        "2026-06-08-api",
                        "run-1",
                        "custom,astock_data",
                        0,
                        1,
                        0.5,
                        '{"status":"ok","rows":[1]}',
                        "v1",
                        "hash-1",
                        "cfg-1",
                        "2026-06-08 10:01:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            migrated_db = DatabaseManager(db_url=f"sqlite:///{db_path}")
            repo = AShareSnapshotRepository(migrated_db)
            saved = repo.save_snapshot(
                snapshot_type="sector_fund_flow",
                trade_date="2026-06-08",
                as_of="2026-06-08T10:05:00+08:00",
                as_of_bucket="2026-06-08-api",
                run_id="run-2",
                provider_set="astock_data,custom",
                is_final=False,
                coverage_ratio=0.9,
                payload={"status": "partial", "rows": [2]},
                schema_version="v1",
                config_hash="cfg-2",
            )

            with migrated_db.get_session() as session:
                count = session.execute(
                    select(func.count()).select_from(AShareIntelligenceSnapshot)
                ).scalar_one()
                migrated = session.execute(
                    select(AShareIntelligenceSnapshot).where(
                        AShareIntelligenceSnapshot.snapshot_id == "legacy-1"
                    )
                ).scalar_one()

            self.assertEqual(count, 2)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(migrated.provider_set, "astock_data,custom")
            self.assertIsNotNone(migrated.provider_set_json)
            self.assertIsNotNone(migrated.provider_set_hash)

        DatabaseManager.reset_instance()


if __name__ == "__main__":
    unittest.main()
