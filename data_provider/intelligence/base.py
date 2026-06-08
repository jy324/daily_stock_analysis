# -*- coding: utf-8 -*-
"""A-share intelligence provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from src.schemas.ashare_intelligence import (
    AShareIntelligenceResult,
    AShareProviderResult,
    AShareSourceMetadata,
)


class AShareIntelligenceError(RuntimeError):
    """Base error for the A-share intelligence adapter layer."""

    error_code = "ashare_intelligence_error"


class AShareFeatureDisabled(AShareIntelligenceError):
    error_code = "feature_disabled"


class AShareProviderUnavailable(AShareIntelligenceError):
    error_code = "provider_unavailable"


class AShareProviderRateLimited(AShareIntelligenceError):
    error_code = "rate_limited"


class AShareProvider(ABC):
    """Provider adapter contract used by service, API and agent tools."""

    name: str
    schema_version: str = "v1"

    @abstractmethod
    def fetch(self, capability: str, query: Dict[str, Any]) -> AShareProviderResult:
        """Fetch one capability using provider-native rate limits."""
        raise NotImplementedError


__all__ = [
    "AShareFeatureDisabled",
    "AShareIntelligenceError",
    "AShareIntelligenceResult",
    "AShareProvider",
    "AShareProviderRateLimited",
    "AShareProviderResult",
    "AShareProviderUnavailable",
    "AShareSourceMetadata",
]
