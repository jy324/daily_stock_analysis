# -*- coding: utf-8 -*-
"""A-share intelligence agent tool registration and contract tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.agent import factory
from src.schemas.ashare_intelligence import AShareIntelligenceResult, AShareSourceMetadata


def _config(config_file: str, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        ashare_intelligence_enabled=enabled,
        ashare_config_file=config_file,
    )


class FakeService:
    def __init__(self, config) -> None:
        self.config = config

    def get_capability(self, capability: str, **kwargs):
        return AShareIntelligenceResult(
            capability=capability,
            provider="fake",
            status="partial",
            data={"capability": capability, "query": kwargs},
            source=AShareSourceMetadata(
                provider="fake",
                status="partial",
                as_of="2026-06-08T10:30:00+08:00",
                is_partial=False,
            ),
            coverage={"coverage_ratio": 0.8},
            cache_hit=True,
            snapshot_id="snap-1",
        )

    def get_risk_events(self, **kwargs):
        return AShareIntelligenceResult(
            capability="risk_events",
            provider="fake",
            status="partial",
            data={"events": [], "query": kwargs},
            source=AShareSourceMetadata(
                provider="fake",
                status="partial",
                as_of="2026-06-08T10:30:00+08:00",
                is_partial=False,
            ),
            coverage={"coverage_ratio": 0.5},
            cache_hit=True,
            snapshot_id="snap-risk",
        )


class AShareAgentToolsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        factory._TOOL_REGISTRY = None
        if hasattr(factory, "_TOOL_REGISTRY_CACHE_KEY"):
            factory._TOOL_REGISTRY_CACHE_KEY = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "ashare.yaml"

    def tearDown(self) -> None:
        factory._TOOL_REGISTRY = None
        if hasattr(factory, "_TOOL_REGISTRY_CACHE_KEY"):
            factory._TOOL_REGISTRY_CACHE_KEY = None
        self.temp_dir.cleanup()

    def _write_agent_config(self, enabled: bool) -> str:
        self.config_path.write_text(
            "\n".join(["agent_tools:", f"  enabled: {'true' if enabled else 'false'}"]),
            encoding="utf-8",
        )
        return str(self.config_path)

    def test_registry_does_not_register_ashare_tools_when_disabled(self) -> None:
        config = _config(self._write_agent_config(False), enabled=True)

        with patch("src.config.get_config", return_value=config):
            registry = factory.get_tool_registry()

        self.assertNotIn("get_ashare_market_intelligence", registry.list_names())
        self.assertNotIn("get_ashare_stock_capital_flow", registry.list_names())
        self.assertNotIn("get_ashare_stock_risk_events", registry.list_names())

    def test_registry_registers_ashare_tools_when_gate_and_agent_tools_enabled(self) -> None:
        config = _config(self._write_agent_config(True), enabled=True)

        with patch("src.config.get_config", return_value=config):
            registry = factory.get_tool_registry()

        self.assertIn("get_ashare_market_intelligence", registry.list_names())
        self.assertIn("get_ashare_stock_capital_flow", registry.list_names())
        self.assertIn("get_ashare_stock_risk_events", registry.list_names())

    def test_registry_cache_key_tracks_agent_tool_flag(self) -> None:
        config = _config(self._write_agent_config(False), enabled=True)
        with patch("src.config.get_config", return_value=config):
            disabled_registry = factory.get_tool_registry()

        config = _config(self._write_agent_config(True), enabled=True)
        with patch("src.config.get_config", return_value=config):
            enabled_registry = factory.get_tool_registry()

        self.assertIsNot(disabled_registry, enabled_registry)
        self.assertNotIn("get_ashare_market_intelligence", disabled_registry.list_names())
        self.assertIn("get_ashare_market_intelligence", enabled_registry.list_names())

    def test_market_tool_contract_forbids_refresh_and_returns_snapshot_metadata(self) -> None:
        from src.agent.tools.ashare_intelligence_tools import _handle_get_ashare_market_intelligence

        config = _config(self._write_agent_config(True), enabled=True)
        with patch("src.config.get_config", return_value=config), \
                patch("src.agent.tools.ashare_intelligence_tools.AShareIntelligenceService", FakeService):
            result = _handle_get_ashare_market_intelligence(
                capability="sector_fund_flow",
                trade_date="2026-06-08",
                limit=3,
                refresh=True,
            )

        self.assertEqual(result["data_status"], "partial")
        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["snapshot_id"], "snap-1")
        self.assertEqual(result["coverage"], {"coverage_ratio": 0.8})
        self.assertFalse(result["query"]["refresh"])
        self.assertEqual(result["query"]["limit"], 3)

    def test_stock_tool_applies_lookback_hard_limit(self) -> None:
        from src.agent.tools.ashare_intelligence_tools import _handle_get_ashare_stock_capital_flow

        config = _config(self._write_agent_config(True), enabled=True)
        with patch("src.config.get_config", return_value=config), \
                patch("src.agent.tools.ashare_intelligence_tools.AShareIntelligenceService", FakeService):
            result = _handle_get_ashare_stock_capital_flow(
                code="600519",
                trade_date="2026-06-08",
                lookback=999,
            )

        self.assertEqual(result["data"]["query"]["lookback"], 120)
        self.assertEqual(result["data_status"], "partial")

    def test_risk_events_tool_forbids_refresh_and_clamps_lookback(self) -> None:
        from src.agent.tools.ashare_intelligence_tools import _handle_get_ashare_stock_risk_events

        config = _config(self._write_agent_config(True), enabled=True)
        with patch("src.config.get_config", return_value=config), \
                patch("src.agent.tools.ashare_intelligence_tools.AShareIntelligenceService", FakeService):
            result = _handle_get_ashare_stock_risk_events(
                code="600519",
                trade_date="2026-06-08",
                lookback=999,
                refresh=True,
            )

        self.assertEqual(result["snapshot_id"], "snap-risk")
        self.assertEqual(result["query"]["lookback"], 120)
        self.assertFalse(result["query"]["refresh"])


if __name__ == "__main__":
    unittest.main()
