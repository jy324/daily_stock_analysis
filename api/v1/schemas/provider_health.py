# -*- coding: utf-8 -*-
"""Provider health API schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ProviderRunAggregate(BaseModel):
    provider: str
    attempts: int
    success_count: int
    fallback_count: int
    stale_count: int
    success_rate_pct: Optional[float] = None
    fallback_rate_pct: Optional[float] = None
    stale_rate_pct: Optional[float] = None
    avg_latency_ms: Optional[int] = None
    last_error_type: Optional[str] = None
    last_seen_at: Optional[str] = None


class CircuitBreakerHealth(BaseModel):
    breaker: str = Field(..., description="熔断器分组：realtime / chip")
    source: str = Field(..., description="数据源名称")
    state: str = Field(..., description="closed / open / half_open")
    failures: int = 0
    seconds_since_failure: Optional[int] = None
    cooldown_remaining_seconds: Optional[int] = None


class ProviderHealthResponse(BaseModel):
    window_hours: int
    generated_at: str
    records_scanned: int = Field(..., description="窗口内含 provider 诊断的分析记录数")
    total_provider_runs: int = Field(..., description="聚合的 provider 调用次数")
    providers: List[ProviderRunAggregate] = Field(default_factory=list)
    circuit_breakers: List[CircuitBreakerHealth] = Field(default_factory=list)
