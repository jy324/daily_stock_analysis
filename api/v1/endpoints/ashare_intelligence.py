# -*- coding: utf-8 -*-
"""A-share intelligence API routes.

The routes are registered regardless of the feature flag. Runtime gates keep
the disabled behavior explicit for Web/API clients.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from api.deps import get_config_dep
from api.v1.schemas.analysis import MarketReviewAccepted, MarketReviewRequest
from data_provider.intelligence.base import AShareProviderRateLimited, AShareProviderUnavailable
from src.config import Config
from src.core.market_review_lock import (
    release_market_review_lock as _release_market_review_lock,
    try_acquire_market_review_lock as _try_acquire_market_review_lock,
)
from src.core.trading_calendar import is_market_open
from src.report_language import normalize_report_language
from src.schemas.ashare_intelligence import AShareIntelligenceResult
from src.services.ashare_intelligence_service import AShareIntelligenceService
from src.services.task_queue import get_task_queue

router = APIRouter()


@router.get("/market/ashare/status")
def ashare_intelligence_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return AShareIntelligenceService(config).status()


@router.post(
    "/market/ashare/review",
    response_model=MarketReviewAccepted,
    status_code=202,
)
def ashare_market_review(
    request: Optional[MarketReviewRequest] = Body(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    config: Config = Depends(get_config_dep),
) -> MarketReviewAccepted:
    service = AShareIntelligenceService(config)
    service.ensure_enabled()
    service.ensure_provider_installed()

    request = request or MarketReviewRequest()
    task_queue = get_task_queue()
    task_id = _ashare_review_task_id(idempotency_key)
    idempotency_key_hash = _idempotency_key_hash(idempotency_key)
    request_body_hash = _market_review_request_hash(request)
    if task_id:
        existing_task = task_queue.get_task(task_id)
        if existing_task is not None:
            existing_body_hash = getattr(existing_task, "request_body_hash", None)
            if existing_body_hash and existing_body_hash != request_body_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "idempotency_conflict",
                        "message": "Idempotency-Key was already used with a different request body.",
                    },
                )
            return MarketReviewAccepted(
                status="accepted",
                message="A-share market review task already accepted for this Idempotency-Key.",
                send_notification=request.send_notification,
                task_id=existing_task.task_id,
                trace_id=_task_trace_id(existing_task),
            )
    else:
        task_id = uuid.uuid4().hex

    runtime_config = _with_request_report_language(config, getattr(request, "report_language", None))
    lock_token = _try_acquire_market_review_lock(runtime_config)
    if lock_token is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_market_review", "message": "A-share market review is already running."},
        )

    try:
        task = task_queue.submit_background_task(
            lambda: _run_ashare_market_review_background(
                send_notification=request.send_notification,
                lock_token=lock_token,
                config=runtime_config,
                query_id=task_id,
            ),
            stock_code="market_review",
            stock_name="A股大盘复盘",
            message="A-share market review task accepted",
            task_id=task_id,
            trace_id=task_id,
            idempotency_key_hash=idempotency_key_hash,
            request_body_hash=request_body_hash,
        )
    except Exception:
        _release_market_review_lock(lock_token)
        raise

    return MarketReviewAccepted(
        status="accepted",
        message="A-share market review task accepted.",
        send_notification=request.send_notification,
        task_id=task.task_id,
        trace_id=_task_trace_id(task),
    )


@router.get("/market/ashare/sector-flow", response_model=AShareIntelligenceResult)
def ashare_sector_flow(
    trade_date: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    refresh: bool = False,
    config: Config = Depends(get_config_dep),
) -> AShareIntelligenceResult:
    query_date = _resolve_ashare_trade_date(trade_date)
    return _service_result(
        AShareIntelligenceService(config),
        "sector_fund_flow",
        trade_date=query_date,
        as_of_bucket=f"{query_date}-api",
        limit=limit,
        refresh=refresh,
    )


@router.get("/stocks/{code}/capital-flow", response_model=AShareIntelligenceResult)
def ashare_stock_capital_flow(
    code: str,
    trade_date: Optional[str] = None,
    lookback: int = Query(120, ge=1, le=120),
    refresh: bool = False,
    config: Config = Depends(get_config_dep),
) -> AShareIntelligenceResult:
    query_date = _resolve_ashare_trade_date(trade_date)
    return _service_result(
        AShareIntelligenceService(config),
        "capital_flow_daily",
        code=code,
        trade_date=query_date,
        as_of_bucket=f"{query_date}-api",
        lookback=lookback,
        refresh=refresh,
    )


@router.get("/stocks/{code}/risk-events", response_model=AShareIntelligenceResult)
def ashare_stock_risk_events(
    code: str,
    trade_date: Optional[str] = None,
    lookback: int = Query(30, ge=1, le=120),
    refresh: bool = False,
    config: Config = Depends(get_config_dep),
) -> AShareIntelligenceResult:
    query_date = _resolve_ashare_trade_date(trade_date)
    try:
        return AShareIntelligenceService(config).get_risk_events(
            code=code,
            trade_date=query_date,
            lookback=lookback,
            refresh=refresh,
        )
    except AShareProviderRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "message": str(exc) or "A-share provider rate limited."},
        ) from exc
    except AShareProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "provider_unavailable", "message": str(exc) or "A-share provider unavailable."},
        ) from exc


def _service_result(
    service: AShareIntelligenceService,
    capability: str,
    **kwargs: Any,
) -> AShareIntelligenceResult:
    try:
        return service.get_capability(capability, **kwargs)
    except AShareProviderRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "message": str(exc) or "A-share provider rate limited."},
        ) from exc
    except AShareProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "provider_unavailable", "message": str(exc) or "A-share provider unavailable."},
        ) from exc


def _ashare_review_task_id(idempotency_key: Optional[str]) -> Optional[str]:
    normalized = (idempotency_key or "").strip()
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"ashare-review-{digest}"


def _idempotency_key_hash(idempotency_key: Optional[str]) -> Optional[str]:
    normalized = (idempotency_key or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _market_review_request_hash(request: MarketReviewRequest) -> str:
    payload = request.model_dump(mode="json", by_alias=False)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _with_request_report_language(config: Config, report_language: Optional[str]) -> Config:
    normalized = normalize_report_language(report_language, default="")
    if not normalized:
        return config
    scoped_config = copy.copy(config)
    scoped_config.report_language = normalized
    return scoped_config


def _run_ashare_market_review_background(
    *,
    send_notification: bool,
    lock_token: Any,
    config: Config,
    query_id: str,
) -> Any:
    from api.v1.endpoints.analysis import _run_market_review_background

    return _run_market_review_background(
        send_notification=send_notification,
        override_region="cn",
        lock_token=lock_token,
        config=config,
        query_id=query_id,
    )


def _task_trace_id(task: Any) -> Optional[str]:
    trace_id = getattr(task, "trace_id", None)
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id
    task_id = getattr(task, "task_id", None)
    if isinstance(task_id, str) and task_id.strip():
        return task_id
    return None


def _default_ashare_trade_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _resolve_ashare_trade_date(trade_date: Optional[str]) -> str:
    if not trade_date:
        return _default_ashare_trade_date()
    raw = str(trade_date).strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_trade_date",
                "message": "trade_date must be a valid YYYY-MM-DD date.",
            },
        ) from exc
    if raw != parsed.isoformat():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_trade_date",
                "message": "trade_date must use YYYY-MM-DD format.",
            },
        )
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if parsed > today:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "future_trade_date",
                "message": "trade_date cannot be in the future.",
            },
        )
    if not is_market_open("cn", parsed):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "non_trading_day",
                "message": "trade_date is not an A-share trading day.",
            },
        )
    return parsed.isoformat()
