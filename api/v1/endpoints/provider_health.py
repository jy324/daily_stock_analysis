# -*- coding: utf-8 -*-
"""Provider health observability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from api.v1.schemas.provider_health import ProviderHealthResponse
from src.services.provider_health_service import ProviderHealthService
from src.storage import DatabaseManager

router = APIRouter()


@router.get(
    "/providers/health",
    response_model=ProviderHealthResponse,
    summary="数据源健康聚合",
    description="聚合最近窗口内已持久化的 provider 调用诊断（成功率/降级/陈旧/延迟）"
    "与实时熔断器状态，作为数据源可观测面板的统一入口。",
)
def get_provider_health(
    window_hours: int = Query(24, ge=1, le=168, description="聚合时间窗口（小时）"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> ProviderHealthResponse:
    snapshot = ProviderHealthService(db_manager).get_provider_health(window_hours=window_hours)
    return ProviderHealthResponse(**snapshot)
