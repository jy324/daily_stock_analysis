# -*- coding: utf-8 -*-
"""Lazy adapter for the external astock_data package."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Any, Dict

from .base import AShareProvider, AShareProviderResult, AShareProviderUnavailable, AShareSourceMetadata


class AStockDataProvider(AShareProvider):
    name = "astock_data"
    schema_version = "v1"

    def __init__(self, client: Any):
        self._client = client

    def fetch(self, capability: str, query: Dict[str, Any]) -> AShareProviderResult:
        code = query.get("code")
        trade_date = query.get("trade_date")
        limit = query.get("limit")

        if capability == "capital_flow_minute":
            raw = self._client.stock_fund_flow_minute(str(code))
        elif capability == "capital_flow_daily":
            raw = self._client.stock_fund_flow_120d(str(code))
        elif capability == "sector_fund_flow":
            raw = self._client.sector_fund_flow(limit=limit)
        elif capability == "dragon_tiger_market":
            raw = self._client.daily_dragon_tiger(date=trade_date, limit=limit)
        elif capability == "dragon_tiger_stock":
            raw = self._client.dragon_tiger_board(str(code), date=trade_date)
        elif capability == "announcements":
            raw = self._client.cninfo_announcements(
                code=str(code),
                start_date=query.get("start_date") or trade_date,
                end_date=query.get("end_date") or trade_date,
            )
        elif capability == "lockup":
            raw = self._client.lockup_expiry(date=trade_date, limit=limit)
        else:
            raise AShareProviderUnavailable(f"Unsupported A-share capability: {capability}")

        return _coerce_provider_result(raw)


def create_astock_data_provider() -> AStockDataProvider:
    """Create the provider while keeping astock_data out of module import time."""
    astock_data = import_module("astock_data")
    client_factory = getattr(astock_data, "EastmoneyClient", None)
    if client_factory is None:
        eastmoney = import_module("astock_data.eastmoney")
        client_factory = getattr(eastmoney, "EastmoneyClient")
    return AStockDataProvider(client_factory())


def _coerce_provider_result(raw: Any) -> AShareProviderResult:
    status = str(_get(raw, "status", "unavailable"))
    if status not in {"ok", "partial", "empty", "unavailable"}:
        status = "unavailable"
    source_raw = _get(raw, "source", None)
    source = AShareSourceMetadata(
        provider=str(_get(source_raw, "provider", "astock_data")),
        status=status,
        as_of=str(_get(source_raw, "as_of", _utc_now())),
        is_partial=bool(_get(source_raw, "is_partial", False)),
        error=_get(source_raw, "error", None),
    )
    return AShareProviderResult(
        status=status,
        data=_get(raw, "data", None),
        source=source,
        coverage=dict(_get(raw, "coverage", {}) or {}),
    )


def _get(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
