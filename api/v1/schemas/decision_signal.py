# -*- coding: utf-8 -*-
"""DecisionSignal query/management API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.schemas.decision_signal import SignalState


class DecisionSignalItem(BaseModel):
    id: int
    code: str
    market: Optional[str] = None
    analysis_history_id: Optional[int] = None
    signal_version: int
    generated_at: Optional[str] = None
    source: Optional[str] = None
    operation_advice: Optional[str] = None
    direction: str
    action: Optional[str] = None
    position_size_pct: Optional[float] = None
    confidence_level: Optional[str] = None
    confidence_score: Optional[int] = None
    entry_type: str
    entry_price: Optional[float] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    invalidation_conditions: List[str] = Field(default_factory=list)
    applicable_phases: List[str] = Field(default_factory=list)
    quality_constraints: Dict[str, Any] = Field(default_factory=dict)
    state: str
    state_history: List[Dict[str, Any]] = Field(default_factory=list)
    entered_date: Optional[str] = None
    entered_price: Optional[float] = None
    closed_date: Optional[str] = None
    closed_price: Optional[float] = None
    created_at: Optional[str] = None


class DecisionSignalListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[DecisionSignalItem] = Field(default_factory=list)


class SignalStateUpdateRequest(BaseModel):
    state: SignalState = Field(..., description="目标生命周期状态")
    note: Optional[str] = Field(None, max_length=500, description="人工备注，写入状态流转历史")
