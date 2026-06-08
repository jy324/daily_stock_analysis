# -*- coding: utf-8 -*-
"""A-share intelligence provider manager cache and status tests."""

from __future__ import annotations

import shutil
import tempfile
import unittest
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


def _config(cache_dir: str, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        ashare_intelligence_enabled=enabled,
        ashare_provider_priority="fake",
        ashare_cache_dir=cache_dir,
        ashare_config_file="missing-ashare-config.yaml",
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


if __name__ == "__main__":
    unittest.main()
