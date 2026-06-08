# -*- coding: utf-8 -*-
"""A-share intelligence provider manager with deterministic cache boundaries."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Mapping, Optional

import yaml

from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareProviderResult

from .base import (
    AShareFeatureDisabled,
    AShareProvider,
    AShareProviderRateLimited,
    AShareProviderUnavailable,
    AShareSourceMetadata,
)

ProviderFactory = Callable[[], AShareProvider]

SUPPORTED_CAPABILITIES = {
    "capital_flow_minute",
    "capital_flow_daily",
    "sector_fund_flow",
    "dragon_tiger_market",
    "dragon_tiger_stock",
    "announcements",
    "lockup",
}

DEFAULT_TTL_SECONDS = {
    "capital_flow_minute": 300,
    "capital_flow_daily": 3600,
    "sector_fund_flow": 600,
    "dragon_tiger_market": 86400,
    "dragon_tiger_stock": 86400,
    "announcements": 3600,
    "lockup": 86400,
}


class AShareIntelligenceManager:
    """Read-through manager for memory cache, file cache and provider adapters."""

    def __init__(
        self,
        config: Any,
        *,
        provider_factories: Optional[Mapping[str, ProviderFactory]] = None,
        ttl_overrides: Optional[Mapping[str, int]] = None,
    ):
        self.config = config
        self._provider_factories = dict(provider_factories or _default_provider_factories())
        self._providers: Dict[str, AShareProvider] = {}
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
        self._ttl_seconds = self._load_ttl_seconds(ttl_overrides)

    def get_capability(
        self,
        capability: str,
        *,
        code: Optional[str] = None,
        trade_date: Optional[str] = None,
        market_phase: Optional[str] = None,
        as_of_bucket: Optional[str] = None,
        refresh: bool = False,
        **params: Any,
    ) -> AShareIntelligenceResult:
        if not bool(getattr(self.config, "ashare_intelligence_enabled", False)):
            raise AShareFeatureDisabled("A-share intelligence is disabled")
        if capability not in SUPPORTED_CAPABILITIES:
            raise AShareProviderUnavailable(f"Unsupported A-share capability: {capability}")

        provider_name = self._provider_name()
        query = _clean_query(
            {
                "code": code,
                "trade_date": trade_date,
                "market_phase": market_phase,
                "as_of_bucket": as_of_bucket,
                **params,
            }
        )
        cache_key = self._cache_key(provider_name, capability, query)
        stale_payload: Optional[Dict[str, Any]] = None

        if not refresh:
            memory_payload = self._read_memory_cache(cache_key)
            if memory_payload is not None:
                return self._result_from_cache(memory_payload, cache_hit=True)

            file_payload = self._read_file_cache(cache_key)
            if file_payload is not None:
                if self._is_fresh(file_payload):
                    self._write_memory_cache(cache_key, file_payload)
                    return self._result_from_cache(file_payload, cache_hit=True)
                stale_payload = file_payload
        else:
            stale_payload = self._read_file_cache(cache_key)

        try:
            provider_result = self._provider(provider_name).fetch(capability, query)
        except AShareProviderRateLimited:
            raise
        except Exception as exc:
            if stale_payload is not None:
                return self._stale_result(stale_payload, str(exc) or type(exc).__name__)
            if isinstance(exc, AShareProviderUnavailable):
                raise
            raise AShareProviderUnavailable(str(exc) or type(exc).__name__) from exc

        result = self._result_from_provider(provider_name, capability, provider_result)
        if result.status in {"ok", "partial", "empty"}:
            payload = self._cache_payload(cache_key, result)
            self._write_memory_cache(cache_key, payload)
            self._write_file_cache(cache_key, payload)
        return result

    def _provider_name(self) -> str:
        priority = str(getattr(self.config, "ashare_provider_priority", "astock_data") or "astock_data")
        for name in [part.strip() for part in priority.split(",") if part.strip()]:
            if name in self._provider_factories:
                return name
        raise AShareProviderUnavailable("No configured A-share provider is available")

    def _provider(self, name: str) -> AShareProvider:
        with self._lock:
            if name not in self._providers:
                self._providers[name] = self._provider_factories[name]()
            return self._providers[name]

    def _cache_key(self, provider: str, capability: str, query: Dict[str, Any]) -> str:
        key_payload = {
            "provider": provider,
            "capability": capability,
            "code": query.get("code"),
            "trade_date": query.get("trade_date"),
            "market_phase": query.get("market_phase"),
            "as_of_bucket": query.get("as_of_bucket"),
            "schema_version": "v1",
            "query": query,
        }
        serialized = json.dumps(key_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        cache_dir = Path(str(getattr(self.config, "ashare_cache_dir", "./data/ashare_cache")))
        return cache_dir / cache_key[:2] / f"{cache_key}.json"

    def _read_memory_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        payload = self._memory_cache.get(cache_key)
        if payload is None or not self._is_fresh(payload):
            return None
        return payload

    def _write_memory_cache(self, cache_key: str, payload: Dict[str, Any]) -> None:
        self._memory_cache[cache_key] = payload

    def _read_file_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        cache_path = self._cache_path(cache_key)
        if not cache_path.exists():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_file_cache(self, cache_key: str, payload: Dict[str, Any]) -> None:
        cache_path = self._cache_path(cache_key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        tmp_path.replace(cache_path)

    def _is_fresh(self, payload: Dict[str, Any]) -> bool:
        expires_at = payload.get("expires_at")
        try:
            return float(expires_at) > time.time()
        except (TypeError, ValueError):
            return False

    def _result_from_provider(
        self,
        provider: str,
        capability: str,
        provider_result: AShareProviderResult,
    ) -> AShareIntelligenceResult:
        return AShareIntelligenceResult(
            capability=capability,
            provider=provider,
            status=provider_result.status,
            data=provider_result.data,
            source=provider_result.source,
            coverage=provider_result.coverage,
            cache_hit=False,
        )

    def _result_from_cache(self, payload: Dict[str, Any], *, cache_hit: bool) -> AShareIntelligenceResult:
        result_payload = dict(payload["result"])
        result_payload["cache_hit"] = cache_hit
        return AShareIntelligenceResult(**result_payload)

    def _stale_result(self, payload: Dict[str, Any], reason: str) -> AShareIntelligenceResult:
        result_payload = dict(payload["result"])
        source_payload = dict(result_payload["source"])
        source_payload["status"] = "stale"
        source_payload["error"] = reason
        result_payload.update(
            {
                "status": "stale",
                "source": source_payload,
                "cache_hit": False,
                "stale_reason": reason,
            }
        )
        return AShareIntelligenceResult(**result_payload)

    def _cache_payload(self, cache_key: str, result: AShareIntelligenceResult) -> Dict[str, Any]:
        ttl = max(0, int(self._ttl_seconds.get(result.capability, 0)))
        now = time.time()
        return {
            "cache_key": cache_key,
            "created_at": now,
            "expires_at": now + ttl,
            "result": result.model_dump(mode="json"),
        }

    def _load_ttl_seconds(self, ttl_overrides: Optional[Mapping[str, int]]) -> Dict[str, int]:
        ttl_seconds = dict(DEFAULT_TTL_SECONDS)
        config_file = Path(str(getattr(self.config, "ashare_config_file", "") or ""))
        if config_file.exists():
            try:
                raw_config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
                raw_ttl = raw_config.get("ttl_seconds", {})
                if isinstance(raw_ttl, dict):
                    ttl_seconds.update({str(k): int(v) for k, v in raw_ttl.items()})
            except (OSError, TypeError, ValueError, yaml.YAMLError):
                pass
        if ttl_overrides:
            ttl_seconds.update({str(k): int(v) for k, v in ttl_overrides.items()})
        return ttl_seconds


def _default_provider_factories() -> Dict[str, ProviderFactory]:
    from .astock_data_provider import create_astock_data_provider

    return {"astock_data": create_astock_data_provider}


def _clean_query(query: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in query.items() if value is not None}


def utc_now_source(provider: str, status: str = "unavailable") -> AShareSourceMetadata:
    return AShareSourceMetadata(
        provider=provider,
        status=status,  # type: ignore[arg-type]
        as_of=datetime.now(timezone.utc).isoformat(),
    )
