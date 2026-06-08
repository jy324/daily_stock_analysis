# -*- coding: utf-8 -*-
"""A-share deterministic scoring schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AShareSignalScore(BaseModel):
    score: Optional[float] = None
    confidence: float = 0.0
    coverage: float = 0.0
    version: str = "ashare-scoring-v1"
    features: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    risk_pressure_score: Optional[float] = None


class ASharePersistenceScore(BaseModel):
    value: Optional[float] = None
    window: int
    version: str = "ashare-scoring-v1"
    warnings: List[str] = Field(default_factory=list)
