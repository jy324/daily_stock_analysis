# -*- coding: utf-8 -*-
"""Tests for DecisionSignal lifecycle persistence + migration (workflow B.2)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal
from src.storage import DatabaseManager


def _columns(db_path: str, table: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        return {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    finally:
        conn.close()


class DecisionSignalLifecycleMigrationTestCase(unittest.TestCase):
    """An existing B.1-era decision_signals table must gain lifecycle columns."""

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_existing_table_gains_lifecycle_columns(self) -> None:
        DatabaseManager.reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/b1.db"
            conn = sqlite3.connect(db_path)
            try:
                # Minimal B.1-era table without the lifecycle columns.
                conn.execute(
                    """
                    CREATE TABLE decision_signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code VARCHAR(10) NOT NULL,
                        direction VARCHAR(16) NOT NULL,
                        entry_type VARCHAR(16) NOT NULL DEFAULT 'none',
                        state VARCHAR(24) NOT NULL DEFAULT 'generated'
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            DatabaseManager(db_url=f"sqlite:///{db_path}")

            cols = _columns(db_path, "decision_signals")
            for col in (
                "state_history_json",
                "entered_date",
                "entered_price",
                "closed_date",
                "closed_price",
            ):
                self.assertIn(col, cols, col)


class DecisionSignalLifecycleRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.repo = DecisionSignalRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def _save(self, **overrides):
        payload = {
            "code": "600519",
            "analysis_history_id": 1,
            "direction": "long",
            "action": "buy",
            "entry_type": "precise",
            "entry_price": 1680.0,
            "stop_loss": 1600.0,
            "take_profit": 1800.0,
        }
        payload.update(overrides)
        return self.repo.save_signal(DecisionSignal(**payload))

    def test_get_active_signals_excludes_terminal(self) -> None:
        self._save(state="generated")
        self._save(state="entered", analysis_history_id=2)
        self._save(state="stop_hit", analysis_history_id=3)
        self._save(state="expired", analysis_history_id=4)

        active = self.repo.get_active_signals()
        states = sorted(r.state for r in active)
        self.assertEqual(states, ["entered", "generated"])

    def test_update_lifecycle_records_fields_and_history(self) -> None:
        rec = self._save(state="waiting_entry")
        self.repo.update_lifecycle(
            rec.id,
            state="entered",
            entered_date=date(2026, 6, 11),
            entered_price=1680.0,
            history_entry={"from": "waiting_entry", "to": "entered", "day": "2026-06-11"},
        )
        updated = self.repo.get_latest_for_analysis(rec.analysis_history_id)
        self.assertEqual(updated.state, "entered")
        self.assertEqual(updated.entered_price, 1680.0)
        self.assertEqual(updated.entered_date, date(2026, 6, 11))
        history = updated.state_history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["to"], "entered")

    def test_state_history_appends(self) -> None:
        rec = self._save(state="generated")
        self.repo.update_lifecycle(rec.id, state="waiting_entry", history_entry={"to": "waiting_entry"})
        self.repo.update_lifecycle(rec.id, state="entered", history_entry={"to": "entered"})
        updated = self.repo.get_latest_for_analysis(rec.analysis_history_id)
        self.assertEqual([h["to"] for h in updated.state_history], ["waiting_entry", "entered"])


if __name__ == "__main__":
    unittest.main()
