# -*- coding: utf-8 -*-
"""Decision signal generation and lifecycle service (workflow B).

Hosts the deterministic generation wiring (B.1) and the lifecycle state machine
plus daily advancement (B.2), so all decision-signal behaviour lives in one
cohesive service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Tuple

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal, build_signal_from_analysis_fields


# --- Lifecycle state machine (B.2) ---------------------------------------------

# Terminal states have no outgoing transitions.
_TERMINAL_STATES = frozenset({"target_hit", "stop_hit", "expired", "invalidated"})

# Allowed forward-only transitions. ``generated -> entered`` is permitted for
# market-entry signals that enter immediately; otherwise entry passes through
# ``waiting_entry``.
_ALLOWED_TRANSITIONS = {
    "generated": frozenset({"waiting_entry", "entered", "expired", "invalidated"}),
    "waiting_entry": frozenset({"entered", "expired", "invalidated"}),
    "entered": frozenset({"target_hit", "stop_hit", "expired", "invalidated"}),
}


class InvalidSignalTransition(Exception):
    """Raised when an illegal lifecycle transition is attempted."""


def is_terminal_state(state: str) -> bool:
    """Return whether ``state`` is a terminal lifecycle state."""
    return state in _TERMINAL_STATES


class SignalStateMachine:
    """Validates DecisionSignal lifecycle transitions (forward-only, no silent skips)."""

    @staticmethod
    def can_transition(from_state: str, to_state: str) -> bool:
        return to_state in _ALLOWED_TRANSITIONS.get(from_state, frozenset())

    @staticmethod
    def assert_transition(from_state: str, to_state: str) -> None:
        if not SignalStateMachine.can_transition(from_state, to_state):
            raise InvalidSignalTransition(f"illegal signal transition: {from_state} -> {to_state}")


# --- Daily advancement (B.2) ---------------------------------------------------


@dataclass
class SignalAdvance:
    """Outcome of advancing a signal by one trading day.

    ``to_state`` is ``None`` when the day produces no transition.
    """

    to_state: Optional[str] = None
    entered_price: Optional[float] = None
    closed_price: Optional[float] = None
    reason: str = ""


def _long_entry_fill(signal: DecisionSignal, open_price: float, low: float) -> Optional[float]:
    """Return the long-entry fill price for the day, or ``None`` if not triggered.

    A limit buy fills when the day's low reaches the level; a gap below the level
    fills at the (lower) open. ``market`` enters at the open.
    """
    entry_type = signal.entry_type
    if entry_type == "market":
        return open_price
    if entry_type == "precise" and signal.entry_price is not None:
        return min(open_price, signal.entry_price) if low <= signal.entry_price else None
    if entry_type == "zone" and signal.entry_high is not None:
        return min(open_price, signal.entry_high) if low <= signal.entry_high else None
    return None


def _long_exit(
    signal: DecisionSignal, open_price: float, high: float, low: float
) -> Tuple[Optional[str], Optional[float]]:
    """Return ``(state, fill)`` for a long exit. Stop has priority on a same-day double touch.

    A gap through the level fills worse than the level: stop fills at the lower of
    open/stop, target fills at the higher of open/target.
    """
    if signal.stop_loss is not None and low <= signal.stop_loss:
        return "stop_hit", min(open_price, signal.stop_loss)
    if signal.take_profit is not None and high >= signal.take_profit:
        return "target_hit", max(open_price, signal.take_profit)
    return None, None


def advance_signal_for_day(
    signal: DecisionSignal,
    *,
    day: date,
    ohlc: Optional[Mapping[str, float]],
) -> SignalAdvance:
    """Advance one signal by a single trading day's OHLC.

    On the entry day the signal only transitions to ``entered``; exits are
    detected from the following day so each call yields at most one validated
    transition. A halted/suspended day (``ohlc is None``) and terminal states
    produce no change.
    """
    state = signal.state
    if is_terminal_state(state) or ohlc is None:
        return SignalAdvance()

    open_price = ohlc["open"]
    high = ohlc["high"]
    low = ohlc["low"]
    close = ohlc["close"]
    expired = signal.valid_until is not None and day > signal.valid_until

    if state == "entered":
        exit_state, exit_price = _long_exit(signal, open_price, high, low)
        if exit_state is not None:
            return SignalAdvance(to_state=exit_state, closed_price=exit_price, reason=exit_state)
        if expired:
            return SignalAdvance(to_state="expired", closed_price=close, reason="expired while holding")
        return SignalAdvance()

    # state is generated or waiting_entry
    if expired:
        return SignalAdvance(to_state="expired", reason="expired before entry")

    if signal.direction == "long":
        entered_price = _long_entry_fill(signal, open_price, low)
        if entered_price is not None:
            return SignalAdvance(to_state="entered", entered_price=entered_price, reason="entry filled")
        if state == "generated" and signal.entry_type in ("precise", "zone"):
            return SignalAdvance(to_state="waiting_entry", reason="armed for entry")
        return SignalAdvance()

    # short / neutral signals have no entry simulation in a long-only system
    return SignalAdvance()


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
