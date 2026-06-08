# -*- coding: utf-8 -*-
"""A-share intelligence feature gate and runtime capability facade."""

from __future__ import annotations

import importlib.util
from typing import Any, Dict

from fastapi import HTTPException

from src.config import Config
from src.schemas.capabilities import AShareIntelligenceCapability

ASTOCK_DATA_PACKAGE = "astock_data"


class AShareIntelligenceService:
    """Expose safe capability checks without constructing external clients."""

    def __init__(self, config: Config):
        self.config = config

    def capabilities(self) -> AShareIntelligenceCapability:
        enabled = bool(getattr(self.config, "ashare_intelligence_enabled", False))
        return AShareIntelligenceCapability(
            enabled=enabled,
            provider_installed=is_astock_data_installed(),
            report_enabled=enabled and bool(_config_flag(self.config, "report_enabled", False)),
            agent_tools_enabled=enabled and bool(_config_flag(self.config, "agent_tools_enabled", False)),
            scoring_enabled=enabled and bool(_config_flag(self.config, "scoring_enabled", False)),
        )

    def status(self) -> Dict[str, Any]:
        self.ensure_enabled()
        self.ensure_provider_installed()
        return {
            "enabled": True,
            "status": "available",
            "provider_priority": getattr(self.config, "ashare_provider_priority", "astock_data"),
        }

    def ensure_enabled(self) -> None:
        if not bool(getattr(self.config, "ashare_intelligence_enabled", False)):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_disabled",
                    "message": "ASHARE_INTELLIGENCE_ENABLED is false.",
                },
            )

    def ensure_provider_installed(self) -> None:
        if is_astock_data_installed():
            return
        raise HTTPException(
            status_code=503,
            detail={
                "error": "dependency_unavailable",
                "message": "A-share intelligence is enabled but astock_data is not installed.",
            },
        )


def is_astock_data_installed() -> bool:
    """Return whether astock_data is importable without importing it."""
    return importlib.util.find_spec(ASTOCK_DATA_PACKAGE) is not None


def _config_flag(config: Config, name: str, default: bool) -> bool:
    return bool(getattr(config, f"ashare_{name}", default))
