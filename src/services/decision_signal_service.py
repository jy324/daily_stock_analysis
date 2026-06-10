# -*- coding: utf-8 -*-
"""Decision signal generation and lifecycle service (workflow B).

This module currently hosts the deterministic generation wiring (B.1). The
lifecycle state machine and daily advancement (B.2) will be added here so all
decision-signal behaviour lives in one cohesive service.
"""

from __future__ import annotations

from typing import Any, Optional

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal, build_signal_from_analysis_fields


def generate_and_persist_signal(
    db: Any,
    *,
    result: Any,
    query_id: str,
    market: Optional[str] = None,
) -> Optional[Any]:
    """Build a ``normalized_fallback`` signal for a just-saved analysis and persist it.

    Resolves the analysis row by the exact ``(query_id, code)`` pair (``query_id``
    can repeat within a batch) and reuses the persisted sniper prices as the single
    source of truth. Returns the saved record, or ``None`` when no matching analysis
    row exists. Callers must treat signal generation as best-effort: a failure here
    must never break the analysis pipeline.
    """
    code = getattr(result, "code", None)
    if not code:
        return None

    rows = db.get_analysis_history(code=code, query_id=query_id, limit=1)
    if not rows:
        return None
    history = rows[0]

    signal: DecisionSignal = build_signal_from_analysis_fields(
        code=code,
        operation_advice=getattr(result, "operation_advice", None),
        action=getattr(result, "action", None),
        confidence_level=getattr(result, "confidence_level", None),
        ideal_buy=getattr(history, "ideal_buy", None),
        secondary_buy=getattr(history, "secondary_buy", None),
        stop_loss=getattr(history, "stop_loss", None),
        take_profit=getattr(history, "take_profit", None),
        market=market,
        analysis_history_id=history.id,
    )
    return DecisionSignalRepository(db).save_signal(signal)
