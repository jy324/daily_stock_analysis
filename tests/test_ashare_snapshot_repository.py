# -*- coding: utf-8 -*-
"""A-share intelligence DB snapshot repository tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

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
            _create_legacy_snapshot_db(db_path)

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
            self.assertEqual(_legacy_snapshot_row_count(db_path), 1)

        DatabaseManager.reset_instance()

    def test_legacy_sqlite_snapshot_migration_preserves_data_when_create_fails(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/legacy-create-fail.db"
            _create_legacy_snapshot_db(db_path)

            with patch.object(
                DatabaseManager,
                "_create_ashare_snapshot_table_for_migration",
                side_effect=RuntimeError("create failed"),
            ):
                with self.assertRaises(RuntimeError):
                    DatabaseManager(db_url=f"sqlite:///{db_path}")

            self.assertEqual(_snapshot_table_row_count(db_path), 1)
            self.assertEqual(_legacy_snapshot_row_count(db_path), 0)

        DatabaseManager.reset_instance()

    def test_legacy_sqlite_snapshot_migration_preserves_data_when_normalize_fails(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/legacy-normalize-fail.db"
            _create_legacy_snapshot_db(db_path)

            with patch.object(
                DatabaseManager,
                "_normalize_ashare_snapshot_row",
                side_effect=RuntimeError("normalize failed"),
            ):
                with self.assertRaises(RuntimeError):
                    DatabaseManager(db_url=f"sqlite:///{db_path}")

            self.assertEqual(_snapshot_table_row_count(db_path), 1)
            self.assertEqual(_legacy_snapshot_row_count(db_path), 0)

        DatabaseManager.reset_instance()

    def test_legacy_sqlite_snapshot_migration_preserves_data_when_insert_conflicts(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/legacy-conflict.db"
            _create_legacy_snapshot_db(db_path, include_unique_slot=False)
            _insert_legacy_snapshot_row(db_path, snapshot_id="legacy-2", run_id="run-duplicate")

            with self.assertRaises(Exception):
                DatabaseManager(db_url=f"sqlite:///{db_path}")

            self.assertEqual(_snapshot_table_row_count(db_path), 2)
            self.assertEqual(_legacy_snapshot_row_count(db_path), 0)

        DatabaseManager.reset_instance()


def _create_legacy_snapshot_db(db_path: str, *, include_unique_slot: bool = True) -> None:
    connection = sqlite3.connect(db_path)
    unique_clause = (
        """
        , CONSTRAINT uix_ashare_snapshot_slot UNIQUE (
            snapshot_type,
            trade_date,
            as_of_bucket,
            schema_version,
            provider_set
        )
        """
        if include_unique_slot
        else ""
    )
    try:
        connection.execute(
            f"""
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
                generated_at DATETIME NOT NULL
                {unique_clause}
            )
            """
        )
        _insert_legacy_snapshot_row(db_path, connection=connection)
        connection.commit()
    finally:
        connection.close()


def _insert_legacy_snapshot_row(
    db_path: str,
    *,
    connection: sqlite3.Connection | None = None,
    snapshot_id: str = "legacy-1",
    run_id: str = "run-1",
) -> None:
    owns_connection = connection is None
    connection = connection or sqlite3.connect(db_path)
    try:
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
                snapshot_id,
                "sector_fund_flow",
                "2026-06-08",
                "2026-06-08 10:00:00",
                "2026-06-08-api",
                run_id,
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
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def _snapshot_table_row_count(db_path: str) -> int:
    return _table_row_count(db_path, "ashare_intelligence_snapshot")


def _legacy_snapshot_row_count(db_path: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ashare_intelligence_snapshot__legacy_%'"
            ).fetchall()
        ]
        return sum(_table_row_count(db_path, name) for name in names)
    finally:
        connection.close()


def _table_row_count(db_path: str, table_name: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
        return int(row[0])
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
