# -*- coding: utf-8 -*-
"""Lazy adapter for the external astock_data package."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from typing import Any, Dict, Iterable, List, Optional

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
        lookback = query.get("lookback")

        if capability == "capital_flow_minute":
            raw = self._client.get_stock_intraday_flow(str(code), trade_date=trade_date)
        elif capability == "capital_flow_daily":
            raw = self._client.get_stock_flow_history(
                str(code),
                trade_date=trade_date,
                lookback=_safe_positive_int(lookback, default=120, maximum=120),
            )
        elif capability == "sector_fund_flow":
            raw = self._client.get_sector_flow_ranking(
                trade_date=trade_date,
                limit=_safe_positive_int(limit, default=10, maximum=50),
            )
        elif capability == "dragon_tiger_market":
            raw = self._client.get_market_dragon_tiger(
                trade_date=trade_date,
                limit=_safe_positive_int(limit, default=100, maximum=500) if limit is not None else None,
            )
        elif capability == "dragon_tiger_stock":
            raw = self._client.get_stock_dragon_tiger(str(code), trade_date=trade_date)
        elif capability == "announcements":
            raw = self._client.get_announcements(
                str(code),
                start_date=query.get("start_date") or trade_date,
                end_date=query.get("end_date") or trade_date,
            )
        elif capability == "lockup":
            raw = self._client.get_lockup_events(
                str(code),
                trade_date=trade_date,
                limit=_safe_positive_int(limit, default=100, maximum=500) if limit is not None else None,
            )
        else:
            raise AShareProviderUnavailable(f"Unsupported A-share capability: {capability}")

        return _postprocess_result(capability, query, _coerce_provider_result(raw))


def create_astock_data_provider() -> AStockDataProvider:
    """Create the provider while keeping astock_data out of module import time."""
    astock_data = import_module("astock_data")
    client_factory = getattr(astock_data, "AStockDataClient", None)
    if client_factory is None:
        raise AShareProviderUnavailable("astock_data.AStockDataClient is not available")
    return AStockDataProvider(client_factory())


def _coerce_provider_result(raw: Any) -> AShareProviderResult:
    status = str(_get(raw, "status", _get(_get(raw, "meta", None), "status", "unavailable")))
    if status not in {"ok", "partial", "empty", "unavailable"}:
        status = "unavailable"
    source_raw = _get(raw, "source", _get(raw, "meta", None))
    warnings = _get(source_raw, "warnings", None)
    error = _get(source_raw, "error", None)
    if error is None and warnings:
        error = "; ".join(str(item) for item in warnings)
    source = AShareSourceMetadata(
        provider=str(_get(source_raw, "provider", "astock_data")),
        status=status,
        as_of=str(_get(source_raw, "as_of", _utc_now())),
        is_partial=bool(_get(source_raw, "is_partial", False)),
        error=error,
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


def _postprocess_result(
    capability: str,
    query: Dict[str, Any],
    result: AShareProviderResult,
) -> AShareProviderResult:
    code = _normalize_code(query.get("code"))
    data = result.data
    coverage = dict(result.coverage or {})
    if capability in {"capital_flow_daily", "lockup", "dragon_tiger_stock", "announcements"} and code:
        rows = _rows(data)
        if rows:
            filtered = _filter_rows_by_code(rows, code, require_explicit_code=capability == "lockup")
            data = filtered
            coverage["filtered_code"] = code
            coverage["filtered_count"] = len(filtered)

    if capability == "capital_flow_daily":
        lookback = _safe_positive_int(query.get("lookback"), default=120, maximum=120)
        rows = _rows(data)
        if rows:
            data = _clip_rows_by_lookback(rows, lookback)
            coverage["requested_lookback"] = lookback
            coverage["returned_count"] = len(data)
            coverage["coverage_ratio"] = round(min(len(data), lookback) / float(lookback), 4)

    return AShareProviderResult(
        status=result.status,
        data=data,
        source=result.source,
        coverage=coverage,
    )


def _rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("rows", "items", "events", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _filter_rows_by_code(
    rows: Iterable[Dict[str, Any]],
    code: str,
    *,
    require_explicit_code: bool = False,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        row_code = _normalize_code(_first_present(row, "code", "stock_code", "security_code", "SECURITY_CODE", "股票代码"))
        if (not row_code and not require_explicit_code) or row_code == code:
            filtered.append(row)
    return filtered


def _clip_rows_by_lookback(rows: List[Dict[str, Any]], lookback: int) -> List[Dict[str, Any]]:
    def sort_key(row: Dict[str, Any]) -> str:
        value = _first_present(row, "trade_date", "date", "TRADE_DATE", "日期")
        return "" if value in (None, "") else str(value)

    return sorted(rows, key=sort_key, reverse=True)[:lookback]


def _first_present(row: Dict[str, Any], *keys: str) -> Optional[Any]:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        return text[2:]
    if "." in text:
        return text.split(".", 1)[0]
    return text


def _safe_positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))
