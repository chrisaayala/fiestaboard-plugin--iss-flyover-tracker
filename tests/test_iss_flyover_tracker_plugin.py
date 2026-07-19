import copy
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch


@dataclass
class PluginResult:
    available: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    formatted_lines: list[str] | None = None


class PluginBase:
    def __init__(self, manifest: dict[str, Any] | None = None):
        self._manifest = manifest or {}
        self._config: dict[str, Any] = {}

    @property
    def manifest(self) -> dict[str, Any]:
        return self._manifest

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @config.setter
    def config(self, value: dict[str, Any]) -> None:
        self._config = value

    def get_data(self, board: Any = None) -> PluginResult:
        self._cache_key(board)
        return self.fetch_data()

    @staticmethod
    def _cache_key(board: Any = None) -> str:
        return board.device_type if board else "__default__"


class ISSFlyOverTrackerPluginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plugin_module = cls._load_plugin_module()
        manifest_path = Path(__file__).resolve().parents[1] / "manifest.json"
        cls.manifest_data = json.loads(manifest_path.read_text())

    @staticmethod
    def _load_plugin_module():
        src_module = types.ModuleType("src")
        plugins_module = types.ModuleType("src.plugins")
        base_module = types.ModuleType("src.plugins.base")
        base_module.PluginBase = PluginBase
        base_module.PluginResult = PluginResult

        sys.modules["src"] = src_module
        sys.modules["src.plugins"] = plugins_module
        sys.modules["src.plugins.base"] = base_module

        module_path = Path(__file__).resolve().parents[1] / "__init__.py"
        spec = importlib.util.spec_from_file_location("iss_flyover_tracker_plugin", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_fetch_data_calls_pollux_with_defaults_and_returns_next_pass_data(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}

            result = plugin.fetch_data()

        self.assertTrue(result.available)
        get.assert_called_once_with(
            self.plugin_module.API_ISS_PASS_URL,
            params={
                "lat": 39.9526,
                "lon": -75.1652,
                "n": 5,
                "visible_only": "true",
                "days_ahead": 10,
            },
            timeout=15,
        )
        self.assertEqual(result.data["status"], "VISIBLE")
        self.assertEqual(result.data["next_rise_utc"], "2026-07-20T00:58:32Z")
        self.assertEqual(result.data["next_rise_local"], "Jul 19 8:58 PM EDT")
        self.assertEqual(result.data["time"], "8:58")
        self.assertEqual(result.data["time_12h"], "8:58 PM")
        self.assertEqual(result.data["time_24h"], "20:58")
        self.assertEqual(result.data["timezone_abbr"], "EDT")
        self.assertEqual(result.data["day_of_week"], "Sunday")
        self.assertEqual(result.data["day"], 19)
        self.assertEqual(result.data["next_visible_start_local"], "8:59 PM")
        self.assertEqual(result.data["next_visible_end_local"], "9:01 PM")
        self.assertEqual(result.data["duration"], "3m 17s")
        self.assertEqual(result.data["visible_duration"], "2m 10s")
        self.assertEqual(result.data["rise_heading"], "NNW")
        self.assertEqual(result.data["set_heading"], "NE")
        self.assertEqual(result.data["max_elevation_deg"], 12.8)
        self.assertEqual(result.data["is_above_horizon"], "yes")
        self.assertEqual(result.data["is_visible"], "yes")
        self.assertEqual(len(result.data["passes"]), 2)
        self.assertEqual(
            result.formatted_lines,
            [
                "ISS VISIBLE",
                "Jul 19 8:58 PM EDT",
                "RISE NNW SET NE",
                "MAX 12.8 DEG",
                "DUR 2m 10s",
                "",
            ],
        )

    def test_fetch_data_uses_configured_values(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {
                "latitude": 34.0522,
                "longitude": -118.2437,
                "max_passes": 3,
                "visible_only": False,
                "days_ahead": 7,
                "timezone": "America/Los_Angeles",
            }

            result = plugin.fetch_data()

        get.assert_called_once_with(
            self.plugin_module.API_ISS_PASS_URL,
            params={
                "lat": 34.0522,
                "lon": -118.2437,
                "n": 3,
                "visible_only": "false",
                "days_ahead": 7,
            },
            timeout=15,
        )
        self.assertTrue(result.available)
        self.assertEqual(result.data["timezone"], "America/Los_Angeles")
        self.assertEqual(result.data["next_rise_local"], "Jul 19 5:58 PM PDT")

    def test_fetch_data_reads_defaults_from_manifest(self) -> None:
        manifest = copy.deepcopy(self.manifest_data)
        properties = manifest["settings_schema"]["properties"]
        properties["latitude"]["default"] = 12.3456
        properties["longitude"]["default"] = 65.4321
        properties["max_passes"]["default"] = 2
        properties["visible_only"]["default"] = False
        properties["days_ahead"]["default"] = 4
        properties["timezone"]["default"] = "UTC"

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(manifest)
            plugin.config = {}

            result = plugin.fetch_data()

        get.assert_called_once_with(
            self.plugin_module.API_ISS_PASS_URL,
            params={
                "lat": 12.3456,
                "lon": 65.4321,
                "n": 2,
                "visible_only": "false",
                "days_ahead": 4,
            },
            timeout=15,
        )
        self.assertEqual(result.data["timezone"], "UTC")
        self.assertEqual(result.data["next_rise_local"], "Jul 20 12:58 AM UTC")

    def test_fetch_data_returns_countdown_fields_from_current_time(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response):
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}
            plugin._now_utc = Mock(return_value=datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc))

            result = plugin.fetch_data()

        self.assertEqual(result.data["seconds_until_next_occurrence"], 3512)
        self.assertEqual(result.data["minutes_until_next_occurrence"], 58)

    def test_get_data_keeps_base_cache_key_contract(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response):
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}

            result = plugin.get_data()

        self.assertTrue(result.available)

    def test_fetch_data_returns_available_when_api_returns_no_passes(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        payload = self._sample_payload()
        payload["passes"] = []
        response.json.return_value = payload

        with patch.object(self.plugin_module.requests, "get", return_value=response):
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}

            result = plugin.fetch_data()

        self.assertTrue(result.available)
        self.assertEqual(result.data["status"], "NO PASSES")
        self.assertEqual(result.data["summary"], "NO ISS PASSES")
        self.assertEqual(result.data["pass_count"], 0)
        self.assertEqual(result.data["passes"], [])
        self.assertEqual(result.formatted_lines[:3], ["ISS", "NO VISIBLE", "PASSES FOUND"])

    def test_fetch_data_returns_unavailable_on_api_error(self) -> None:
        with patch.object(self.plugin_module.requests, "get", side_effect=RuntimeError("boom")):
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}

            result = plugin.fetch_data()

        self.assertFalse(result.available)
        self.assertIn("Unable to fetch ISS pass data", result.error)

    def test_validate_config_rejects_invalid_values(self) -> None:
        plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)

        errors = plugin.validate_config(
            {
                "latitude": 91,
                "longitude": -181,
                "max_passes": 6,
                "visible_only": "true",
                "days_ahead": 15,
                "timezone": "Not/AZone",
            }
        )

        self.assertEqual(
            errors,
            [
                "Latitude must be between -90 and 90",
                "Longitude must be between -180 and 180",
                "Maximum passes must be between 1 and 5",
                "Forecast days must be between 1 and 14",
                "Visible Only must be true or false",
                "Timezone must be a valid IANA timezone name",
            ],
        )

    def test_validate_config_accepts_empty_config_because_defaults_exist(self) -> None:
        plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)

        self.assertEqual(plugin.validate_config({}), [])

    def test_fetch_data_uses_cache_until_refresh_interval_expires(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}
            plugin._now_utc = Mock(return_value=datetime(2026, 7, 20, 1, 0, 0, tzinfo=timezone.utc))

            first_result = plugin.fetch_data()
            second_result = plugin.fetch_data()

        self.assertTrue(first_result.available)
        self.assertTrue(second_result.available)
        get.assert_called_once()

    def test_fetch_data_refreshes_cache_after_first_cached_pass_set_time(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}
            plugin._now_utc = Mock(return_value=datetime(2026, 7, 20, 1, 2, 0, tzinfo=timezone.utc))

            plugin.fetch_data()
            plugin.fetch_data()

        self.assertEqual(get.call_count, 2)

    def test_fetch_data_refreshes_cache_after_refresh_interval(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=response) as get:
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}

            plugin.fetch_data()
            plugin._fetch_cache_time = plugin._fetch_cache_time.replace(year=2000)
            plugin.fetch_data()

        self.assertEqual(get.call_count, 2)

    def test_fetch_data_returns_stale_cache_on_api_error(self) -> None:
        success_response = Mock()
        success_response.raise_for_status.return_value = None
        success_response.json.return_value = self._sample_payload()

        with patch.object(self.plugin_module.requests, "get", return_value=success_response):
            plugin = self.plugin_module.ISSFlyOverTrackerPlugin(self.manifest_data)
            plugin.config = {}
            cached_result = plugin.fetch_data()

        plugin._fetch_cache_time = plugin._fetch_cache_time.replace(year=2000)

        with patch.object(self.plugin_module.requests, "get", side_effect=RuntimeError("boom")):
            result = plugin.fetch_data()

        self.assertTrue(result.available)
        self.assertEqual(result.data["next_rise_utc"], cached_result.data["next_rise_utc"])

    def _sample_payload(self) -> dict[str, Any]:
        return {
            "satellite": "ISS (ZARYA)",
            "tle_epoch": "2026-07-19T04:27:19Z",
            "tle_age_hours": 13.6,
            "observer": {
                "lat": 40.108268,
                "lon": -75.66448,
                "elevation_m": 0,
            },
            "generated_at": "2026-07-19T18:06:09Z",
            "params": {
                "min_elevation_deg": 10,
                "visible_only": True,
                "sun_alt_max_deg": -6,
                "days_ahead": 10,
            },
            "passes": [
                {
                    "rise": {
                        "time": "2026-07-20T00:58:32Z",
                        "azimuth_deg": 339.3,
                        "compass": "NNW",
                    },
                    "culmination": {
                        "time": "2026-07-20T01:00:10Z",
                        "elevation_deg": 12.8,
                    },
                    "set": {
                        "time": "2026-07-20T01:01:49Z",
                        "azimuth_deg": 37.1,
                        "compass": "NE",
                    },
                    "duration_sec": 197,
                    "above_horizon": True,
                    "visible": True,
                    "visible_start": "2026-07-20T00:59:38Z",
                    "visible_end": "2026-07-20T01:01:49Z",
                    "visible_duration_sec": 130,
                },
                {
                    "rise": {
                        "time": "2026-07-20T02:34:43Z",
                        "azimuth_deg": 322.8,
                        "compass": "NW",
                    },
                    "culmination": {
                        "time": "2026-07-20T02:37:48Z",
                        "elevation_deg": 31.1,
                    },
                    "set": {
                        "time": "2026-07-20T02:40:53Z",
                        "azimuth_deg": 92.8,
                        "compass": "E",
                    },
                    "duration_sec": 370,
                    "above_horizon": True,
                    "visible": True,
                    "visible_start": "2026-07-20T02:34:43Z",
                    "visible_end": "2026-07-20T02:38:35Z",
                    "visible_duration_sec": 232,
                },
            ],
        }


if __name__ == "__main__":
    unittest.main()
