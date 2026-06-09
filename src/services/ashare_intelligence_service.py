# -*- coding: utf-8 -*-
"""A-share intelligence feature gate and runtime capability facade."""

from __future__ import annotations

import importlib.util
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import yaml
from fastapi import HTTPException

from data_provider.intelligence.base import AShareProviderRateLimited, AShareProviderUnavailable
from src.config import Config
from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareSourceMetadata
from src.schemas.capabilities import AShareIntelligenceCapability

ASTOCK_DATA_PACKAGE = "astock_data"
logger = logging.getLogger(__name__)


class AShareIntelligenceService:
    """Expose safe capability checks without constructing external clients."""

    def __init__(
        self,
        config: Config,
        *,
        manager: Optional[Any] = None,
        snapshot_repository: Optional[Any] = None,
        persist_snapshots: bool = True,
    ):
        self.config = config
        self._manager = manager
        self._snapshot_repository = snapshot_repository
        self._persist_snapshots = persist_snapshots

    def capabilities(self) -> AShareIntelligenceCapability:
        enabled = bool(getattr(self.config, "ashare_intelligence_enabled", False))
        feature_config = _load_feature_config(self.config)
        return AShareIntelligenceCapability(
            enabled=enabled,
            provider_installed=is_astock_data_installed(),
            report_enabled=enabled and _nested_enabled(feature_config, "report"),
            agent_tools_enabled=enabled and _nested_enabled(feature_config, "agent_tools"),
            scoring_enabled=(
                enabled
                and bool(getattr(self.config, "ashare_scoring_enabled", False))
                and _nested_enabled(feature_config, "scoring")
            ),
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
        manager = manager or self._manager
        if manager is None:
            manager = self._build_default_manager()

        result = manager.get_capability(
            capability,
            code=code,
            trade_date=trade_date,
            market_phase=market_phase,
            as_of_bucket=as_of_bucket,
            refresh=refresh,
            **params,
        )
        if capability == "capital_flow_daily" and code:
            result = _filter_and_clip_stock_result(result, code=code, lookback=params.get("lookback"))
        if snapshot_repository is not None and trade_date and as_of_bucket:
            result = self._persist_snapshot(
                result,
                snapshot_repository=snapshot_repository,
                trade_date=trade_date,
                as_of_bucket=as_of_bucket,
                run_id=run_id,
                config_hash=config_hash,
                is_final=is_final,
            )
        elif self._persist_snapshots and trade_date and as_of_bucket and result.status in {"ok", "partial", "empty", "stale"}:
            result = self._persist_snapshot(
                result,
                snapshot_repository=self._default_snapshot_repository(),
                trade_date=trade_date,
                as_of_bucket=as_of_bucket,
                run_id=run_id,
                config_hash=config_hash,
                is_final=is_final,
            )
        return result

    def get_risk_events(
        self,
        *,
        code: str,
        trade_date: str,
        lookback: int = 30,
        refresh: bool = False,
        manager: Optional[Any] = None,
        as_of_bucket: Optional[str] = None,
    ) -> AShareIntelligenceResult:
        self.ensure_enabled()
        if manager is None:
            self.ensure_provider_installed()
            from data_provider.intelligence.manager import AShareIntelligenceManager

            manager = AShareIntelligenceManager(self.config)

        query_bucket = as_of_bucket or f"{trade_date}-api"
        start_date = _risk_events_start_date(trade_date, lookback)
        capability_queries = [
            (
                "announcements",
                {
                    "code": code,
                    "trade_date": trade_date,
                    "as_of_bucket": query_bucket,
                    "start_date": start_date,
                    "end_date": trade_date,
                    "refresh": refresh,
                },
            ),
            (
                "lockup",
                {
                    "code": code,
                    "trade_date": trade_date,
                    "as_of_bucket": query_bucket,
                    "limit": 100,
                    "refresh": refresh,
                },
            ),
            (
                "dragon_tiger_stock",
                {
                    "code": code,
                    "trade_date": trade_date,
                    "as_of_bucket": query_bucket,
                    "refresh": refresh,
                },
            ),
        ]

        results: List[AShareIntelligenceResult] = []
        unavailable: List[str] = []
        for capability, query in capability_queries:
            try:
                results.append(manager.get_capability(capability, **query))
            except AShareProviderRateLimited:
                raise
            except AShareProviderUnavailable as exc:
                unavailable.append(f"{capability}:{str(exc) or type(exc).__name__}")

        if not results:
            raise AShareProviderUnavailable("; ".join(unavailable) or "A-share risk events unavailable")

        events = _dedupe_risk_events(
            [
                event
                for result in results
                for event in _risk_events_from_result(code, result)
            ]
        )
        status = _risk_events_status(results, unavailable, bool(events))
        providers = sorted({result.provider for result in results if result.provider})
        coverage = {
            "universe_scope": "stock",
            "universe_size": 1,
            "covered_count": len(results),
            "expected_count": len(capability_queries),
            "coverage_ratio": round(len(results) / float(len(capability_queries)), 4),
            "event_count": len(events),
            "warnings": unavailable,
        }

        return AShareIntelligenceResult(
            capability="risk_events",
            provider=",".join(providers) or "unknown",
            status=status,
            data={
                "code": code,
                "trade_date": trade_date,
                "lookback": lookback,
                "events": events,
                "dedupe": {
                    "keys": [
                        "announcement_id",
                        "normalized_url",
                        "title_hash",
                        "code+date+event_type",
                    ],
                },
            },
            source=AShareSourceMetadata(
                provider=",".join(providers) or "unknown",
                status=status,
                as_of=_latest_as_of(results),
                is_partial=status == "partial",
                error="; ".join(unavailable) or None,
            ),
            coverage=coverage,
            cache_hit=all(result.cache_hit for result in results),
        )

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

    def _build_default_manager(self) -> Any:
        from data_provider.intelligence.manager import AShareIntelligenceManager

        self._manager = AShareIntelligenceManager(self.config)
        return self._manager

    def _default_snapshot_repository(self) -> Any:
        if self._snapshot_repository is None:
            from src.repositories.ashare_snapshot_repo import AShareSnapshotRepository

            self._snapshot_repository = AShareSnapshotRepository()
        return self._snapshot_repository

    def _persist_snapshot(
        self,
        result: AShareIntelligenceResult,
        *,
        snapshot_repository: Any,
        trade_date: str,
        as_of_bucket: str,
        run_id: Optional[str],
        config_hash: Optional[str],
        is_final: bool,
    ) -> AShareIntelligenceResult:
        try:
            snapshot = snapshot_repository.save_snapshot(
                snapshot_type=result.capability,
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
        except Exception as exc:
            logger.warning("A-share intelligence snapshot write failed: %s", exc)
            return result

        result.snapshot_id = getattr(snapshot, "snapshot_id", None)
        result.snapshot_revision = getattr(snapshot, "revision", None)
        return result


def is_astock_data_installed() -> bool:
    """Return whether astock_data is importable without importing it."""
    return importlib.util.find_spec(ASTOCK_DATA_PACKAGE) is not None


def is_ashare_feature_section_enabled(config: Config, section: str) -> bool:
    if not bool(getattr(config, "ashare_intelligence_enabled", False)):
        return False
    return _nested_enabled(_load_feature_config(config), section)


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


def _risk_events_start_date(trade_date: str, lookback: int) -> str:
    try:
        end = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return trade_date
    days = max(1, min(int(lookback), 120))
    return (end - timedelta(days=days)).isoformat()


def _risk_events_from_result(code: str, result: AShareIntelligenceResult) -> List[Dict[str, Any]]:
    event_type = {
        "announcements": "announcement",
        "lockup": "lockup_expiry",
        "dragon_tiger_stock": "dragon_tiger",
    }.get(result.capability, result.capability)
    return [
        _normalize_risk_event(code, event_type, item)
        for item in _iter_result_items(result.data)
        if _raw_event_matches_request_code(item, code, require_explicit_code=result.capability == "lockup")
    ]


def _iter_result_items(data: Any) -> List[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("events", "items", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_risk_event(code: str, event_type: str, item: Any) -> Dict[str, Any]:
    raw = item if isinstance(item, dict) else {"value": item}
    event_code = _normalize_stock_code(_first_value(raw, "code", "stock_code", "security_code", "SECURITY_CODE", default=code) or code)
    event_date = _first_value(raw, "date", "trade_date", "effective_date", "unlock_date")
    title = _first_value(raw, "title", "name", "reason", "event_name")
    source_id = _first_value(raw, "announcement_id", "notice_id", "id")
    normalized_url = _normalize_url(_first_value(raw, "url", "link", "announcement_url"))
    title_text = None if title is None else str(title).strip()
    return {
        "event_type": event_type,
        "code": event_code,
        "date": None if event_date is None else str(event_date),
        "title": title_text,
        "source_id": None if source_id is None else str(source_id),
        "normalized_url": normalized_url,
        "title_hash": _title_hash(title_text),
        "raw": raw,
    }


def _dedupe_risk_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for event in events:
        key = _risk_event_key(event)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _risk_event_key(event: Dict[str, Any]) -> str:
    if event.get("source_id"):
        return f"{event.get('event_type')}:id:{event['source_id']}"
    if event.get("normalized_url"):
        return f"{event.get('event_type')}:url:{event['normalized_url']}"
    if event.get("title_hash"):
        return (
            f"{event.get('event_type')}:title:{event.get('code')}:"
            f"{event.get('date')}:{event['title_hash']}"
        )
    return f"{event.get('event_type')}:{event.get('code')}:{event.get('date')}"


def _risk_events_status(
    results: List[AShareIntelligenceResult],
    unavailable: List[str],
    has_events: bool,
) -> str:
    if unavailable:
        return "partial"
    statuses = {result.status for result in results}
    if "partial" in statuses or "stale" in statuses:
        return "partial" if has_events else "stale"
    if has_events:
        return "ok"
    return "empty"


def _latest_as_of(results: List[AShareIntelligenceResult]) -> str:
    values = [result.source.as_of for result in results if result.source and result.source.as_of]
    if values:
        return max(values)
    return datetime.now(timezone.utc).isoformat()


def _first_value(raw: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return default


def _normalize_url(value: Any) -> Optional[str]:
    raw_url = str(value or "").strip()
    if not raw_url:
        return None
    parts = urlsplit(raw_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _title_hash(title: Optional[str]) -> Optional[str]:
    normalized = (title or "").strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _raw_event_matches_request_code(
    item: Any,
    request_code: str,
    *,
    require_explicit_code: bool = False,
) -> bool:
    if not isinstance(item, dict):
        return not require_explicit_code
    raw_code = _first_value(item, "code", "stock_code", "security_code", "SECURITY_CODE")
    if raw_code in (None, ""):
        return not require_explicit_code
    return _normalize_stock_code(raw_code) == _normalize_stock_code(request_code)


def _normalize_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        return text[2:]
    if "." in text:
        return text.split(".", 1)[0]
    return text


def _filter_and_clip_stock_result(
    result: AShareIntelligenceResult,
    *,
    code: str,
    lookback: Any,
) -> AShareIntelligenceResult:
    rows = _iter_result_items(result.data)
    if not rows:
        return result
    normalized_code = _normalize_stock_code(code)
    filtered = [
        row
        for row in rows
        if _raw_event_matches_request_code(row, normalized_code)
    ]
    safe_lookback = _safe_lookback(lookback)
    clipped = sorted(filtered, key=_row_trade_date, reverse=True)[:safe_lookback]
    result.data = clipped
    coverage = dict(result.coverage or {})
    coverage.update(
        {
            "filtered_code": normalized_code,
            "filtered_count": len(filtered),
            "requested_lookback": safe_lookback,
            "returned_count": len(clipped),
            "coverage_ratio": round(min(len(clipped), safe_lookback) / float(safe_lookback), 4),
        }
    )
    result.coverage = coverage
    return result


def _safe_lookback(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 120
    return max(1, min(parsed, 120))


def _row_trade_date(row: Dict[str, Any]) -> str:
    return str(_first_value(row, "trade_date", "date", "TRADE_DATE", "日期", default="") or "")
