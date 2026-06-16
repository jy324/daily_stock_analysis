# -*- coding: utf-8 -*-
"""DecisionSignal persistence repository (workflow B)."""

from __future__ import annotations

import json
from typing import List, Optional, Tuple, Union

from sqlalchemy import func, select, update

from src.schemas.decision_signal import DecisionSignal
from src.storage import DatabaseManager, DecisionSignalRecord


class DecisionSignalRepository:
    """Read/write repository for structured decision signals."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def save_signal(self, signal: DecisionSignal) -> DecisionSignalRecord:
        session = self.db.get_session()
        try:
            row = DecisionSignalRecord(
                code=signal.code,
                market=signal.market,
                analysis_history_id=signal.analysis_history_id,
                signal_version=signal.signal_version,
                generated_at=signal.generated_at,
                source=signal.source,
                operation_advice=signal.operation_advice,
                direction=signal.direction,
                action=signal.action,
                position_size_pct=signal.position_size_pct,
                confidence_level=signal.confidence_level,
                confidence_score=signal.confidence_score,
                entry_type=signal.entry_type,
                entry_price=signal.entry_price,
                entry_low=signal.entry_low,
                entry_high=signal.entry_high,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                valid_from=signal.valid_from,
                valid_until=signal.valid_until,
                invalidation_conditions_json=json.dumps(
                    signal.invalidation_conditions, ensure_ascii=False
                ),
                applicable_phases_json=json.dumps(signal.applicable_phases, ensure_ascii=False),
                quality_constraints_json=json.dumps(signal.quality_constraints, ensure_ascii=False),
                state=signal.state,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    _TERMINAL_STATES = ("target_hit", "stop_hit", "expired", "invalidated")

    def get_active_signals(self, limit: int = 1000) -> list:
        """Return non-terminal signals (candidates for daily advancement)."""
        session = self.db.get_session()
        try:
            rows = session.execute(
                select(DecisionSignalRecord)
                .where(DecisionSignalRecord.state.notin_(self._TERMINAL_STATES))
                .order_by(DecisionSignalRecord.id.asc())
                .limit(limit)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)
        finally:
            session.close()

    def update_lifecycle(
        self,
        signal_id: int,
        *,
        state: Optional[str] = None,
        expected_state: Optional[str] = None,
        entered_date=None,
        entered_price: Optional[float] = None,
        closed_date=None,
        closed_price: Optional[float] = None,
        history_entry: Optional[dict] = None,
    ) -> bool:
        """Update lifecycle fields and append one entry to the state history.

        When ``expected_state`` is provided, the write is conditional on the row
        still being in that state. This preserves the state-machine invariant when
        manual API updates race with another manual update or the daily advancer.
        """
        session = self.db.get_session()
        try:
            row = session.get(DecisionSignalRecord, signal_id)
            if row is None:
                return False
            if expected_state is not None and row.state != expected_state:
                return False

            values = {}
            if state is not None:
                values["state"] = state
            if entered_date is not None:
                values["entered_date"] = entered_date
            if entered_price is not None:
                values["entered_price"] = entered_price
            if closed_date is not None:
                values["closed_date"] = closed_date
            if closed_price is not None:
                values["closed_price"] = closed_price
            if history_entry is not None:
                history = json.loads(row.state_history_json or "[]")
                history.append(history_entry)
                values["state_history_json"] = json.dumps(history, ensure_ascii=False)

            if not values:
                session.commit()
                return True

            conditions = [DecisionSignalRecord.id == signal_id]
            if expected_state is not None:
                conditions.append(DecisionSignalRecord.state == expected_state)
            result = session.execute(
                update(DecisionSignalRecord)
                .where(*conditions)
                .values(**values)
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _code_filter_candidates(code: Union[str, List[str], None]) -> List[str]:
        if not code:
            return []
        if isinstance(code, list):
            candidates: List[str] = []
            for item in code:
                for candidate in DecisionSignalRepository._code_filter_candidates(item):
                    if candidate not in candidates:
                        candidates.append(candidate)
            return candidates
        try:
            from src.services.history_service import HistoryService

            return HistoryService._history_code_filter_candidates(code)
        except Exception:
            raw = str(code or "").strip()
            return [raw.upper()] if raw else []

    def _apply_filters(self, stmt, *, code, market, action, state, source, active_only):
        if code:
            candidates = self._code_filter_candidates(code)
            if candidates:
                stmt = stmt.where(DecisionSignalRecord.code.in_(candidates))
        if market:
            stmt = stmt.where(DecisionSignalRecord.market == market)
        if action:
            stmt = stmt.where(DecisionSignalRecord.action == action)
        if state:
            stmt = stmt.where(DecisionSignalRecord.state == state)
        if source:
            stmt = stmt.where(DecisionSignalRecord.source == source)
        if active_only:
            stmt = stmt.where(DecisionSignalRecord.state.notin_(self._TERMINAL_STATES))
        return stmt

    def list_signals(
        self,
        *,
        code: Optional[Union[str, List[str]]] = None,
        market: Optional[str] = None,
        action: Optional[str] = None,
        state: Optional[str] = None,
        source: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[DecisionSignalRecord], int]:
        """Return ``(rows, total)`` for the given filters, newest first.

        ``total`` is the unpaginated match count so callers can paginate. Rows are
        ordered by ``generated_at`` then ``id`` descending (most recent first).
        """
        session = self.db.get_session()
        try:
            base = self._apply_filters(
                select(DecisionSignalRecord),
                code=code, market=market, action=action,
                state=state, source=source, active_only=active_only,
            )
            total = session.execute(
                self._apply_filters(
                    select(func.count(DecisionSignalRecord.id)),
                    code=code, market=market, action=action,
                    state=state, source=source, active_only=active_only,
                )
            ).scalar_one()
            rows = session.execute(
                base.order_by(
                    DecisionSignalRecord.generated_at.desc(),
                    DecisionSignalRecord.id.desc(),
                ).limit(limit).offset(offset)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows), int(total)
        finally:
            session.close()

    def get_by_id(self, signal_id: int) -> Optional[DecisionSignalRecord]:
        """Return a single signal row by primary key, or ``None``."""
        session = self.db.get_session()
        try:
            row = session.get(DecisionSignalRecord, signal_id)
            if row is not None:
                session.expunge(row)
            return row
        finally:
            session.close()

    def get_latest_active_for_code(self, code: str) -> Optional[DecisionSignalRecord]:
        """Return the most recent non-terminal signal for a stock, or ``None``."""
        candidates = self._code_filter_candidates(code)
        session = self.db.get_session()
        try:
            stmt = (
                select(DecisionSignalRecord)
                .where(DecisionSignalRecord.state.notin_(self._TERMINAL_STATES))
                .order_by(
                    DecisionSignalRecord.generated_at.desc(),
                    DecisionSignalRecord.id.desc(),
                )
                .limit(1)
            )
            if candidates:
                stmt = stmt.where(DecisionSignalRecord.code.in_(candidates))
            else:
                stmt = stmt.where(DecisionSignalRecord.code == code)
            row = session.execute(stmt).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row
        finally:
            session.close()

    def get_latest_for_analysis(self, analysis_history_id: int) -> Optional[DecisionSignalRecord]:
        """Return the highest-version signal for an analysis, or ``None``."""
        session = self.db.get_session()
        try:
            row = session.execute(
                select(DecisionSignalRecord)
                .where(DecisionSignalRecord.analysis_history_id == analysis_history_id)
                .order_by(
                    DecisionSignalRecord.signal_version.desc(),
                    DecisionSignalRecord.id.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row
        finally:
            session.close()
