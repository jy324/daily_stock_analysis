# -*- coding: utf-8 -*-
"""Tests for the DecisionSignal query/management API (workflow B).

The signal backend already exists; these cover the new read/filter endpoints,
the latest-active lookup, and the manual lifecycle state update (which must
reuse the forward-only state machine and reject illegal transitions).
"""

import os
import tempfile
import unittest
from datetime import date


class _SignalApiBase(unittest.TestCase):
    def setUp(self):
        from src.config import Config
        from src.storage import DatabaseManager

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "sig.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self):
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        self._tmp.cleanup()

    def _save(self, **overrides):
        from src.repositories.decision_signal_repo import DecisionSignalRepository
        from src.schemas.decision_signal import DecisionSignal

        params = dict(
            code="600519", direction="long", action="buy",
            entry_type="market", source="llm_structured",
        )
        params.update(overrides)
        return DecisionSignalRepository(self.db).save_signal(DecisionSignal(**params))


class RepositoryFilterTestCase(_SignalApiBase):
    def test_list_filters_and_total(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        self._save(code="600519", action="buy", source="llm_structured")
        self._save(code="000001", action="sell", direction="short", source="normalized_fallback")
        self._save(code="600519", action="hold")
        repo = DecisionSignalRepository(self.db)

        rows, total = repo.list_signals(code="600519")
        self.assertEqual(total, 2)
        self.assertTrue(all(r.code == "600519" for r in rows))

        rows, total = repo.list_signals(action="sell")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].code, "000001")

        rows, total = repo.list_signals(source="normalized_fallback")
        self.assertEqual(total, 1)

    def test_active_only_excludes_terminal(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        self._save(code="600519")
        self._save(code="600519", state="expired")
        repo = DecisionSignalRepository(self.db)

        rows, total = repo.list_signals(active_only=True)
        self.assertEqual(total, 1)
        self.assertNotIn("expired", [r.state for r in rows])

    def test_pagination(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        for _ in range(5):
            self._save()
        repo = DecisionSignalRepository(self.db)
        rows, total = repo.list_signals(limit=2, offset=0)
        self.assertEqual(total, 5)
        self.assertEqual(len(rows), 2)

    def test_latest_active_for_code(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        self._save(code="600519", state="expired")
        latest = self._save(code="600519")
        repo = DecisionSignalRepository(self.db)
        row = repo.get_latest_active_for_code("600519")
        self.assertIsNotNone(row)
        self.assertEqual(row.id, latest.id)

    def test_code_filters_match_equivalent_stock_code_variants(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        row = self._save(code="600519")
        hk = self._save(code="HK00700")
        repo = DecisionSignalRepository(self.db)

        rows, total = repo.list_signals(code="SH600519")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].id, row.id)

        latest = repo.get_latest_active_for_code("700.HK")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, hk.id)


class ServiceStateUpdateTestCase(_SignalApiBase):
    def test_valid_transition_appends_history(self):
        from src.services.decision_signal_query_service import DecisionSignalQueryService

        row = self._save(state="generated")
        service = DecisionSignalQueryService(self.db)
        updated = service.update_state(row.id, new_state="entered", note="manual fill")

        self.assertEqual(updated["state"], "entered")
        self.assertEqual(updated["entered_date"], date.today().isoformat())
        self.assertEqual(len(updated["state_history"]), 1)
        entry = updated["state_history"][0]
        self.assertEqual(entry["from"], "generated")
        self.assertEqual(entry["to"], "entered")
        self.assertEqual(entry["source"], "manual")
        self.assertEqual(entry["note"], "manual fill")

    def test_illegal_transition_raises(self):
        from src.services.decision_signal_query_service import (
            DecisionSignalQueryService,
            InvalidSignalTransition,
        )

        row = self._save(state="generated")
        service = DecisionSignalQueryService(self.db)
        # generated -> target_hit is not allowed (must enter first).
        with self.assertRaises(InvalidSignalTransition):
            service.update_state(row.id, new_state="target_hit")

    def test_missing_signal_raises(self):
        from src.services.decision_signal_query_service import (
            DecisionSignalQueryService,
            SignalNotFound,
        )

        service = DecisionSignalQueryService(self.db)
        with self.assertRaises(SignalNotFound):
            service.update_state(99999, new_state="entered")

    def test_stale_state_update_raises_conflict(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository
        from src.services.decision_signal_query_service import (
            DecisionSignalQueryService,
            InvalidSignalTransition,
        )

        stale_row = self._save(state="generated")
        repo = DecisionSignalRepository(self.db)
        updated = repo.update_lifecycle(
            stale_row.id,
            state="waiting_entry",
            expected_state="generated",
            history_entry={"from": "generated", "to": "waiting_entry"},
        )
        self.assertTrue(updated)

        service = DecisionSignalQueryService(self.db)
        service.repo.get_by_id = lambda _signal_id: stale_row
        with self.assertRaises(InvalidSignalTransition):
            service.update_state(stale_row.id, new_state="entered")

    def test_repository_expected_state_guard_does_not_overwrite(self):
        from src.repositories.decision_signal_repo import DecisionSignalRepository

        row = self._save(state="waiting_entry")
        repo = DecisionSignalRepository(self.db)

        updated = repo.update_lifecycle(
            row.id,
            state="entered",
            expected_state="generated",
            history_entry={"from": "generated", "to": "entered"},
        )
        self.assertFalse(updated)
        current = repo.get_by_id(row.id)
        self.assertEqual(current.state, "waiting_entry")
        self.assertEqual(current.state_history, [])


class ApiEndpointTestCase(_SignalApiBase):
    def _client(self):
        from fastapi.testclient import TestClient
        from server import app

        return TestClient(app)

    def test_list_and_get_and_latest(self):
        row = self._save(code="600519")
        client = self._client()

        resp = client.get("/api/v1/signals?code=600519")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["code"], "600519")

        resp = client.get(f"/api/v1/signals/{row.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], row.id)

        resp = client.get("/api/v1/signals/latest?code=600519")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], row.id)

        resp = client.get("/api/v1/signals/latest?code=600519.SH")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], row.id)

    def test_latest_404_when_none(self):
        client = self._client()
        resp = client.get("/api/v1/signals/latest?code=999999")
        self.assertEqual(resp.status_code, 404)

    def test_patch_state_valid_and_conflict(self):
        row = self._save(state="generated")
        client = self._client()

        resp = client.patch(f"/api/v1/signals/{row.id}/state", json={"state": "entered"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "entered")

        # entered -> waiting_entry is illegal -> 409.
        resp = client.patch(f"/api/v1/signals/{row.id}/state", json={"state": "waiting_entry"})
        self.assertEqual(resp.status_code, 409)

    def test_patch_state_missing_404(self):
        client = self._client()
        resp = client.patch("/api/v1/signals/424242/state", json={"state": "entered"})
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
