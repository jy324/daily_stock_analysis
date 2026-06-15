# -*- coding: utf-8 -*-
"""Query/management service for structured DecisionSignals (workflow B).

The signal backend (schema, table, repository, lifecycle state machine) already
exists and is consumed by reports/backtests; this service exposes it for
querying and manual lifecycle management without inventing a parallel data
model. Manual state changes are validated against the same forward-only
:class:`SignalStateMachine` used by the daily advancer, so the API cannot make a
transition the automated pipeline would reject.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.services.decision_signal_service import (
    InvalidSignalTransition,
    SignalStateMachine,
    is_terminal_state,
)
from src.storage import DatabaseManager, DecisionSignalRecord


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def serialize_signal_record(row: DecisionSignalRecord) -> Dict[str, Any]:
    """Serialize an ORM row into the API payload (signal fields + lifecycle)."""
    return {
        "id": row.id,
        "code": row.code,
        "market": row.market,
        "analysis_history_id": row.analysis_history_id,
        "signal_version": row.signal_version,
        "generated_at": _iso(row.generated_at),
        "source": row.source,
        "operation_advice": row.operation_advice,
        "direction": row.direction,
        "action": row.action,
        "position_size_pct": row.position_size_pct,
        "confidence_level": row.confidence_level,
        "confidence_score": row.confidence_score,
        "entry_type": row.entry_type,
        "entry_price": row.entry_price,
        "entry_low": row.entry_low,
        "entry_high": row.entry_high,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "valid_from": _iso(row.valid_from),
        "valid_until": _iso(row.valid_until),
        "invalidation_conditions": row.invalidation_conditions,
        "applicable_phases": row.applicable_phases,
        "quality_constraints": row.quality_constraints,
        "state": row.state,
        "state_history": row.state_history,
        "entered_date": _iso(row.entered_date),
        "entered_price": row.entered_price,
        "closed_date": _iso(row.closed_date),
        "closed_price": row.closed_price,
        "created_at": _iso(row.created_at),
    }


class SignalNotFound(Exception):
    """Raised when a manual operation targets a missing signal."""


class DecisionSignalQueryService:
    """Read and manually manage persisted decision signals."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = DecisionSignalRepository(self.db)

    def list_signals(
        self,
        *,
        code: Optional[str] = None,
        market: Optional[str] = None,
        action: Optional[str] = None,
        state: Optional[str] = None,
        source: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        rows, total = self.repo.list_signals(
            code=code, market=market, action=action, state=state,
            source=source, active_only=active_only, limit=limit, offset=offset,
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [serialize_signal_record(row) for row in rows],
        }

    def get_signal(self, signal_id: int) -> Optional[Dict[str, Any]]:
        row = self.repo.get_by_id(signal_id)
        return serialize_signal_record(row) if row is not None else None

    def get_latest_active_for_code(self, code: str) -> Optional[Dict[str, Any]]:
        row = self.repo.get_latest_active_for_code(code)
        return serialize_signal_record(row) if row is not None else None

    def update_state(
        self,
        signal_id: int,
        *,
        new_state: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manually transition a signal, enforcing the lifecycle state machine.

        Raises :class:`SignalNotFound` if the signal is missing and
        :class:`InvalidSignalTransition` if the transition is not allowed.
        """
        row = self.repo.get_by_id(signal_id)
        if row is None:
            raise SignalNotFound(f"signal {signal_id} not found")

        # Reuse the forward-only machine; an illegal transition raises and the
        # endpoint maps it to 409 (no silent no-op).
        SignalStateMachine.assert_transition(row.state, new_state)

        today = date.today()
        history_entry = {
            "from": row.state,
            "to": new_state,
            "at": datetime.now(timezone.utc).isoformat(),
            "source": "manual",
        }
        if note:
            history_entry["note"] = note

        entered_date = today if (new_state == "entered" and row.entered_date is None) else None
        closed_date = today if (is_terminal_state(new_state) and row.closed_date is None) else None

        self.repo.update_lifecycle(
            signal_id,
            state=new_state,
            entered_date=entered_date,
            closed_date=closed_date,
            history_entry=history_entry,
        )
        return self.get_signal(signal_id)

    @staticmethod
    def serialize(row: DecisionSignalRecord) -> Dict[str, Any]:
        return serialize_signal_record(row)


__all__ = [
    "DecisionSignalQueryService",
    "SignalNotFound",
    "InvalidSignalTransition",
    "serialize_signal_record",
]
