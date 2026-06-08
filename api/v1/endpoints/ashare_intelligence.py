# -*- coding: utf-8 -*-
"""A-share intelligence API routes.

The routes are registered regardless of the feature flag. Runtime gates keep
the disabled behavior explicit for Web/API clients.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from api.deps import get_config_dep
from src.config import Config
from src.services.ashare_intelligence_service import AShareIntelligenceService

router = APIRouter()


@router.get("/market/ashare/status")
def ashare_intelligence_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return AShareIntelligenceService(config).status()
