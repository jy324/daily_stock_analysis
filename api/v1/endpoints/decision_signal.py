# -*- coding: utf-8 -*-
"""DecisionSignal query/management endpoints (workflow B).

Exposes the already-persisted structured signals for querying and manual
lifecycle management. Read endpoints are additive; the manual state update
reuses the lifecycle state machine and rejects illegal transitions with 409.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_database_manager
from api.v1.schemas.decision_signal import (
    DecisionSignalItem,
    DecisionSignalListResponse,
    SignalStateUpdateRequest,
)
from src.services.decision_signal_query_service import (
    DecisionSignalQueryService,
    InvalidSignalTransition,
    SignalNotFound,
)
from src.storage import DatabaseManager

router = APIRouter()


@router.get(
    "/signals",
    response_model=DecisionSignalListResponse,
    summary="查询结构化决策信号",
    description="按股票/市场/动作/状态/来源过滤分页查询持久化的 DecisionSignal。",
)
def list_signals(
    code: Optional[str] = Query(None, description="股票代码"),
    market: Optional[str] = Query(None, description="市场"),
    action: Optional[str] = Query(None, description="八态动作，如 buy/hold/sell"),
    state: Optional[str] = Query(None, description="生命周期状态；持仓中=entered"),
    source: Optional[str] = Query(None, description="llm_structured / normalized_fallback"),
    active_only: bool = Query(False, description="仅返回未终结（非 target_hit/stop_hit/expired/invalidated）信号"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> DecisionSignalListResponse:
    result = DecisionSignalQueryService(db_manager).list_signals(
        code=code, market=market, action=action, state=state,
        source=source, active_only=active_only, limit=limit, offset=offset,
    )
    return DecisionSignalListResponse(**result)


@router.get(
    "/signals/latest",
    response_model=DecisionSignalItem,
    summary="获取个股最新活跃信号",
    description="返回某只股票最近一条未终结的决策信号（当前可执行信号）。",
)
def get_latest_active_signal(
    code: str = Query(..., description="股票代码"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> DecisionSignalItem:
    item = DecisionSignalQueryService(db_manager).get_latest_active_for_code(code)
    if item is None:
        raise HTTPException(status_code=404, detail="no active signal for code")
    return DecisionSignalItem(**item)


@router.get(
    "/signals/{signal_id}",
    response_model=DecisionSignalItem,
    summary="获取单条决策信号",
)
def get_signal(
    signal_id: int,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> DecisionSignalItem:
    item = DecisionSignalQueryService(db_manager).get_signal(signal_id)
    if item is None:
        raise HTTPException(status_code=404, detail="signal not found")
    return DecisionSignalItem(**item)


@router.patch(
    "/signals/{signal_id}/state",
    response_model=DecisionSignalItem,
    summary="人工更新信号生命周期状态",
    description="按状态机校验进行人工状态流转；非法转移返回 409，目标不存在返回 404。",
)
def update_signal_state(
    signal_id: int,
    payload: SignalStateUpdateRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> DecisionSignalItem:
    service = DecisionSignalQueryService(db_manager)
    try:
        item = service.update_state(signal_id, new_state=payload.state, note=payload.note)
    except SignalNotFound:
        raise HTTPException(status_code=404, detail="signal not found")
    except InvalidSignalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return DecisionSignalItem(**item)
