# -*- coding: utf-8 -*-
"""Provider health aggregation service.

Builds a system-wide data-source observability snapshot from two sources that
already exist in the runtime:

1. **Historical provider runs** — every analysis trace records per-attempt
   ``ProviderRun`` diagnostics (success / latency / fallback / stale / error),
   which are persisted inside ``AnalysisHistory.context_snapshot`` under
   ``diagnostics.provider_runs``. We aggregate those over a recent time window.
2. **Live circuit-breaker state** — the in-memory realtime / chip breakers
   expose each source's current CLOSED / OPEN / HALF_OPEN state.

No new storage is introduced; this is a read-only aggregation surface.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from src.storage import DatabaseManager
from src.utils.data_processing import parse_json_field

logger = logging.getLogger(__name__)


class ProviderHealthService:
    """Aggregate persisted provider runs plus live breaker state."""

    DEFAULT_WINDOW_HOURS = 24
    MAX_RECORDS = 1000

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    @staticmethod
    def aggregate_provider_runs(runs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aggregate per-attempt provider runs into per-provider health stats.

        DB-agnostic and deterministic. Runs without a non-empty ``provider`` are
        skipped. A run counts as a fallback when it carries ``fallback_from`` or
        ``fallback_to``; as stale when ``stale_seconds`` is a positive number.
        ``last_error_type`` / ``last_seen_at`` track the most recent run by
        ``created_at`` (ISO strings sort chronologically).
        """
        buckets: Dict[str, Dict[str, Any]] = {}

        for run in runs:
            if not isinstance(run, dict):
                continue
            provider = str(run.get("provider") or "").strip()
            if not provider:
                continue

            bucket = buckets.setdefault(
                provider,
                {
                    "provider": provider,
                    "attempts": 0,
                    "success_count": 0,
                    "fallback_count": 0,
                    "stale_count": 0,
                    "_latencies": [],
                    "last_error_type": None,
                    "last_seen_at": None,
                    "_last_error_at": None,
                },
            )

            bucket["attempts"] += 1
            if run.get("success") is True:
                bucket["success_count"] += 1
            if run.get("fallback_from") or run.get("fallback_to"):
                bucket["fallback_count"] += 1

            stale_seconds = run.get("stale_seconds")
            if isinstance(stale_seconds, (int, float)) and stale_seconds > 0:
                bucket["stale_count"] += 1

            latency = run.get("latency_ms")
            if isinstance(latency, (int, float)):
                bucket["_latencies"].append(float(latency))

            created_at = run.get("created_at")
            if created_at is not None:
                if bucket["last_seen_at"] is None or str(created_at) > str(bucket["last_seen_at"]):
                    bucket["last_seen_at"] = created_at

            error_type = run.get("error_type")
            if error_type:
                if bucket["_last_error_at"] is None or str(created_at) >= str(bucket["_last_error_at"]):
                    bucket["last_error_type"] = error_type
                    bucket["_last_error_at"] = created_at

        result: List[Dict[str, Any]] = []
        for bucket in buckets.values():
            attempts = bucket["attempts"]
            latencies = bucket.pop("_latencies")
            bucket.pop("_last_error_at", None)
            bucket["success_rate_pct"] = round(bucket["success_count"] / attempts * 100, 2) if attempts else None
            bucket["fallback_rate_pct"] = round(bucket["fallback_count"] / attempts * 100, 2) if attempts else None
            bucket["stale_rate_pct"] = round(bucket["stale_count"] / attempts * 100, 2) if attempts else None
            bucket["avg_latency_ms"] = round(sum(latencies) / len(latencies)) if latencies else None
            result.append(bucket)

        # Most-active providers first; provider name as a stable tiebreaker.
        result.sort(key=lambda b: (-b["attempts"], b["provider"]))
        return result

    @staticmethod
    def _circuit_breaker_states() -> List[Dict[str, Any]]:
        """Flatten the live realtime / chip breakers into a list (read-only)."""
        from data_provider.realtime_types import (
            get_chip_circuit_breaker,
            get_realtime_circuit_breaker,
        )

        rows: List[Dict[str, Any]] = []
        for breaker_name, breaker in (
            ("realtime", get_realtime_circuit_breaker()),
            ("chip", get_chip_circuit_breaker()),
        ):
            try:
                described = breaker.describe()
            except Exception as exc:  # never let observability break on a breaker
                logger.warning("读取熔断器 %s 状态失败: %s", breaker_name, exc)
                continue
            for source, info in described.items():
                rows.append({"breaker": breaker_name, "source": source, **info})
        rows.sort(key=lambda r: (r["breaker"], r["source"]))
        return rows

    def get_provider_health(
        self,
        *,
        window_hours: int = DEFAULT_WINDOW_HOURS,
        max_records: int = MAX_RECORDS,
    ) -> Dict[str, Any]:
        """Build the provider-health snapshot over the last ``window_hours``."""
        window_hours = max(1, int(window_hours))
        cutoff = datetime.now() - timedelta(hours=window_hours)
        # get_analysis_history filters by whole days; widen then refine in-memory.
        days = max(1, math.ceil(window_hours / 24))

        records_scanned = 0
        collected_runs: List[Dict[str, Any]] = []
        try:
            records = self.db.get_analysis_history(days=days, limit=int(max_records))
        except Exception as exc:
            logger.error("读取分析历史用于 provider 健康聚合失败: %s", exc)
            records = []

        for record in records:
            created_at = getattr(record, "created_at", None)
            if created_at is not None and created_at < cutoff:
                continue
            snapshot = parse_json_field(getattr(record, "context_snapshot", None))
            if not isinstance(snapshot, dict):
                continue
            diagnostics = snapshot.get("diagnostics")
            if not isinstance(diagnostics, dict):
                continue
            provider_runs = diagnostics.get("provider_runs")
            if not isinstance(provider_runs, list):
                continue
            records_scanned += 1
            collected_runs.extend(run for run in provider_runs if isinstance(run, dict))

        providers = self.aggregate_provider_runs(collected_runs)
        return {
            "window_hours": window_hours,
            "generated_at": datetime.now().isoformat(),
            "records_scanned": records_scanned,
            "total_provider_runs": len(collected_runs),
            "providers": providers,
            "circuit_breakers": self._circuit_breaker_states(),
        }
