"""FiestaBoard plugin for upcoming International Space Station passes.

This plugin has two different kinds of "freshness" to keep straight:

1. Pollux Labs API predictions are cacheable until they are no longer the best
   answer. The API returns known pass predictions for a forecast window, so
   calling it for every render wastes network and creates avoidable failure
   modes. However, once the first cached pass has passed its set time, the
   plugin refreshes immediately so a "next 5" request stays full instead of
   slowly shrinking to 4, 3, 2 while waiting for the hourly TTL.
2. Template variables derived from "now" are not cacheable. Values such as
   ``seconds_until_next_occurrence`` need to be recalculated on every render.

To satisfy both constraints, ``manifest.json`` sets ``live_data: true`` so
FiestaBoard calls ``fetch_data()`` every render. This class then maintains its
own cache of the raw API payload and rebuilds the PluginResult from that cached
payload each time. That keeps countdown values moving without hammering Pollux.
"""

import logging
from datetime import datetime, timezone as datetime_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

API_ISS_PASS_URL = "https://iss-api.polluxlabs.io/iss-pass"


class ISSFlyOverTrackerPlugin(PluginBase):
    def __init__(self, manifest: dict[str, Any] | None = None):
        # The real FiestaBoard PluginBase expects a manifest argument. The
        # lightweight unit-test stub historically did not, so keep this shim
        # to make local tests and host loading share the same plugin class.
        try:
            super().__init__(manifest or {})
        except TypeError:
            super().__init__()
            self._manifest = manifest or {}

        # Internal API-payload cache. This intentionally does NOT cache the
        # finished PluginResult because several output fields depend on "now"
        # and must be recalculated on every fetch_data() call.
        self._fetch_cache_key: tuple[Any, ...] | None = None
        self._fetch_cache_time: datetime | None = None
        self._fetch_cache_payload: dict[str, Any] | None = None
        self._clock = lambda: datetime.now(datetime_timezone.utc)

    @property
    def plugin_id(self) -> str:
        return "iss_flyover_tracker"

    def fetch_data(self) -> PluginResult:
        logger.info("ISS fetch_data started")
        config = getattr(self, "config", {}) or {}
        settings_properties = self._settings_properties()

        # Defaults and bounds live in manifest.json so the UI schema and the
        # runtime behavior cannot drift apart. The fallback literals below are
        # defensive only, used if a malformed manifest is ever loaded.
        max_passes_limit = int(settings_properties.get("max_passes", {}).get("maximum", 5))
        min_elevation_minimum = int(settings_properties.get("min_elevation", {}).get("minimum", 0))
        min_elevation_limit = int(settings_properties.get("min_elevation", {}).get("maximum", 90))
        days_ahead_limit = int(settings_properties.get("days_ahead", {}).get("maximum", 14))

        # User config wins over manifest defaults. These helpers read the
        # manifest defaults automatically when the user has not configured a
        # value yet.
        latitude = self._numeric_config(config, "latitude", float)
        longitude = self._numeric_config(config, "longitude", float)
        max_passes = self._numeric_config(config, "max_passes", int)
        min_elevation = self._numeric_config(config, "min_elevation", float)
        visible_only_default = bool(settings_properties.get("visible_only", {}).get("default", False))
        visible_only_value = config.get("visible_only", visible_only_default)
        if isinstance(visible_only_value, bool):
            visible_only = visible_only_value
        elif isinstance(visible_only_value, str):
            visible_only = visible_only_value.lower() in {"1", "true", "yes", "on"}
        else:
            visible_only = bool(visible_only_value)
        days_ahead = self._numeric_config(config, "days_ahead", int)
        timezone_default = settings_properties.get("timezone", {}).get("default", "America/New_York")
        timezone_name = str(config.get("timezone", timezone_default))

        # Pollux parameter names are intentionally short and mirror the API:
        # lat/lon for observer position, n for number of passes, min_elevation
        # for the peak elevation threshold, visible_only for naked-eye
        # filtering, and days_ahead for the forecast window.
        params = {
            "lat": latitude,
            "lon": longitude,
            "n": max(1, min(max_passes, max_passes_limit)),
            "min_elevation": max(min_elevation_minimum, min(min_elevation, min_elevation_limit)),
            "visible_only": str(visible_only).lower(),
            "days_ahead": max(1, min(days_ahead, days_ahead_limit)),
        }
        logger.info(
            "ISS request parameters resolved: lat=%s lon=%s n=%s min_elevation=%s visible_only=%s days_ahead=%s timezone=%s",
            params["lat"],
            params["lon"],
            params["n"],
            params["min_elevation"],
            params["visible_only"],
            params["days_ahead"],
            timezone_name,
        )

        # Cache is keyed by every input that changes the API payload or local
        # formatting. Timezone does not affect Pollux, but it affects the data
        # exposed to templates, so it belongs in the cache key.
        # Do not call this `_cache_key`: PluginBase already has a `_cache_key`
        # method used by FiestaBoard's board-size cache. Shadowing it breaks
        # host calls to plugin.get_data(board).
        cache_key = (
            params["lat"],
            params["lon"],
            params["n"],
            params["min_elevation"],
            params["visible_only"],
            params["days_ahead"],
            timezone_name,
        )

        payload = None
        if self._fetch_cache_key == cache_key and self._fetch_cache_time is not None:
            refresh_default = int(settings_properties.get("refresh_seconds", {}).get("default", 3600))
            refresh_minimum = int(settings_properties.get("refresh_seconds", {}).get("minimum", refresh_default))
            refresh_value = config.get("refresh_seconds", refresh_default)
            try:
                ttl_seconds = max(int(refresh_value), refresh_minimum)
            except (TypeError, ValueError):
                ttl_seconds = max(refresh_default, refresh_minimum)

            cache_age_seconds = (datetime.now() - self._fetch_cache_time).total_seconds()
            if cache_age_seconds >= ttl_seconds:
                logger.info("ISS cache expired: age=%.0fs ttl=%ss", cache_age_seconds, ttl_seconds)
            else:
                logger.info("ISS cache valid: age=%.0fs ttl=%ss", cache_age_seconds, ttl_seconds)
                payload = self._fetch_cache_payload
        else:
            logger.info("ISS cache unavailable for current request")

        if payload is not None:
            passes = payload.get("passes") or []
            if passes:
                first_set_time = (passes[0].get("set") or {}).get("time", "")
                first_set_dt = self._parse_utc(first_set_time)
                if first_set_dt is not None and first_set_dt <= self._clock():
                    logger.info("ISS first cached pass set time is past: set_utc=%s", first_set_time)
                    logger.info("ISS cached first pass has already set; refreshing API payload")
                    payload = None

        if payload is None:
            try:
                logger.info("ISS cache miss; requesting Pollux Labs ISS pass data")
                response = requests.get(API_ISS_PASS_URL, params=params, timeout=15)
                response.raise_for_status()
                payload = response.json()
                # Store the API payload timestamp using local monotonic-ish
                # wall time. Pollux's generated_at/tle_epoch are data fields,
                # not cache expiration controls.
                self._fetch_cache_key = cache_key
                self._fetch_cache_time = datetime.now()
                self._fetch_cache_payload = payload
                logger.info("ISS cache updated")
                logger.info("ISS API fetch succeeded")
            except Exception as exc:
                logger.error("Error fetching ISS pass data: %s", exc, exc_info=True)
                # If the API is down but we have a payload for the exact same
                # request, prefer stale-but-useful predictions over a blank
                # board. A different cache key means the user changed location
                # or options, so stale data would be misleading. This also
                # covers the "first pass expired, refresh failed" path.
                if self._fetch_cache_key == cache_key:
                    logger.info("ISS stale cache available for current request")
                    payload = self._fetch_cache_payload
                else:
                    logger.info("ISS stale cache unavailable for current request")
                    payload = None
                if payload is None:
                    return PluginResult(available=False, error=f"Unable to fetch ISS pass data: {exc}")
                logger.warning("Using stale cached ISS pass data after API error")
        else:
            logger.info("ISS cache hit; rebuilding display data from cached API payload")

        try:
            # Rebuild from payload every time so countdown fields and local
            # presentation stay current even when the API payload is cached.
            try:
                timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                fallback = str(settings_properties.get("timezone", {}).get("default", "America/New_York"))
                logger.warning("Invalid timezone %s, falling back to %s", timezone_name, fallback)
                timezone = ZoneInfo(fallback)

            passes = payload.get("passes") or []
            logger.info("Building ISS result data from %s API pass(es)", len(passes))
            pass_items: list[dict[str, Any]] = []

            for pass_payload in passes:
                rise = pass_payload.get("rise") or {}
                culmination = pass_payload.get("culmination") or {}
                set_data = pass_payload.get("set") or {}

                rise_utc = rise.get("time", "")
                rise_dt = self._parse_utc(rise_utc)
                local_rise_dt = rise_dt.astimezone(timezone) if rise_dt else None

                if local_rise_dt:
                    local_hour = local_rise_dt.strftime("%I").lstrip("0") or "0"
                    time = f"{local_hour}:{local_rise_dt.strftime('%M')}"
                    time_12h = f"{time} {local_rise_dt.strftime('%p')}"
                    time_24h = local_rise_dt.strftime("%H:%M")
                    timezone_abbr = local_rise_dt.tzname()
                    day_of_week = local_rise_dt.strftime("%A")
                    day = local_rise_dt.day
                    rise_date_local = f"{local_rise_dt.strftime('%b')} {local_rise_dt.day}"
                else:
                    time = ""
                    time_12h = ""
                    time_24h = ""
                    timezone_abbr = ""
                    day_of_week = ""
                    day = ""
                    rise_date_local = ""

                seconds_until = 0
                if rise_dt is not None:
                    seconds_until = max(int((rise_dt - self._clock()).total_seconds()), 0)

                visible_start_utc = pass_payload.get("visible_start", "")
                visible_end_utc = pass_payload.get("visible_end", "")
                culmination_utc = culmination.get("time", "")
                duration_seconds = int(pass_payload.get("duration_sec") or 0)
                visible_duration_seconds = int(pass_payload.get("visible_duration_sec") or 0)

                pass_items.append(
                    {
                        "rise_utc": rise_utc,
                        "rise_local": self._format_timestamp(rise_utc, timezone, include_date=True),
                        "rise_date_local": rise_date_local,
                        "rise_time_local": self._format_timestamp(rise_utc, timezone),
                        "time": time,
                        "time_12h": time_12h,
                        "time_24h": time_24h,
                        "timezone_abbr": timezone_abbr,
                        "day_of_week": day_of_week,
                        "day": day,
                        "seconds_until_next_occurrence": seconds_until,
                        "minutes_until_next_occurrence": seconds_until // 60,
                        "visible_start_utc": visible_start_utc,
                        "visible_start_local": self._format_timestamp(visible_start_utc, timezone),
                        "visible_end_utc": visible_end_utc,
                        "visible_end_local": self._format_timestamp(visible_end_utc, timezone),
                        "culmination_utc": culmination_utc,
                        "culmination_local": self._format_timestamp(culmination_utc, timezone),
                        "duration_seconds": duration_seconds,
                        "duration": self._format_duration(duration_seconds),
                        "visible_duration_seconds": visible_duration_seconds,
                        "visible_duration": self._format_duration(visible_duration_seconds),
                        "rise_heading": rise.get("compass", ""),
                        "rise_azimuth_deg": self._round_number(rise.get("azimuth_deg", ""), 1),
                        "set_heading": set_data.get("compass", ""),
                        "set_azimuth_deg": self._round_number(set_data.get("azimuth_deg", ""), 1),
                        "max_elevation_deg": self._round_number(culmination.get("elevation_deg", ""), 1),
                        "is_above_horizon": "yes" if bool(pass_payload.get("above_horizon", False)) else "no",
                        "is_visible": "yes" if bool(pass_payload.get("visible", False)) else "no",
                    }
                )

            data: dict[str, Any] = {
                "satellite": payload.get("satellite", "ISS"),
                "latitude": self._round_number(
                    payload.get("observer", {}).get("lat", settings_properties.get("latitude", {}).get("default", 0)),
                    4,
                ),
                "longitude": self._round_number(
                    payload.get("observer", {}).get("lon", settings_properties.get("longitude", {}).get("default", 0)),
                    4,
                ),
                "timezone": timezone.key,
                "generated_at_utc": payload.get("generated_at", ""),
                "tle_epoch_utc": payload.get("tle_epoch", ""),
                "tle_age_hours": payload.get("tle_age_hours", ""),
                "min_elevation_deg": self._round_number(
                    payload.get("params", {}).get(
                        "min_elevation_deg",
                        payload.get("params", {}).get("min_elevation", params["min_elevation"]),
                    ),
                    1,
                ),
                "pass_count": len(pass_items),
                "passes": pass_items,
            }

            if not pass_items:
                logger.info("ISS API returned no matching passes")
                data.update(
                    {
                        "status": "NO PASSES",
                        "summary": "NO ISS PASSES",
                        "next_rise_utc": "",
                        "next_rise_local": "",
                        "next_rise_date_local": "",
                        "next_rise_time_local": "",
                        "time": "",
                        "time_12h": "",
                        "time_24h": "",
                        "timezone_abbr": "",
                        "day_of_week": "",
                        "day": "",
                        "seconds_until_next_occurrence": 0,
                        "minutes_until_next_occurrence": 0,
                        "next_visible_start_utc": "",
                        "next_visible_start_local": "",
                        "next_visible_end_utc": "",
                        "next_visible_end_local": "",
                        "culmination_utc": "",
                        "culmination_local": "",
                        "duration_seconds": 0,
                        "duration": "",
                        "visible_duration_seconds": 0,
                        "visible_duration": "",
                        "rise_heading": "",
                        "rise_azimuth_deg": "",
                        "set_heading": "",
                        "set_azimuth_deg": "",
                        "max_elevation_deg": "",
                        "is_above_horizon": "no",
                        "is_visible": "no",
                    }
                )
            else:
                next_pass = pass_items[0]
                logger.info(
                    "ISS next pass selected: rise_local=%s visible=%s max_elevation=%s",
                    next_pass.get("rise_local"),
                    next_pass.get("is_visible"),
                    next_pass.get("max_elevation_deg"),
                )
                data.update(
                    {
                        "status": "VISIBLE" if next_pass["is_visible"] == "yes" else "UPCOMING",
                        "summary": (
                            f"ISS {next_pass.get('rise_local', '')} "
                            f"{next_pass.get('rise_heading', '')}->{next_pass.get('set_heading', '')}"
                        ).strip(),
                        "next_rise_utc": next_pass["rise_utc"],
                        "next_rise_local": next_pass["rise_local"],
                        "next_rise_date_local": next_pass["rise_date_local"],
                        "next_rise_time_local": next_pass["rise_time_local"],
                        "time": next_pass["time"],
                        "time_12h": next_pass["time_12h"],
                        "time_24h": next_pass["time_24h"],
                        "timezone_abbr": next_pass["timezone_abbr"],
                        "day_of_week": next_pass["day_of_week"],
                        "day": next_pass["day"],
                        "seconds_until_next_occurrence": next_pass["seconds_until_next_occurrence"],
                        "minutes_until_next_occurrence": next_pass["minutes_until_next_occurrence"],
                        "next_visible_start_utc": next_pass["visible_start_utc"],
                        "next_visible_start_local": next_pass["visible_start_local"],
                        "next_visible_end_utc": next_pass["visible_end_utc"],
                        "next_visible_end_local": next_pass["visible_end_local"],
                        "culmination_utc": next_pass["culmination_utc"],
                        "culmination_local": next_pass["culmination_local"],
                        "duration_seconds": next_pass["duration_seconds"],
                        "duration": next_pass["duration"],
                        "visible_duration_seconds": next_pass["visible_duration_seconds"],
                        "visible_duration": next_pass["visible_duration"],
                        "rise_heading": next_pass["rise_heading"],
                        "rise_azimuth_deg": next_pass["rise_azimuth_deg"],
                        "set_heading": next_pass["set_heading"],
                        "set_azimuth_deg": next_pass["set_azimuth_deg"],
                        "max_elevation_deg": next_pass["max_elevation_deg"],
                        "is_above_horizon": next_pass["is_above_horizon"],
                        "is_visible": next_pass["is_visible"],
                    }
                )

            logger.info(
                "ISS pass data parsed: pass_count=%s status=%s next_rise_local=%s",
                data.get("pass_count"),
                data.get("status"),
                data.get("next_rise_local"),
            )
        except Exception as exc:
            logger.error("Error parsing ISS pass data: %s", exc, exc_info=True)
            return PluginResult(available=False, error="Unable to parse ISS pass data")

        result = PluginResult(
            available=True,
            data=data,
            # FiestaBoard can render templates from `data`, but formatted_lines
            # gives the plugin a sensible built-in six-line board view.
            formatted_lines=(
                ["ISS", "NO VISIBLE", "PASSES FOUND", f"{data.get('timezone', '')}", "", ""]
                if data.get("pass_count", 0) == 0
                else [
                    "ISS VISIBLE" if data.get("is_visible") == "yes" else "ISS PASS",
                    data.get("next_rise_local", ""),
                    f"RISE {data.get('rise_heading', '')} SET {data.get('set_heading', '')}",
                    f"MAX {data.get('max_elevation_deg', '')} DEG",
                    f"DUR {data.get('visible_duration') or data.get('duration') or ''}",
                    "",
                ]
            ),
        )
        logger.info("ISS formatted display generated: %s", result.formatted_lines)
        logger.info("ISS fetch_data completed successfully")
        return result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        logger.info("Validating ISS plugin config")
        errors: list[str] = []

        # The manifest schema should catch these in the UI, but validate_config
        # is the plugin's last line of defense when config is edited manually
        # or imported from an older installation.
        self._validate_number(config, errors, "latitude", "Latitude", -90, 90)
        self._validate_number(config, errors, "longitude", "Longitude", -180, 180)
        self._validate_number(config, errors, "max_passes", "Maximum passes", 1, 5, integer=True)
        self._validate_number(config, errors, "min_elevation", "Minimum elevation", 0, 90)
        self._validate_number(config, errors, "days_ahead", "Forecast days", 1, 14, integer=True)

        if "visible_only" in config and not isinstance(config["visible_only"], bool):
            errors.append("Visible Only must be true or false")

        timezone_name = config.get("timezone")
        if timezone_name:
            try:
                # ZoneInfo validates IANA timezone names without needing any
                # third-party dependency. Examples: America/New_York, UTC.
                ZoneInfo(str(timezone_name))
            except ZoneInfoNotFoundError:
                errors.append("Timezone must be a valid IANA timezone name")

        if errors:
            logger.info("ISS config validation found %s error(s): %s", len(errors), errors)
        else:
            logger.info("ISS config validation passed")

        return errors

    def cleanup(self) -> None:
        logger.info("Plugin %s cleanup", self.plugin_id)

    def _format_timestamp(self, value: str, timezone: ZoneInfo, include_date: bool = False) -> str:
        # Incoming API values are UTC ISO strings ending in "Z"; convert them to
        # timezone-aware datetimes before presenting local display strings.
        dt = self._parse_utc(value)
        if dt is None:
            return ""
        local_dt = dt.astimezone(timezone)
        hour = local_dt.strftime("%I").lstrip("0") or "0"
        minute = local_dt.strftime("%M")
        am_pm = local_dt.strftime("%p")
        if include_date:
            return f"{local_dt.strftime('%b')} {local_dt.day} {hour}:{minute} {am_pm} {local_dt.tzname()}"
        return f"{hour}:{minute} {am_pm}"

    def _parse_utc(self, value: str) -> datetime | None:
        if not value:
            return None
        # Python's fromisoformat understands "+00:00" but not every runtime
        # accepts "Z", so normalize the UTC suffix explicitly.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _format_duration(self, seconds: int) -> str:
        # Vestaboards are small, so prefer compact "3m 17s" style durations.
        if seconds <= 0:
            return ""
        minutes, remainder = divmod(seconds, 60)
        if minutes and remainder:
            return f"{minutes}m {remainder}s"
        if minutes:
            return f"{minutes}m"
        return f"{remainder}s"

    def _numeric_config(
        self, config: dict[str, Any], key: str, numeric_type: type[float] | type[int]
    ) -> float | int:
        # Configuration defaults are manifest-backed. A bad user value falls
        # back to the manifest default instead of crashing fetch_data().
        default = self._settings_properties().get(key, {}).get("default", 0)
        try:
            return numeric_type(config.get(key, default))
        except (TypeError, ValueError):
            return numeric_type(default)

    def _validate_number(
        self,
        config: dict[str, Any],
        errors: list[str],
        key: str,
        label: str,
        minimum: float,
        maximum: float,
        integer: bool = False,
    ) -> None:
        if key not in config:
            return

        # Convert using the expected numeric type so "5" can be accepted while
        # "five" gets a clear validation error.
        value = config[key]
        expected_type = int if integer else float
        try:
            numeric_value = expected_type(value)
        except (TypeError, ValueError):
            errors.append(f"{label} must be a number")
            return

        if numeric_value < minimum or numeric_value > maximum:
            errors.append(f"{label} must be between {minimum:g} and {maximum:g}")

    def _round_number(self, value: Any, digits: int) -> Any:
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return value

    def _settings_properties(self) -> dict[str, Any]:
        # Real PluginBase exposes `manifest`; the local fallback uses
        # `_manifest`. Support both so helper methods work in tests and in app.
        manifest = getattr(self, "manifest", None)
        if isinstance(manifest, dict):
            return manifest.get("settings_schema", {}).get("properties", {})
        local_manifest = getattr(self, "_manifest", {})
        if isinstance(local_manifest, dict):
            return local_manifest.get("settings_schema", {}).get("properties", {})
        return {}
