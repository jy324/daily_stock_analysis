# -*- coding: utf-8 -*-
"""Structured decision signal schema and its lifecycle (workflow B).

``DecisionSignal`` upgrades the free-text ``operation_advice`` into an
executable, verifiable signal that reports, alerts, backtests and position
analysis can all consume from one structured contract. It deliberately reuses
the existing eight-state :data:`~src.schemas.decision_action.DecisionAction`
taxonomy rather than inventing a parallel one, and derives a coarse
:data:`SignalDirection` aligned with the existing long-only backtest semantics
(see ``src/core/backtest_engine.py``).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.decision_action import DecisionAction, normalize_decision_action

# Coarse price-direction view used by evaluation/backtest. ``long`` expects the
# price to rise (or stay constructive), ``short`` expects weakness, ``neutral``
# expresses no actionable view.
SignalDirection = Literal["long", "short", "neutral"]

# Bullish/bearish/no-view groupings of the eight-state action taxonomy. Kept in
# sync with the backtest keyword inference so a structured signal and a legacy
# text-inferred signal evaluate the same way.
_LONG_ACTIONS: frozenset[str] = frozenset({"buy", "add", "hold"})
_SHORT_ACTIONS: frozenset[str] = frozenset({"sell", "reduce"})


def direction_from_action(action: Optional[str]) -> SignalDirection:
    """Map an eight-state :data:`DecisionAction` to a coarse signal direction.

    Bullish actions (buy/add/hold) are ``long``; bearish actions (sell/reduce)
    are ``short``; observational actions (watch/avoid/alert) and any unknown or
    missing value are ``neutral``.
    """
    if action in _LONG_ACTIONS:
        return "long"
    if action in _SHORT_ACTIONS:
        return "short"
    return "neutral"


# How the entry price is expressed. ``precise`` carries a single ``entry_price``;
# ``zone`` carries an ``entry_low``/``entry_high`` band; ``market`` means enter at
# the prevailing price; ``none`` means no actionable entry (e.g. observation only
# or when a data-quality policy forbids a precise entry).
EntryType = Literal["precise", "zone", "market", "none"]

# Lifecycle states. The transitions are enforced by the state machine in
# workflow B.2; the schema only records the current state.
SignalState = Literal[
    "generated",
    "waiting_entry",
    "entered",
    "target_hit",
    "stop_hit",
    "expired",
    "invalidated",
]

# How the signal was produced: directly from a structured LLM payload, or
# normalized from the legacy free-text fields as a deterministic fallback.
SignalSource = Literal["llm_structured", "normalized_fallback"]

ConfidenceLevel = Literal["high", "medium", "low"]


class DecisionSignal(BaseModel):
    """A structured, executable decision signal derived from one analysis.

    Designed to be additive: nothing is required beyond ``code`` and
    ``direction``/``entry_type`` so it can be produced for every analysis,
    including degraded ones (where ``entry_type`` is forced to ``none``).
    """

    model_config = ConfigDict(validate_assignment=True)

    # Identity / provenance
    code: str
    market: Optional[str] = None
    analysis_history_id: Optional[int] = None
    signal_version: int = Field(1, ge=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: SignalSource = "llm_structured"
    operation_advice: Optional[str] = None

    # Decision
    direction: SignalDirection
    action: Optional[DecisionAction] = None
    position_size_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    confidence_level: Optional[ConfidenceLevel] = None
    confidence_score: Optional[int] = Field(None, ge=0, le=100)

    # Entry / exit
    entry_type: EntryType = "none"
    entry_price: Optional[float] = Field(None, gt=0.0)
    entry_low: Optional[float] = Field(None, gt=0.0)
    entry_high: Optional[float] = Field(None, gt=0.0)
    stop_loss: Optional[float] = Field(None, gt=0.0)
    take_profit: Optional[float] = Field(None, gt=0.0)

    # Validity window
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None

    # Constraints / context
    invalidation_conditions: List[str] = Field(default_factory=list)
    applicable_phases: List[str] = Field(default_factory=list)
    quality_constraints: Dict[str, Any] = Field(default_factory=dict)

    # Lifecycle
    state: SignalState = "generated"

    @model_validator(mode="after")
    def _validate_entry_and_window(self) -> "DecisionSignal":
        if self.entry_type == "precise" and self.entry_price is None:
            raise ValueError("entry_type 'precise' requires entry_price")
        if self.entry_type == "zone":
            if self.entry_low is None or self.entry_high is None:
                raise ValueError("entry_type 'zone' requires entry_low and entry_high")
            if self.entry_low > self.entry_high:
                raise ValueError("entry_low must not exceed entry_high")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must not precede valid_from")
        return self


_CONFIDENCE_ALIASES: Dict[str, ConfidenceLevel] = {
    "高": "high",
    "中": "medium",
    "低": "low",
    "high": "high",
    "medium": "medium",
    "low": "low",
}


def _normalize_confidence_level(value: Optional[str]) -> Optional[ConfidenceLevel]:
    if value is None:
        return None
    # ``str.lower()`` is a no-op on the Chinese aliases, so one lowercase lookup
    # handles both the zh (高/中/低) and en (high/medium/low) forms.
    return _CONFIDENCE_ALIASES.get(str(value).strip().lower())


def build_signal_from_analysis_fields(
    *,
    code: str,
    operation_advice: Optional[str],
    action: Optional[str] = None,
    confidence_level: Optional[str] = None,
    ideal_buy: Optional[float] = None,
    secondary_buy: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    market: Optional[str] = None,
    analysis_history_id: Optional[int] = None,
) -> DecisionSignal:
    """Build a ``normalized_fallback`` signal from the existing analysis fields.

    Deterministic and LLM-independent: the explicit eight-state ``action`` wins
    when present, otherwise the action is inferred from ``operation_advice`` via
    :func:`normalize_decision_action`. Entry prices are only attached to ``long``
    signals (this is a long-only advisory system); ``stop_loss``/``take_profit``
    always pass through for evaluation.
    """
    resolved_action = normalize_decision_action(action) if action else normalize_decision_action(operation_advice)
    direction = direction_from_action(resolved_action)

    entry_type: EntryType = "none"
    entry_price: Optional[float] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None

    if direction == "long":
        prices = sorted(p for p in (ideal_buy, secondary_buy) if p is not None and p > 0)
        if len(prices) >= 2:
            entry_type = "zone"
            entry_low, entry_high = prices[0], prices[-1]
        elif len(prices) == 1:
            entry_type = "precise"
            entry_price = prices[0]

    return DecisionSignal(
        code=code,
        market=market,
        analysis_history_id=analysis_history_id,
        source="normalized_fallback",
        operation_advice=operation_advice,
        direction=direction,
        action=resolved_action,
        confidence_level=_normalize_confidence_level(confidence_level),
        entry_type=entry_type,
        entry_price=entry_price,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss if stop_loss and stop_loss > 0 else None,
        take_profit=take_profit if take_profit and take_profit > 0 else None,
    )


__all__ = [
    "SignalDirection",
    "EntryType",
    "SignalState",
    "SignalSource",
    "ConfidenceLevel",
    "DecisionAction",
    "DecisionSignal",
    "direction_from_action",
    "build_signal_from_analysis_fields",
]
