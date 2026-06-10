# -*- coding: utf-8 -*-
"""DecisionSignal persistence repository (workflow B)."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select

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
