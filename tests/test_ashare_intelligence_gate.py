# -*- coding: utf-8 -*-
"""A-share intelligence feature gate and capabilities contract tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config


def _make_client() -> tuple[tempfile.TemporaryDirectory[str], TestClient]:
    temp_dir = tempfile.TemporaryDirectory()
    return temp_dir, TestClient(create_app(static_dir=Path(temp_dir.name)))


class AShareIntelligenceConfigTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        Config.reset_instance()

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_defaults_ashare_intelligence_disabled(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        with patch.dict(os.environ, {"STOCK_LIST": "600519"}, clear=True):
            config = Config._load_from_env()

        self.assertFalse(config.ashare_intelligence_enabled)
        self.assertEqual(config.ashare_provider_priority, "astock_data")
        self.assertEqual(config.ashare_cache_dir, "./data/ashare_cache")
        self.assertEqual(config.ashare_config_file, "config/ashare_intelligence.yaml")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_reads_ashare_intelligence_settings(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "STOCK_LIST": "600519",
            "ASHARE_INTELLIGENCE_ENABLED": "true",
            "ASHARE_PROVIDER_PRIORITY": "astock_data,custom",
            "ASHARE_CACHE_DIR": "./tmp/ashare",
            "ASHARE_CONFIG_FILE": "config/custom_ashare.yaml",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertTrue(config.ashare_intelligence_enabled)
        self.assertEqual(config.ashare_provider_priority, "astock_data,custom")
        self.assertEqual(config.ashare_cache_dir, "./tmp/ashare")
        self.assertEqual(config.ashare_config_file, "config/custom_ashare.yaml")


class AShareIntelligenceCapabilitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()
        sys.modules.pop("astock_data", None)

    def tearDown(self) -> None:
        Config.reset_instance()
        sys.modules.pop("astock_data", None)

    def test_capabilities_endpoint_reports_disabled_without_importing_provider(self) -> None:
        temp_dir, client = _make_client()
        try:
            with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=None):
                response = client.get("/api/v1/capabilities")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["ashare_intelligence"],
            {
                "enabled": False,
                "provider_installed": False,
                "report_enabled": False,
                "agent_tools_enabled": False,
                "scoring_enabled": False,
            },
        )
        self.assertNotIn("astock_data", sys.modules)

    def test_capabilities_endpoint_reports_installed_provider_without_importing_it(self) -> None:
        temp_dir, client = _make_client()
        try:
            fake_spec = SimpleNamespace(name="astock_data")
            with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=fake_spec):
                response = client.get("/api/v1/capabilities")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ashare_intelligence"]["provider_installed"])
        self.assertNotIn("astock_data", sys.modules)

    def test_capabilities_endpoint_reads_yaml_subfeature_flags_when_enabled(self) -> None:
        temp_dir, client = _make_client()
        config_file = Path(temp_dir.name) / "ashare.yaml"
        config_file.write_text(
            "\n".join(
                [
                    "report:",
                    "  enabled: true",
                    "agent_tools:",
                    "  enabled: true",
                    "scoring:",
                    "  enabled: false",
                ]
            ),
            encoding="utf-8",
        )
        try:
            env = {
                "ASHARE_INTELLIGENCE_ENABLED": "true",
                "ASHARE_CONFIG_FILE": str(config_file),
            }
            with patch.dict(os.environ, env, clear=True):
                Config.reset_instance()
                fake_spec = SimpleNamespace(name="astock_data")
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=fake_spec):
                    response = client.get("/api/v1/capabilities")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 200)
        body = response.json()["ashare_intelligence"]
        self.assertTrue(body["enabled"])
        self.assertTrue(body["report_enabled"])
        self.assertTrue(body["agent_tools_enabled"])
        self.assertFalse(body["scoring_enabled"])
        self.assertNotIn("astock_data", sys.modules)

    def test_registered_ashare_route_rejects_when_feature_disabled(self) -> None:
        temp_dir, client = _make_client()
        try:
            response = client.get("/api/v1/market/ashare/status")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "feature_disabled")

    def test_registered_ashare_route_reports_missing_dependency_when_enabled(self) -> None:
        temp_dir, client = _make_client()
        try:
            with patch.dict(os.environ, {"ASHARE_INTELLIGENCE_ENABLED": "true"}, clear=True):
                Config.reset_instance()
                with patch("src.services.ashare_intelligence_service.importlib.util.find_spec", return_value=None):
                    response = client.get("/api/v1/market/ashare/status")
        finally:
            temp_dir.cleanup()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "dependency_unavailable")


if __name__ == "__main__":
    unittest.main()
