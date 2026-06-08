# -*- coding: utf-8 -*-
"""A-share intelligence feature gate and runtime capability facade."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import HTTPException

from src.config import Config
from src.schemas.ashare_intelligence import AShareIntelligenceResult
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

    def get_capability(
        self,
        capability: str,
        *,
        code: Optional[str] = None,
        trade_date: Optional[str] = None,
        market_phase: Optional[str] = None,
        as_of_bucket: Optional[str] = None,
        refresh: bool = False,
        run_id: Optional[str] = None,
        config_hash: Optional[str] = None,
        is_final: bool = False,
        manager: Optional[Any] = None,
        snapshot_repository: Optional[Any] = None,
        **params: Any,
    ) -> AShareIntelligenceResult:
        self.ensure_enabled()
        self.ensure_provider_installed()
        if manager is None:
            from data_provider.intelligence.manager import AShareIntelligenceManager

            manager = AShareIntelligenceManager(self.config)

        result = manager.get_capability(
            capability,
            code=code,
            trade_date=trade_date,
            market_phase=market_phase,
            as_of_bucket=as_of_bucket,
            refresh=refresh,
            **params,
        )
        if snapshot_repository is not None and trade_date and as_of_bucket:
            snapshot_repository.save_snapshot(
                snapshot_type=capability,
                trade_date=trade_date,
                as_of=result.source.as_of,
                as_of_bucket=as_of_bucket,
                run_id=run_id,
                provider_set=result.provider,
                is_final=is_final,
                coverage_ratio=_coverage_ratio(result.coverage),
                payload=result.model_dump(mode="json"),
                schema_version="v1",
                config_hash=config_hash,
            )
        return result

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


def _coverage_ratio(coverage: Dict[str, Any]) -> Optional[float]:
    value = coverage.get("coverage_ratio")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
