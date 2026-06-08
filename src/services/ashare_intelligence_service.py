# -*- coding: utf-8 -*-
"""A-share intelligence feature gate and runtime capability facade."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

import yaml
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
        feature_config = _load_feature_config(self.config)
        return AShareIntelligenceCapability(
            enabled=enabled,
            provider_installed=is_astock_data_installed(),
            report_enabled=enabled and _nested_enabled(feature_config, "report"),
            agent_tools_enabled=enabled and _nested_enabled(feature_config, "agent_tools"),
            scoring_enabled=enabled and _nested_enabled(feature_config, "scoring"),
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


def _load_feature_config(config: Config) -> Dict[str, Any]:
    config_file = Path(str(getattr(config, "ashare_config_file", "") or ""))
    if not config_file.exists():
        return {}
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _nested_enabled(feature_config: Dict[str, Any], section: str) -> bool:
    raw_section = feature_config.get(section)
    if not isinstance(raw_section, dict):
        return False
    return bool(raw_section.get("enabled", False))
