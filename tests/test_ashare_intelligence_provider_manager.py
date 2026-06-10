# -*- coding: utf-8 -*-
"""A-share intelligence provider manager cache and status tests."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from data_provider.intelligence.base import (
    AShareFeatureDisabled,
    AShareProviderResult,
    AShareProviderUnavailable,
    AShareSourceMetadata,
)
from data_provider.intelligence.manager import AShareIntelligenceManager


def _config(
    cache_dir: str,
    *,
    enabled: bool = True,
    priority: str = "fake",
    cache_max_files: int = 1000,
) -> SimpleNamespace:
    return SimpleNamespace(
        ashare_intelligence_enabled=enabled,
        ashare_provider_priority=priority,
        ashare_cache_dir=cache_dir,
        ashare_config_file="missing-ashare-config.yaml",
        ashare_cache_max_files=cache_max_files,
    )


class FakeProvider:
    name = "fake"
    schema_version = "v1"

    def __init__(self, status: str = "ok", data: Any | None = None, fail: bool = False):
        self.status = status
        self.data = {"value": 1} if data is None else data
        self.fail = fail
        self.calls = 0

    def fetch(self, capability: str, query: Dict[str, Any]) -> AShareProviderResult:
        self.calls += 1
        if self.fail:
            raise AShareProviderUnavailable("fake provider unavailable")
        return AShareProviderResult(
            status=self.status,
            data=self.data,
            source=AShareSourceMetadata(
                provider=self.name,
                status=self.status,
                as_of="2026-06-08T10:00:00+08:00",
                is_partial=False,
            ),
            coverage={"coverage_ratio": 1.0},
        )


class AShareIntelligenceManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="ashare-manager-")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_disabled_manager_does_not_touch_cache_or_provider(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider()
        manager = AShareIntelligenceManager(
            _config(cache_dir, enabled=False),
            provider_factories={"fake": lambda: provider},
        )

        with self.assertRaises(AShareFeatureDisabled):
            manager.get_capability(
                "capital_flow_minute",
                code="600519",
                trade_date="2026-06-08",
            )

        self.assertEqual(provider.calls, 0)
        self.assertFalse(Path(cache_dir).exists())

    def test_fetch_writes_file_cache_and_new_manager_reads_without_provider(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider(data={"net_inflow": {"amount": 100.0, "unit": "CNY"}})
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
        )

        first = manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
        )

        self.assertEqual(first.status, "ok")
        self.assertFalse(first.cache_hit)
        self.assertEqual(provider.calls, 1)

        blocked_provider = FakeProvider(fail=True)
        second_manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: blocked_provider},
        )
        second = second_manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
        )

        self.assertTrue(second.cache_hit)
        self.assertEqual(second.data, first.data)
        self.assertEqual(blocked_provider.calls, 0)

    def test_refresh_bypasses_cache_but_not_provider_path(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider(data={"value": 1})
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
        )

        manager.get_capability("capital_flow_minute", code="600519", trade_date="2026-06-08")
        refreshed = manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
            refresh=True,
        )

        self.assertFalse(refreshed.cache_hit)
        self.assertEqual(provider.calls, 2)

    def test_empty_provider_result_remains_empty_not_unavailable(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider(status="empty", data=[])
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
        )

        result = manager.get_capability(
            "capital_flow_daily",
            code="600519",
            trade_date="2026-06-08",
        )

        self.assertEqual(result.status, "empty")
        self.assertEqual(result.source.status, "empty")
        self.assertEqual(result.data, [])

    def test_provider_failure_can_return_stale_cache(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider(data={"value": "cached"})
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
            ttl_overrides={"capital_flow_minute": 0},
        )
        manager.get_capability("capital_flow_minute", code="600519", trade_date="2026-06-08")

        stale_provider = FakeProvider(fail=True)
        stale_manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: stale_provider},
            ttl_overrides={"capital_flow_minute": 0},
        )
        stale = stale_manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
        )

        self.assertEqual(stale.status, "stale")
        self.assertFalse(stale.cache_hit)
        self.assertEqual(stale.data, {"value": "cached"})
        self.assertEqual(stale_provider.calls, 1)

    def test_provider_priority_falls_back_after_runtime_failure(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        first_provider = FakeProvider(fail=True)
        second_provider = FakeProvider(data={"provider": "second"})
        manager = AShareIntelligenceManager(
            _config(cache_dir, priority="first,second"),
            provider_factories={
                "first": lambda: first_provider,
                "second": lambda: second_provider,
            },
        )

        result = manager.get_capability(
            "sector_fund_flow",
            trade_date="2026-06-08",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.provider, "second")
        self.assertEqual(result.data, {"provider": "second"})
        self.assertEqual(first_provider.calls, 1)
        self.assertEqual(second_provider.calls, 1)

    def test_corrupt_file_cache_is_quarantined_and_provider_refetches(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        provider = FakeProvider(data={"value": "fresh"})
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
        )
        cache_key = manager._cache_key(
            "fake",
            "capital_flow_minute",
            {"code": "600519", "trade_date": "2026-06-08"},
        )
        cache_path = manager._cache_path(cache_key)
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("{broken", encoding="utf-8")

        result = manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(provider.calls, 1)
        self.assertFalse(cache_path.read_text(encoding="utf-8").startswith("{broken"))
        quarantined = list(cache_path.parent.glob(f"{cache_path.name}.corrupt-*"))
        self.assertEqual(len(quarantined), 1)

    def test_file_cache_cleanup_keeps_newest_entries(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")
        manager = AShareIntelligenceManager(
            _config(cache_dir, cache_max_files=1),
            provider_factories={"fake": lambda: FakeProvider()},
        )

        first = manager.get_capability(
            "capital_flow_minute",
            code="600519",
            trade_date="2026-06-08",
        )
        time.sleep(0.01)
        second = manager.get_capability(
            "capital_flow_minute",
            code="000001",
            trade_date="2026-06-08",
        )

        cache_files = list(Path(cache_dir).glob("*/*.json"))
        self.assertEqual(len(cache_files), 1)
        self.assertEqual(second.status, "ok")
        self.assertFalse(first.cache_hit)

    def test_singleflight_allows_one_provider_call_for_same_key(self) -> None:
        cache_dir = str(Path(self.temp_dir) / "cache")

        class SlowProvider(FakeProvider):
            def fetch(self, capability: str, query: Dict[str, Any]) -> AShareProviderResult:
                time.sleep(0.05)
                return super().fetch(capability, query)

        provider = SlowProvider(data={"value": "shared"})
        manager = AShareIntelligenceManager(
            _config(cache_dir),
            provider_factories={"fake": lambda: provider},
        )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: manager.get_capability(
                        "capital_flow_minute",
                        code="600519",
                        trade_date="2026-06-08",
                    ),
                    range(4),
                )
            )

        self.assertEqual(provider.calls, 1)
        self.assertTrue(any(result.cache_hit for result in results))
        self.assertTrue(all(result.data == {"value": "shared"} for result in results))


if __name__ == "__main__":
    unittest.main()
