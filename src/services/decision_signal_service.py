# -*- coding: utf-8 -*-
"""Decision signal generation and lifecycle service (workflow B).

Hosts the deterministic generation wiring (B.1) and the lifecycle state machine
plus daily advancement (B.2), so all decision-signal behaviour lives in one
cohesive service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_signal import DecisionSignal, build_signal_from_analysis_fields
from src.schemas.quality_policy import QualityPolicyDecision

logger = logging.getLogger(__name__)

# Confidence levels ordered tightest -> loosest, for cap comparison.
_CONFIDENCE_RANK: Dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# A callable that returns one day's OHLC for a code, or ``None`` if unavailable
# (e.g. suspended/halted). Decouples advancement from the data-fetching layer.
OhlcProvider = Callable[[str, date], Optional[Mapping[str, float]]]


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


def advance_active_signals(
    db: Any,
    *,
    today: date,
    ohlc_provider: OhlcProvider,
    repo: Optional[DecisionSignalRepository] = None,
) -> Dict[str, int]:
    """Advance every active (non-terminal) signal by one trading day.

    Each signal is advanced independently: a fetch/advance failure for one signal
    is logged and isolated so the rest still progress. Returns a summary with
    ``scanned`` / ``transitioned`` / ``errors`` counts.
    """
    repo = repo or DecisionSignalRepository(db)
    summary = {"scanned": 0, "transitioned": 0, "errors": 0}

    for record in repo.get_active_signals():
        summary["scanned"] += 1
        try:
            signal = record.to_signal()
            ohlc = ohlc_provider(record.code, today)
            advance = advance_signal_for_day(signal, day=today, ohlc=ohlc)
            if advance.to_state is None:
                continue

            SignalStateMachine.assert_transition(record.state, advance.to_state)
            repo.update_lifecycle(
                record.id,
                state=advance.to_state,
                entered_date=today if advance.entered_price is not None else None,
                entered_price=advance.entered_price,
                closed_date=today if advance.closed_price is not None else None,
                closed_price=advance.closed_price,
                history_entry={
                    "from": record.state,
                    "to": advance.to_state,
                    "day": today.isoformat(),
                    "reason": advance.reason,
                },
            )
            summary["transitioned"] += 1
        except Exception as exc:  # isolate per-signal failures
            summary["errors"] += 1
            logger.warning(
                "决策信号推进失败 (id=%s, code=%s): %s",
                getattr(record, "id", None),
                getattr(record, "code", None),
                exc,
            )

    return summary


def build_daily_ohlc_provider(fetcher_manager: Any) -> OhlcProvider:
    """Build an OHLC provider backed by the data layer's daily bars.

    Returns the most recent daily bar's OHLC for a code, or ``None`` when no data
    is available (suspended/delisted), which advancement treats as a halt.
    """

    def provider(code: str, day: date) -> Optional[Mapping[str, float]]:
        frame, _ = fetcher_manager.get_daily_data(code, days=5)
        if frame is None or getattr(frame, "empty", True):
            return None
        last = frame.iloc[-1]
        return {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
        }

    return provider


def run_decision_signal_advancement(
    db: Any = None,
    *,
    fetcher_manager: Any = None,
    today: Optional[date] = None,
) -> Dict[str, int]:
    """Daily entry point: advance active signals using live daily bars.

    Defaults wire the live ``DatabaseManager`` and ``DataFetcherManager`` so the
    scheduler can call this with no arguments; callers should guard it so a
    failure never breaks the daily run.
    """
    if db is None:
        from src.storage import DatabaseManager

        db = DatabaseManager.get_instance()
    if fetcher_manager is None:
        from data_provider import DataFetcherManager

        fetcher_manager = DataFetcherManager()
    return advance_active_signals(
        db,
        today=today or date.today(),
        ohlc_provider=build_daily_ohlc_provider(fetcher_manager),
    )


def constrain_signal_with_quality_policy(
    signal: DecisionSignal,
    decision: Optional[QualityPolicyDecision],
) -> DecisionSignal:
    """Apply data-quality policy constraints to a signal's fields (workflow C.2).

    - ``observation_only`` makes the signal non-executable: direction is forced to
      ``neutral`` and any entry is cleared.
    - ``prohibit_precise_entry`` downgrades a ``precise`` entry to ``none`` (a zone
      entry is permitted and left intact).
    - ``cap_confidence`` lowers the confidence level toward the tightest cap; it
      never raises an already-tighter level.

    What changed (and which policies caused it) is recorded in
    ``quality_constraints`` for auditability. Returns the original signal unchanged
    when no constraint applies.
    """
    if decision is None or decision.is_empty:
        return signal

    updates: Dict[str, Any] = {}
    effects: list[str] = []

    if decision.observation_only:
        updates.update(
            direction="neutral",
            entry_type="none",
            entry_price=None,
            entry_low=None,
            entry_high=None,
        )
        effects.append("observation_only: 信号置为不可执行（direction=neutral, entry=none）")
    elif decision.prohibit_precise_entry and signal.entry_type == "precise":
        updates.update(entry_type="none", entry_price=None)
        effects.append("prohibit_precise_entry: precise 入场降级为 none")

    cap = decision.confidence_cap
    if cap is not None and signal.confidence_level is not None:
        if _CONFIDENCE_RANK.get(signal.confidence_level, 2) > _CONFIDENCE_RANK.get(cap, 2):
            updates["confidence_level"] = cap
            effects.append(f"cap_confidence: 置信度收敛为 {cap}")

    if not effects:
        return signal

    quality_constraints = dict(signal.quality_constraints or {})
    quality_constraints.update(
        {
            "policies": decision.matched_policy_ids,
            "actions": decision.action_types,
            "reasons": decision.reasons,
            "effects": effects,
        }
    )
    updates["quality_constraints"] = quality_constraints
    return signal.model_copy(update=updates)


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

    signal = _apply_quality_policy_from_history(signal, history)
    return DecisionSignalRepository(db).save_signal(signal)


def _apply_quality_policy_from_history(signal: DecisionSignal, history: Any) -> DecisionSignal:
    """Evaluate data-quality policies from the analysis snapshot and constrain the signal.

    Best-effort and fully guarded: any failure (missing snapshot, unreadable policy
    file, evaluation error) leaves the unconstrained signal intact so signal
    generation never breaks the analysis pipeline.
    """
    try:
        from src.analysis_context_pack_overview import extract_analysis_context_pack_overview
        from src.market_phase_summary import extract_market_phase_summary
        from src.services.quality_policy_service import QualityPolicyService

        snapshot = getattr(history, "context_snapshot", None)
        overview = extract_analysis_context_pack_overview(snapshot)
        phase_summary = extract_market_phase_summary(snapshot)
        phase = phase_summary.get("phase") if isinstance(phase_summary, Mapping) else None
        decision = QualityPolicyService().evaluate(overview, phase=phase)
        return constrain_signal_with_quality_policy(signal, decision)
    except Exception as exc:
        logger.warning("决策信号质量策略约束失败，保留未约束信号: %s", exc)
        return signal
