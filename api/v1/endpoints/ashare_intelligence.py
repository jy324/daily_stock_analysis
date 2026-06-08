# -*- coding: utf-8 -*-
"""A-share intelligence API routes.

The routes are registered regardless of the feature flag. Runtime gates keep
the disabled behavior explicit for Web/API clients.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_config_dep
from data_provider.intelligence.base import AShareProviderRateLimited, AShareProviderUnavailable
from src.config import Config
from src.schemas.ashare_intelligence import AShareIntelligenceResult
from src.services.ashare_intelligence_service import AShareIntelligenceService

router = APIRouter()


@router.get("/market/ashare/status")
def ashare_intelligence_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return AShareIntelligenceService(config).status()


@router.get("/market/ashare/sector-flow", response_model=AShareIntelligenceResult)
def ashare_sector_flow(
    trade_date: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    refresh: bool = False,
    config: Config = Depends(get_config_dep),
) -> AShareIntelligenceResult:
    query_date = trade_date or date.today().isoformat()
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
    query_date = trade_date or date.today().isoformat()
    return _service_result(
        AShareIntelligenceService(config),
        "capital_flow_daily",
        code=code,
        trade_date=query_date,
        as_of_bucket=f"{query_date}-api",
        lookback=lookback,
        refresh=refresh,
    )


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
