# -*- coding: utf-8 -*-
"""Runtime capability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_config_dep
from src.config import Config
from src.schemas.capabilities import RuntimeCapabilities
from src.services.ashare_intelligence_service import AShareIntelligenceService

router = APIRouter()


@router.get("/capabilities", response_model=RuntimeCapabilities)
def get_capabilities(config: Config = Depends(get_config_dep)) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        ashare_intelligence=AShareIntelligenceService(config).capabilities(),
    )
