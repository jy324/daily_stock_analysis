# -*- coding: utf-8 -*-
"""Market Light snapshot service for structured alerts."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import desc

from src.core.market_review import MARKET_REVIEW_HISTORY_CODE, MARKET_REVIEW_REPORT_TYPE
from src.market_analyzer import MarketAnalyzer
from src.schemas.market_light import MarketLightSnapshot
from src.storage import AnalysisHistory, DatabaseManager


logger = logging.getLogger(__name__)

MARKET_LIGHT_REGIONS = frozenset({"cn", "hk", "us"})
MARKET_LIGHT_HISTORY_BATCH_SIZE = 100


def normalize_market_region(region: str) -> str:
    value = str(region or "").strip().lower()
    if value not in MARKET_LIGHT_REGIONS:
        raise ValueError(f"market target must be one of cn, hk, us: {region}")
    return value


def build_current_snapshot(region: str) -> Dict[str, Any]:
    """Build the current structured Market Light snapshot without LLM review."""

    normalized_region = normalize_market_region(region)
    analyzer = MarketAnalyzer(region=normalized_region)
    overview = analyzer.get_market_overview()
    return analyzer.build_market_light_snapshot(overview)


def load_previous_snapshot(
    region: str,
    *,
    before_trade_date: str,
    db_manager: Optional[DatabaseManager] = None,
    limit: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Load the latest persisted Market Light snapshot before ``before_trade_date``.

    Legacy market-review history rows without ``market_light_snapshots[region]`` are
    skipped while scanning newer rows.
    """

    normalized_region = normalize_market_region(region)
    cutoff = str(before_trade_date or "").strip()
    if not cutoff:
        return None

    db = db_manager or DatabaseManager.get_instance()
    best_trade_date: Optional[str] = None
    best_snapshot: Optional[Dict[str, Any]] = None
    invalid_target_error: Optional[Exception] = None

    with db.get_session() as session:
        query = (
            session.query(AnalysisHistory)
            .filter(
                AnalysisHistory.code == MARKET_REVIEW_HISTORY_CODE,
                AnalysisHistory.report_type == MARKET_REVIEW_REPORT_TYPE,
            )
            .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
        )
        if limit is not None:
            query = query.limit(limit)
        for row in query.yield_per(MARKET_LIGHT_HISTORY_BATCH_SIZE):
            snapshot = _extract_region_snapshot(row.context_snapshot, normalized_region)
            if snapshot is None:
                continue
            trade_date = str(snapshot.get("trade_date") or "").strip()
            if not trade_date or trade_date >= cutoff:
                continue
            if best_trade_date is None or trade_date > best_trade_date:
                best_trade_date = trade_date
                best_snapshot = None
                invalid_target_error = None
            elif trade_date < best_trade_date:
                continue
            try:
                candidate = MarketLightSnapshot.model_validate(snapshot).model_dump()
            except Exception as exc:
                logger.warning(
                    "invalid persisted market light snapshot: row_id=%s region=%s trade_date=%s error=%s",
                    getattr(row, "id", "?"),
                    normalized_region,
                    trade_date,
                    exc,
                )
                if best_snapshot is None:
                    invalid_target_error = exc
                continue
            if best_snapshot is None:
                best_snapshot = candidate

    if best_snapshot is not None:
        return best_snapshot
    if best_trade_date is not None and invalid_target_error is not None:
        raise ValueError(
            f"invalid persisted market light snapshot for {normalized_region} on {best_trade_date}"
        ) from invalid_target_error
    return None


def _extract_region_snapshot(raw_context_snapshot: Any, region: str) -> Optional[Dict[str, Any]]:
    if not raw_context_snapshot:
        return None
    try:
        payload = (
            json.loads(raw_context_snapshot)
            if isinstance(raw_context_snapshot, str)
            else raw_context_snapshot
        )
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    snapshots = payload.get("market_light_snapshots")
    if not isinstance(snapshots, dict):
        return None
    snapshot = snapshots.get(region)
    return snapshot if isinstance(snapshot, dict) else None


MARKET_TURNOVER_BASELINE_LOOKBACK = 20
MARKET_TURNOVER_BASELINE_MIN_SAMPLES = 5


def load_recent_turnover_baseline(
    region: str,
    *,
    before_trade_date: str,
    lookback: int = MARKET_TURNOVER_BASELINE_LOOKBACK,
    min_samples: int = MARKET_TURNOVER_BASELINE_MIN_SAMPLES,
    db_manager: Optional[DatabaseManager] = None,
) -> Optional[float]:
    """Mean two-market turnover (亿) from recent persisted reviews before ``before_trade_date``.

    Reuses the persisted market-review ``context_snapshot.market_review_payload`` (single
    region or ``markets[region]``) ``breadth.total_amount``. Returns ``None`` when fewer than
    ``min_samples`` usable trading days are found, so the caller keeps the absolute-caliber
    turnover description rather than comparing against a thin/empty baseline.
    """
    normalized_region = normalize_market_region(region)
    cutoff = str(before_trade_date or "").strip()
    if not cutoff:
        return None

    db = db_manager or DatabaseManager.get_instance()
    amounts: List[float] = []
    seen_dates: set[str] = set()

    with db.get_session() as session:
        query = (
            session.query(AnalysisHistory)
            .filter(
                AnalysisHistory.code == MARKET_REVIEW_HISTORY_CODE,
                AnalysisHistory.report_type == MARKET_REVIEW_REPORT_TYPE,
            )
            .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
            # Scan a little wider than `lookback` to skip same-day, legacy or
            # other-region rows without prematurely starving the sample.
            .limit(max(lookback * 3, lookback))
        )
        for row in query.yield_per(MARKET_LIGHT_HISTORY_BATCH_SIZE):
            parsed = _extract_region_turnover(row.context_snapshot, normalized_region, cutoff)
            if parsed is None:
                continue
            trade_date, amount = parsed
            if trade_date in seen_dates:
                continue
            seen_dates.add(trade_date)
            amounts.append(amount)
            if len(amounts) >= lookback:
                break

    if len(amounts) < max(1, min_samples):
        return None
    return sum(amounts) / len(amounts)


def _extract_region_turnover(
    raw_context_snapshot: Any,
    region: str,
    cutoff: str,
) -> Optional[tuple[str, float]]:
    """Return ``(trade_date, total_amount)`` for ``region`` from a persisted review row.

    Skips rows on/after ``cutoff``, other regions, and rows without positive breadth turnover.
    """
    if not raw_context_snapshot:
        return None
    try:
        payload = (
            json.loads(raw_context_snapshot)
            if isinstance(raw_context_snapshot, str)
            else raw_context_snapshot
        )
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    review_payload = payload.get("market_review_payload")
    if not isinstance(review_payload, dict):
        return None

    region_payload: Optional[Dict[str, Any]] = None
    markets = review_payload.get("markets")
    if isinstance(markets, dict):
        candidate = markets.get(region)
        if isinstance(candidate, dict):
            region_payload = candidate
    elif str(review_payload.get("region") or "").strip().lower() == region:
        region_payload = review_payload
    if not isinstance(region_payload, dict):
        return None

    trade_date = str(region_payload.get("date") or "").strip()
    if not trade_date or trade_date >= cutoff:
        return None

    breadth = region_payload.get("breadth")
    if not isinstance(breadth, dict):
        return None
    try:
        amount = float(breadth.get("total_amount"))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return trade_date, amount
