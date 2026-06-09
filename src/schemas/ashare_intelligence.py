# -*- coding: utf-8 -*-
"""A-share intelligence provider and cache schemas."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

AShareDataStatus = Literal["ok", "partial", "stale", "empty", "unavailable"]


class AShareSourceMetadata(BaseModel):
    provider: str
    status: AShareDataStatus
    as_of: str
    is_partial: bool = False
    error: Optional[str] = None


class AShareProviderResult(BaseModel):
    status: AShareDataStatus
    data: Any
    source: AShareSourceMetadata
    coverage: Dict[str, Any] = Field(default_factory=dict)


class AShareIntelligenceResult(AShareProviderResult):
    capability: str
    provider: str
    cache_hit: bool = False
    snapshot_id: Optional[str] = None
    snapshot_revision: Optional[int] = None
    stale_reason: Optional[str] = None
