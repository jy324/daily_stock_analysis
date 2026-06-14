# -*- coding: utf-8 -*-
"""Backtesting evaluation engine (pure logic).

This module is intentionally DB-agnostic: it operates on plain values or
objects that look like daily OHLC bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence


OVERALL_SENTINEL_CODE = "__overall__"


class DailyBarLike(Protocol):
    """Protocol for objects representing a daily OHLC bar."""

    date: date
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]


class BacktestResultLike(Protocol):
    """Protocol for objects that behave like a stored BacktestResult."""

    eval_status: str
    position_recommendation: Optional[str]
    outcome: Optional[str]
    direction_correct: Optional[bool]
    stock_return_pct: Optional[float]
    simulated_return_pct: Optional[float]
    hit_stop_loss: Optional[bool]
    hit_take_profit: Optional[bool]
    first_hit: Optional[str]
    first_hit_trading_days: Optional[int]
    operation_advice: Optional[str]


@dataclass(frozen=True)
class EvaluationConfig:
    eval_window_days: int
    neutral_band_pct: float = 2.0
    engine_version: str = "v1"
    # Trading-cost model (workflow D.1b). Only applied for the v2 engine; v1 stays gross.
    commission_rate: float = 0.0  # per side, fraction of notional
    stamp_tax_rate: float = 0.0  # sell side only, fraction of notional
    slippage_bp: float = 0.0  # per side, basis points


class BacktestEngine:
    """Long-only daily-bar backtesting engine."""

    # Operation advice keywords (Chinese + English)
    _BULLISH_KEYWORDS = (
        "买入",
        "加仓",
        "强烈买入",
        "增持",
        "建仓",
        "strong buy",
        "buy",
        "add",
    )
    _BEARISH_KEYWORDS = (
        "卖出",
        "减仓",
        "强烈卖出",
        "清仓",
        "strong sell",
        "sell",
        "reduce",
    )
    _HOLD_KEYWORDS = (
        "持有",
        "震荡观望",
        "洗盘观察",
        "持有观察",
        "hold",
        "range-bound watch",
        "shakeout watch",
        "hold and watch",
    )
    _WAIT_KEYWORDS = (
        "观望",
        "等待",
        "wait",
    )

    # Negation prefixes (trailing spaces stripped for suffix-matching against prefix text).
    # English patterns include trailing space in their canonical form; rstrip is
    # applied during matching so "do not" matches prefix "do not " or "do not".
    _NEGATION_PATTERNS = (
        "not", "don't", "do not", "no", "never", "avoid",  # English
        "不要", "不", "别", "勿", "没有",  # Chinese
    )

    _NEGATION_CONNECTOR_WORDS = (
        "建议",
        "应",
        "应当",
        "宜",
        "先",
        "再",
        "暂",
        "不必",
        "必须",
        "无需",
    )

    @classmethod
    def infer_direction_expected(cls, operation_advice: Optional[str]) -> str:
        """Infer expected direction: up/down/not_down/flat."""
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS):
            return "down"
        if cls._first_intent_position(text, cls._WAIT_KEYWORDS) is not None:
            wait_pos = cls._first_intent_position(text, cls._WAIT_KEYWORDS)
            bullish_pos = cls._first_intent_position(text, cls._BULLISH_KEYWORDS)
            hold_pos = cls._first_intent_position(text, cls._HOLD_KEYWORDS)
            if (bullish_pos is None or wait_pos < bullish_pos) and (
                hold_pos is None or wait_pos < hold_pos
            ):
                return "flat"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS):
            return "up"
        if cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "not_down"
        if cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "flat"
        return "flat"

    @classmethod
    def infer_position_recommendation(cls, operation_advice: Optional[str]) -> str:
        """Infer recommended position: long/cash (long-only system).

        Priority: bearish/wait -> cash, bullish/hold -> long, unrecognized -> cash.
        """
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS):
            return "cash"
        wait_pos = cls._first_intent_position(text, cls._WAIT_KEYWORDS)
        if wait_pos is not None:
            bullish_pos = cls._first_intent_position(text, cls._BULLISH_KEYWORDS)
            hold_pos = cls._first_intent_position(text, cls._HOLD_KEYWORDS)
            if (bullish_pos is None or wait_pos < bullish_pos) and (
                hold_pos is None or wait_pos < hold_pos
            ):
                return "cash"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS) or cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "long"
        if cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "cash"
        return "cash"

    @staticmethod
    def _is_sealed_bar(bar: Any) -> bool:
        """Whether a bar is a one-price sealed board (limit-up/down with no range).

        A sealed limit board has no intraday range (high == low), so a fill at that
        bar could not realistically have been achieved (workflow D.1c).
        """
        high = getattr(bar, "high", None)
        low = getattr(bar, "low", None)
        return high is not None and low is not None and high == low

    @staticmethod
    def _benchmark_fields(
        benchmark_code: Optional[str],
        benchmark_return_pct: Optional[float],
        simulated_return_pct: Optional[float],
    ) -> Dict[str, Any]:
        """Benchmark code/return plus the strategy's excess over the benchmark.

        Excess is the realized (simulated) return minus the benchmark return; it is
        ``None`` when either side is missing. ``benchmark_code`` is preserved even when
        the benchmark return is unavailable so the attempted benchmark is auditable.
        """
        excess = None
        if benchmark_return_pct is not None and simulated_return_pct is not None:
            excess = simulated_return_pct - benchmark_return_pct
        return {
            "benchmark_code": benchmark_code,
            "benchmark_return_pct": benchmark_return_pct,
            "excess_return_pct": excess,
        }

    @staticmethod
    def round_trip_cost_pct(config: EvaluationConfig) -> float:
        """Round-trip trading cost as a percentage of notional, for the v2 engine.

        Buy side: commission + slippage. Sell side: commission + stamp tax + slippage.
        Returns 0.0 for the v1 engine so legacy results stay gross.
        """
        if getattr(config, "engine_version", "v1") == "v1":
            return 0.0
        slippage_rate = float(config.slippage_bp) / 10000.0
        total = (
            2.0 * float(config.commission_rate)
            + float(config.stamp_tax_rate)
            + 2.0 * slippage_rate
        )
        return total * 100.0

    @classmethod
    def evaluate_single(
        cls,
        *,
        operation_advice: Optional[str],
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        config: EvaluationConfig,
        benchmark_code: Optional[str] = None,
        benchmark_return_pct: Optional[float] = None,
        start_high: Optional[float] = None,
        start_low: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate one historical analysis against forward daily bars.

        Notes:
        - Daily bars cannot determine intraday ordering. If stop-loss and
          take-profit are both touched in the same bar, we record
          first_hit="ambiguous" and assume stop-loss first for simulated exit.
        """

        if start_price is None or start_price <= 0:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "error",
            }

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        if len(forward_bars) < eval_days:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "insufficient_data",
                "eval_window_days": eval_days,
            }

        window_bars = list(forward_bars[:eval_days])
        end_close = window_bars[-1].close
        highs = [b.high for b in window_bars if b.high is not None]
        lows = [b.low for b in window_bars if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        else:
            stock_return_pct = (end_close - start_price) / start_price * 100

        direction_expected = cls.infer_direction_expected(operation_advice)
        position = cls.infer_position_recommendation(operation_advice)

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        (
            hit_stop_loss,
            hit_take_profit,
            first_hit,
            first_hit_date,
            first_hit_days,
            simulated_exit_price,
            simulated_exit_reason,
        ) = cls._evaluate_targets(
            position=position,
            stop_loss=stop_loss,
            take_profit=take_profit,
            window_bars=window_bars,
            end_close=end_close,
        )

        simulated_entry_price = start_price if position == "long" else None
        gross_return_pct: Optional[float]
        if position != "long":
            gross_return_pct = 0.0
        elif simulated_exit_price is None:
            gross_return_pct = None
        else:
            gross_return_pct = (simulated_exit_price - start_price) / start_price * 100

        # v2 trading cost applies only to an executed long round trip.
        cost_pct = cls.round_trip_cost_pct(config) if (position == "long" and gross_return_pct is not None) else 0.0
        simulated_return_pct = gross_return_pct - cost_pct if gross_return_pct is not None else None

        # Unfillable (v2): the long entry day was itself a sealed limit board (the
        # assumed fill at start_price was impossible) or the long exit landed on one.
        unfillable: Optional[bool] = None
        if config.engine_version != "v1" and position == "long":
            entry_sealed = (
                start_high is not None and start_low is not None and start_high == start_low
            )
            exit_sealed = first_hit_date is not None and any(
                b.date == first_hit_date and cls._is_sealed_bar(b) for b in window_bars
            )
            unfillable = bool(entry_sealed or exit_sealed)

        return {
            "analysis_date": analysis_date,
            "eval_window_days": eval_days,
            "engine_version": config.engine_version,
            "eval_status": "completed",
            "operation_advice": operation_advice,
            "position_recommendation": position,
            "start_price": start_price,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_expected": direction_expected,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "hit_stop_loss": hit_stop_loss,
            "hit_take_profit": hit_take_profit,
            "first_hit": first_hit,
            "first_hit_date": first_hit_date,
            "first_hit_trading_days": first_hit_days,
            "simulated_entry_price": simulated_entry_price,
            "simulated_exit_price": simulated_exit_price,
            "simulated_exit_reason": simulated_exit_reason,
            "cost_pct": cost_pct,
            "simulated_return_pct": simulated_return_pct,
            "unfillable": unfillable,
            **cls._benchmark_fields(benchmark_code, benchmark_return_pct, simulated_return_pct),
        }

    @staticmethod
    def _direction_expected_from_signal(direction: Optional[str], action: Optional[str]) -> str:
        """Map a structured signal's direction/action to the outcome direction taxonomy.

        ``hold`` is treated as ``not_down`` (the structured equivalent of "don't drop");
        otherwise direction drives expectation. No keyword inference is involved.
        """
        if action == "hold":
            return "not_down"
        if direction == "long":
            return "up"
        if direction == "short":
            return "down"
        return "flat"

    @classmethod
    def _simulate_signal_execution(
        cls,
        *,
        signal: Any,
        window: List[DailyBarLike],
        end_close: Optional[float],
    ) -> Dict[str, Any]:
        """Walk forward bars through the live lifecycle fill model to simulate execution.

        Reuses ``advance_signal_for_day`` so the backtest fill semantics (limit/zone/
        market entry with gaps, stop-priority exits, entry-day-then-exit conservatism)
        are identical to the production daily advancement. A signal whose entry never
        triggers inside the window is recorded as ``not_entered`` with zero P&L.
        """
        from src.services.decision_signal_service import advance_signal_for_day, is_terminal_state

        working = signal.model_copy(update={"state": "generated"})
        stop_loss = getattr(signal, "stop_loss", None)
        take_profit = getattr(signal, "take_profit", None)

        entered_price: Optional[float] = None
        exit_price: Optional[float] = None
        exit_reason: Optional[str] = None
        exit_date: Optional[date] = None
        exit_days: Optional[int] = None
        first_hit = "neither"
        hit_sl: Optional[bool] = None if stop_loss is None else False
        hit_tp: Optional[bool] = None if take_profit is None else False
        sealed_fill = False

        for idx, bar in enumerate(window, start=1):
            if is_terminal_state(working.state):
                break
            if bar.open is None or bar.high is None or bar.low is None:
                continue  # halted/suspended day
            ohlc = {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
            advance = advance_signal_for_day(working, day=bar.date, ohlc=ohlc)
            if advance.to_state is None:
                continue
            working = working.model_copy(update={"state": advance.to_state})
            if advance.entered_price is not None:
                entered_price = advance.entered_price
                if cls._is_sealed_bar(bar):
                    sealed_fill = True
            if advance.closed_price is not None:
                if cls._is_sealed_bar(bar):
                    sealed_fill = True
                exit_price = advance.closed_price
                exit_days = idx
                exit_date = bar.date
                if advance.to_state == "stop_hit":
                    hit_sl = True
                    # A same-day touch of both levels is ambiguous on daily bars.
                    if take_profit is not None and bar.high is not None and bar.high >= take_profit:
                        hit_tp = True
                        first_hit = "ambiguous"
                        exit_reason = "ambiguous_stop_loss"
                    else:
                        first_hit = "stop_loss"
                        exit_reason = "stop_loss"
                elif advance.to_state == "target_hit":
                    hit_tp = True
                    first_hit = "take_profit"
                    exit_reason = "take_profit"
                elif advance.to_state == "expired":
                    exit_reason = "expired"
                break

        if entered_price is None:
            return {
                "simulated_entry_price": None,
                "simulated_exit_price": None,
                "simulated_exit_reason": "not_entered",
                "simulated_return_pct": 0.0,
                "hit_stop_loss": hit_sl,
                "hit_take_profit": hit_tp,
                "first_hit": "not_entered",
                "first_hit_date": None,
                "first_hit_trading_days": None,
                "entered": False,
                "sealed_fill": False,
            }

        if exit_price is None:
            exit_price = end_close
            exit_reason = "window_end"
            first_hit = "neither"
            exit_date = None
            exit_days = None

        simulated_return_pct = (
            None if exit_price is None else (exit_price - entered_price) / entered_price * 100
        )
        return {
            "simulated_entry_price": entered_price,
            "simulated_exit_price": exit_price,
            "simulated_exit_reason": exit_reason,
            "simulated_return_pct": simulated_return_pct,
            "hit_stop_loss": hit_sl,
            "hit_take_profit": hit_tp,
            "first_hit": first_hit,
            "first_hit_date": exit_date,
            "first_hit_trading_days": exit_days,
            "entered": True,
            "sealed_fill": sealed_fill,
        }

    @classmethod
    def evaluate_from_decision_signal(
        cls,
        *,
        signal: Any,
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        config: EvaluationConfig,
        benchmark_code: Optional[str] = None,
        benchmark_return_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate a historical analysis using its structured DecisionSignal.

        Direction and position come straight from the signal (no keyword inference),
        and execution is simulated through the live lifecycle fill model. The stock
        return / direction-correctness split mirrors :meth:`evaluate_single`, while
        ``simulated_return_pct`` reflects the realistic entry fill rather than assuming
        entry at ``start_price``.
        """
        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        direction = getattr(signal, "direction", "neutral")
        action = getattr(signal, "action", None)
        position = "long" if direction == "long" else "cash"
        direction_expected = cls._direction_expected_from_signal(direction, action)

        base = {
            "analysis_date": analysis_date,
            "engine_version": config.engine_version,
            "operation_advice": getattr(signal, "operation_advice", None),
            "position_recommendation": position,
            "direction_expected": direction_expected,
            "signal_based": True,
            "source": getattr(signal, "source", None),
        }

        if start_price is None or start_price <= 0:
            return {**base, "eval_status": "error"}

        if len(forward_bars) < eval_days:
            return {**base, "eval_status": "insufficient_data", "eval_window_days": eval_days}

        window = list(forward_bars[:eval_days])
        end_close = window[-1].close
        highs = [b.high for b in window if b.high is not None]
        lows = [b.low for b in window if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None
        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        else:
            stock_return_pct = (end_close - start_price) / start_price * 100

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        if position != "long":
            sim = {
                "simulated_entry_price": None,
                "simulated_exit_price": None,
                "simulated_exit_reason": "cash",
                "simulated_return_pct": 0.0,
                "hit_stop_loss": None,
                "hit_take_profit": None,
                "first_hit": "not_applicable",
                "first_hit_date": None,
                "first_hit_trading_days": None,
                "entered": False,
            }
        else:
            sim = cls._simulate_signal_execution(signal=signal, window=window, end_close=end_close)

        # v2 trading cost applies only to an executed long round trip.
        cost_pct = 0.0
        if sim.get("entered") and sim.get("simulated_return_pct") is not None:
            cost_pct = cls.round_trip_cost_pct(config)
            sim["simulated_return_pct"] = sim["simulated_return_pct"] - cost_pct

        # Unfillable (sealed limit board) is a v2-only realism flag.
        sealed_fill = bool(sim.pop("sealed_fill", False))
        unfillable = sealed_fill if config.engine_version != "v1" else None

        return {
            "unfillable": unfillable,
            **base,
            "eval_window_days": eval_days,
            "eval_status": "completed",
            "start_price": start_price,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": getattr(signal, "stop_loss", None),
            "take_profit": getattr(signal, "take_profit", None),
            "cost_pct": cost_pct,
            **sim,
            **cls._benchmark_fields(benchmark_code, benchmark_return_pct, sim.get("simulated_return_pct")),
        }

    @classmethod
    def compute_summary(
        cls,
        *,
        results: Iterable[BacktestResultLike],
        scope: str,
        code: Optional[str],
        eval_window_days: int,
        engine_version: str,
    ) -> Dict[str, Any]:
        """Aggregate BacktestResult rows into summary metrics."""
        results_list = list(results)

        total = len(results_list)
        completed = [r for r in results_list if (r.eval_status or "") == "completed"]
        insufficient_count = sum(1 for r in results_list if (r.eval_status or "") == "insufficient_data")

        long_count = sum(1 for r in completed if (r.position_recommendation or "") == "long")
        cash_count = sum(1 for r in completed if (r.position_recommendation or "") == "cash")

        win_count = sum(1 for r in completed if (r.outcome or "") == "win")
        loss_count = sum(1 for r in completed if (r.outcome or "") == "loss")
        neutral_count = sum(1 for r in completed if (r.outcome or "") == "neutral")

        direction_denominator = sum(1 for r in completed if r.direction_correct is not None)
        direction_numerator = sum(1 for r in completed if r.direction_correct is True)
        direction_accuracy_pct = (
            round(direction_numerator / direction_denominator * 100, 2) if direction_denominator else None
        )

        win_loss_denominator = win_count + loss_count
        win_rate_pct = round(win_count / win_loss_denominator * 100, 2) if win_loss_denominator else None
        neutral_rate_pct = round(neutral_count / len(completed) * 100, 2) if completed else None

        avg_stock_return_pct = cls._average([r.stock_return_pct for r in completed])
        avg_simulated_return_pct = cls._average([r.simulated_return_pct for r in completed])

        stop_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_stop_loss is not None
        ]
        stop_loss_trigger_rate = (
            round(sum(1 for r in stop_applicable if r.hit_stop_loss is True) / len(stop_applicable) * 100, 2)
            if stop_applicable
            else None
        )

        take_profit_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_take_profit is not None
        ]
        take_profit_trigger_rate = (
            round(
                sum(1 for r in take_profit_applicable if r.hit_take_profit is True) / len(take_profit_applicable) * 100,
                2,
            )
            if take_profit_applicable
            else None
        )

        any_target_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long"
            and (r.hit_stop_loss is not None or r.hit_take_profit is not None)
        ]
        ambiguous_rate = (
            round(
                sum(1 for r in any_target_applicable if (r.first_hit or "") == "ambiguous")
                / len(any_target_applicable)
                * 100,
                2,
            )
            if any_target_applicable
            else None
        )
        avg_days_to_first_hit = cls._average(
            [
                float(r.first_hit_trading_days)
                for r in any_target_applicable
                if r.first_hit_trading_days is not None and (r.first_hit or "") in ("stop_loss", "take_profit", "ambiguous")
            ]
        )

        advice_breakdown = cls._compute_advice_breakdown(completed)
        diagnostics = cls._compute_diagnostics(results_list)
        risk_metrics = cls.compute_risk_metrics(completed)

        return {
            "scope": scope,
            "code": code,
            "eval_window_days": int(eval_window_days),
            "engine_version": engine_version,
            "total_evaluations": total,
            "completed_count": len(completed),
            "insufficient_count": insufficient_count,
            "long_count": long_count,
            "cash_count": cash_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "direction_accuracy_pct": direction_accuracy_pct,
            "win_rate_pct": win_rate_pct,
            "neutral_rate_pct": neutral_rate_pct,
            "avg_stock_return_pct": avg_stock_return_pct,
            "avg_simulated_return_pct": avg_simulated_return_pct,
            "stop_loss_trigger_rate": stop_loss_trigger_rate,
            "take_profit_trigger_rate": take_profit_trigger_rate,
            "ambiguous_rate": ambiguous_rate,
            "avg_days_to_first_hit": avg_days_to_first_hit,
            "advice_breakdown": advice_breakdown,
            "diagnostics": diagnostics,
            "max_drawdown_pct": risk_metrics["max_drawdown_pct"],
            "volatility_pct": risk_metrics["volatility_pct"],
            "sharpe": risk_metrics["sharpe"],
            "sortino": risk_metrics["sortino"],
            "calmar": risk_metrics["calmar"],
            "profit_factor": risk_metrics["profit_factor"],
            "payoff_ratio": risk_metrics["payoff_ratio"],
            "holding_period_stats": risk_metrics["holding_period_stats"],
        }

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _matches_intent(cls, text: str, keywords: Sequence[str]) -> bool:
        """Check if text expresses the intent of any keyword, accounting for negation.

        Tier 1: exact match (covers clean labels like "买入", "hold").
        Tier 2: substring match with negation guard.
        Keywords are assumed to be lowercase (matching _normalize_text output).
        """
        return cls._first_intent_position(text, keywords) is not None

    @classmethod
    def _first_intent_position(cls, text: str, keywords: Sequence[str]) -> Optional[int]:
        """Return the earliest match position for intent keywords, or None."""
        if not text:
            return None

        best_pos: Optional[int] = None

        for kw in keywords:
            if not kw:
                continue
            if text == kw:
                return 0

            keyword = kw.lower().strip()
            if not keyword:
                continue

            # Use word-boundary matching for ASCII keywords to avoid
            # false positives such as "watch" matching "wait".
            if bool(re.search(r"[a-z]", keyword)):
                for match in re.finditer(
                    rf"(?<![a-zA-Z0-9_]){re.escape(keyword)}(?![a-zA-Z0-9_])",
                    text,
                ):
                    if not cls._is_negated(text[: match.start()], keyword):
                        pos = match.start()
                        if best_pos is None or pos < best_pos:
                            best_pos = pos
                            break
                    continue

            # For non-ASCII terms (Chinese), use substring matching to keep
            # natural language phrasings like "建议买入" effective.
            if re.search(r"[\u4e00-\u9fff]", keyword):
                start = 0
                while True:
                    match_idx = text.find(keyword, start)
                    if match_idx < 0:
                        break
                    if not cls._is_negated(text[:match_idx], keyword):
                        if best_pos is None or match_idx < best_pos:
                            best_pos = match_idx
                        break
                    start = match_idx + len(keyword)
                continue

        return best_pos

    @classmethod
    def _is_negated(cls, prefix: str, keyword: str) -> bool:
        """Check if the prefix text indicates negation for a candidate intent."""
        stripped = prefix.rstrip()
        target = (keyword or "").lower().strip()
        if not target:
            return False

        if any(stripped.endswith(neg) for neg in cls._NEGATION_PATTERNS):
            return True

        # 限定“否定 + 动作动词”匹配，避免将“条件位否定”误伤核心建议意图。
        lookback = stripped[-12:]
        for neg in cls._NEGATION_PATTERNS:
            if not neg:
                continue
            neg_idx = lookback.rfind(neg)
            if neg_idx < 0:
                continue

            suffix_gap = lookback[neg_idx + len(neg):].strip()
            if not suffix_gap:
                return True
            if any(ch in suffix_gap for ch in "，,。；;:!?！？"):
                continue

            if cls._contains_keyword(suffix_gap, target):
                return True

            # Keep English short-gap behavior where negation words are followed by
            # connector words such as "to" (e.g. "not to sell").
            if not any(ch >= "\u4e00" and ch <= "\u9fff" for ch in suffix_gap):
                if len(suffix_gap) <= 6:
                    return True
                continue

            if cls._is_negation_connector_gap(suffix_gap):
                return True

        return False

    @classmethod
    def _contains_keyword(cls, text: str, keyword: str) -> bool:
        """Check whether *keyword* exists in text with intent-aware boundaries."""
        if not text or not keyword:
            return False
        if bool(re.search(r"[a-z]", keyword)):
            return bool(re.search(rf"(?<![a-zA-Z0-9_]){re.escape(keyword)}(?![a-zA-Z0-9_])", text))
        return keyword in text

    @classmethod
    def _is_negation_connector_gap(cls, gap: str) -> bool:
        """Whether a short Chinese negation gap is still a valid negation bridge."""
        compact = re.sub(r"[\s,，。；;:!?！？]", "", gap).strip()
        if not compact:
            return True
        return compact in cls._NEGATION_CONNECTOR_WORDS

    @classmethod
    def _classify_outcome(
        cls,
        *,
        stock_return_pct: Optional[float],
        direction_expected: str,
        neutral_band_pct: float,
    ) -> tuple[Optional[str], Optional[bool]]:
        if stock_return_pct is None:
            return None, None

        band = abs(float(neutral_band_pct))
        r = float(stock_return_pct)

        if direction_expected == "up":
            if r >= band:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        if direction_expected == "down":
            if r <= -band:
                return "win", True
            if r >= band:
                return "loss", False
            return "neutral", None

        if direction_expected == "not_down":
            if r >= 0:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        # flat
        if abs(r) <= band:
            return "win", True
        return "loss", False

    @classmethod
    def _evaluate_targets(
        cls,
        *,
        position: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        window_bars: List[DailyBarLike],
        end_close: Optional[float],
    ) -> tuple[
        Optional[bool],
        Optional[bool],
        str,
        Optional[date],
        Optional[int],
        Optional[float],
        str,
    ]:
        if position != "long":
            return (
                None,
                None,
                "not_applicable",
                None,
                None,
                None,
                "cash",
            )

        has_any_target = stop_loss is not None or take_profit is not None
        if not has_any_target:
            return (
                None,
                None,
                "neither",
                None,
                None,
                end_close,
                "window_end",
            )

        hit_sl: Optional[bool] = None if stop_loss is None else False
        hit_tp: Optional[bool] = None if take_profit is None else False
        first_hit = "neither"
        first_hit_date: Optional[date] = None
        first_hit_days: Optional[int] = None
        exit_price: Optional[float] = end_close
        exit_reason = "window_end"

        for idx, bar in enumerate(window_bars, start=1):
            low = bar.low
            high = bar.high
            stop_hit = stop_loss is not None and low is not None and low <= stop_loss
            tp_hit = take_profit is not None and high is not None and high >= take_profit

            if stop_hit:
                hit_sl = True
            if tp_hit:
                hit_tp = True

            if not stop_hit and not tp_hit:
                continue

            first_hit_date = bar.date
            first_hit_days = idx

            if stop_hit and tp_hit:
                first_hit = "ambiguous"
                exit_price = stop_loss
                exit_reason = "ambiguous_stop_loss"
                break

            if stop_hit:
                first_hit = "stop_loss"
                exit_price = stop_loss
                exit_reason = "stop_loss"
                break

            first_hit = "take_profit"
            exit_price = take_profit
            exit_reason = "take_profit"
            break

        return (
            hit_sl,
            hit_tp,
            first_hit,
            first_hit_date,
            first_hit_days,
            exit_price,
            exit_reason,
        )

    @classmethod
    def compute_risk_metrics(cls, results: Iterable[Any], *, risk_free_pct: float = 0.0) -> Dict[str, Any]:
        """Compute risk/return metrics over completed per-trade simulated returns.

        Inputs are result-like rows exposing ``eval_status``, ``simulated_return_pct``,
        ``analysis_date`` and ``first_hit_trading_days``. Only ``completed`` rows with a
        non-null ``simulated_return_pct`` contribute, ordered by ``analysis_date`` for the
        compounded equity curve. All return figures are percentages. Metrics that are
        undefined for the sample (e.g. volatility with <2 trades, profit factor with no
        losses) are ``None`` rather than a misleading zero.
        """
        rows = [
            r
            for r in results
            if (getattr(r, "eval_status", "") or "") == "completed"
            and getattr(r, "simulated_return_pct", None) is not None
        ]
        rows.sort(key=lambda r: (getattr(r, "analysis_date", None) is None, getattr(r, "analysis_date", None)))
        returns = [float(r.simulated_return_pct) for r in rows]
        n = len(returns)

        empty = {
            "max_drawdown_pct": 0.0,
            "volatility_pct": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "profit_factor": None,
            "payoff_ratio": None,
            "holding_period_stats": cls._holding_period_stats(results),
        }
        if n == 0:
            return empty

        mean_r = sum(returns) / n
        excess_mean = mean_r - float(risk_free_pct)

        volatility = None
        sharpe = None
        if n >= 2:
            variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
            volatility = math.sqrt(variance)
            if volatility > 0:
                sharpe = excess_mean / volatility

        downside_sq_mean = sum((min(0.0, r)) ** 2 for r in returns) / n
        downside_dev = math.sqrt(downside_sq_mean)
        sortino = excess_mean / downside_dev if downside_dev > 0 else None

        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in returns:
            equity *= 1.0 + r / 100.0
            if equity > peak:
                peak = equity
            elif peak > 0:
                drawdown = (peak - equity) / peak
                if drawdown > max_dd:
                    max_dd = drawdown
        max_drawdown_pct = max_dd * 100.0
        total_return_pct = (equity - 1.0) * 100.0
        calmar = total_return_pct / max_drawdown_pct if max_drawdown_pct > 0 else None

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        gross_loss = abs(sum(losses))
        profit_factor = sum(wins) / gross_loss if losses else None
        payoff_ratio = (
            (sum(wins) / len(wins)) / (abs(sum(losses)) / len(losses)) if wins and losses else None
        )

        return {
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "volatility_pct": round(volatility, 4) if volatility is not None else None,
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "sortino": round(sortino, 4) if sortino is not None else None,
            "calmar": round(calmar, 4) if calmar is not None else None,
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
            "holding_period_stats": cls._holding_period_stats(results),
        }

    @staticmethod
    def _holding_period_stats(results: Iterable[Any]) -> Dict[str, Any]:
        """Aggregate ``first_hit_trading_days`` over completed rows that reached a target/stop."""
        days = [
            int(getattr(r, "first_hit_trading_days"))
            for r in results
            if (getattr(r, "eval_status", "") or "") == "completed"
            and getattr(r, "first_hit_trading_days", None) is not None
        ]
        if not days:
            return {}
        return {
            "count": len(days),
            "avg": round(sum(days) / len(days), 4),
            "min": min(days),
            "max": max(days),
        }

    @staticmethod
    def _average(values: Iterable[Optional[float]]) -> Optional[float]:
        items = [float(v) for v in values if v is not None]
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    @staticmethod
    def _compute_advice_breakdown(results: List[BacktestResultLike]) -> Dict[str, Any]:
        breakdown: Dict[str, Dict[str, int]] = {}
        for row in results:
            raw_advice = row.operation_advice
            advice = (raw_advice if isinstance(raw_advice, str) else str(raw_advice or "")).strip() or "(unknown)"
            bucket = breakdown.setdefault(advice, {"total": 0, "win": 0, "loss": 0, "neutral": 0})
            bucket["total"] += 1
            outcome = (row.outcome or "").strip()
            if outcome in ("win", "loss", "neutral"):
                bucket[outcome] += 1

        enriched: Dict[str, Any] = {}
        for advice, bucket in breakdown.items():
            win = bucket["win"]
            loss = bucket["loss"]
            denom = win + loss
            win_rate = round(win / denom * 100, 2) if denom else None
            enriched[advice] = {**bucket, "win_rate_pct": win_rate}
        return enriched

    @staticmethod
    def _compute_diagnostics(results: List[BacktestResultLike]) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        first_hit_counts: Dict[str, int] = {}
        for row in results:
            status = (row.eval_status or "").strip() or "(unknown)"
            status_counts[status] = status_counts.get(status, 0) + 1
            first_hit = (row.first_hit or "").strip() or "(none)"
            first_hit_counts[first_hit] = first_hit_counts.get(first_hit, 0) + 1
        return {
            "eval_status": status_counts,
            "first_hit": first_hit_counts,
        }
