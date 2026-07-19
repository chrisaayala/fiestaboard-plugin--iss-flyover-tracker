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
from datetime import datetime, timedelta, timezone as datetime_timezone
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

    @property
    def plugin_id(self) -> str:
        return "iss_flyover_tracker"

    def fetch_data(self) -> PluginResult:
        logger.info("ISS fetch_data started")
        config = getattr(self, "config", {}) or {}

        # Defaults and bounds live in manifest.json so the UI schema and the
        # runtime behavior cannot drift apart. The fallback literals below are
        # defensive only, used if a malformed manifest is ever loaded.
        max_passes_limit = int(self._setting_bound("max_passes", "maximum", 5))
        days_ahead_limit = int(self._setting_bound("days_ahead", "maximum", 14))

        # User config wins over manifest defaults. These helpers read the
        # manifest defaults automatically when the user has not configured a
        # value yet.
        latitude = self._float_config(config, "latitude")
        longitude = self._float_config(config, "longitude")
        max_passes = self._int_config(config, "max_passes")
        visible_only = self._bool_config(config, "visible_only")
        days_ahead = self._int_config(config, "days_ahead")
        timezone_name = str(config.get("timezone", self._setting_default("timezone", "America/New_York")))

        # Pollux parameter names are intentionally short and mirror the API:
        # lat/lon for observer position, n for number of passes, visible_only
        # for naked-eye filtering, and days_ahead for the forecast window.
        params = {
            "lat": latitude,
            "lon": longitude,
            "n": max(1, min(max_passes, max_passes_limit)),
            "visible_only": str(visible_only).lower(),
            "days_ahead": max(1, min(days_ahead, days_ahead_limit)),
        }
        logger.info(
            "ISS request parameters resolved: lat=%s lon=%s n=%s visible_only=%s days_ahead=%s timezone=%s",
            params["lat"],
            params["lon"],
            params["n"],
            params["visible_only"],
            params["days_ahead"],
            timezone_name,
        )

        # Cache is keyed by every input that changes the API payload or local
        # formatting. Timezone does not affect Pollux, but it affects the data
        # exposed to templates, so it belongs in the cache key.
        cache_key = self._request_cache_key(params, timezone_name)
        payload = self._get_cached_payload(cache_key)
        if payload is not None and self._first_cached_pass_has_set(payload):
            logger.info("ISS cached first pass has already set; refreshing API payload")
            payload = None

        if payload is None:
            try:
                logger.info("ISS cache miss; requesting Pollux Labs ISS pass data")
                response = requests.get(API_ISS_PASS_URL, params=params, timeout=15)
                response.raise_for_status()
                payload = response.json()
                self._set_cached_payload(cache_key, payload)
                logger.info("ISS API fetch succeeded")
            except Exception as exc:
                logger.error("Error fetching ISS pass data: %s", exc, exc_info=True)
                # If the API is down but we have a payload for the exact same
                # request, prefer stale-but-useful predictions over a blank
                # board. A different cache key means the user changed location
                # or options, so stale data would be misleading. This also
                # covers the "first pass expired, refresh failed" path.
                payload = self._get_stale_cached_payload(cache_key)
                if payload is None:
                    return PluginResult(available=False, error=f"Unable to fetch ISS pass data: {exc}")
                logger.warning("Using stale cached ISS pass data after API error")
        else:
            logger.info("ISS cache hit; rebuilding display data from cached API payload")

        try:
            # Rebuild from payload every time so countdown fields and local
            # presentation stay current even when the API payload is cached.
            data = self._build_result_data(payload, timezone_name)
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
            formatted_lines=self._format_display(data),
        )
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

    def _build_result_data(self, payload: dict[str, Any], timezone_name: str) -> dict[str, Any]:
        # The API timestamps are UTC. All local/template-friendly time strings
        # are derived with this configured timezone.
        timezone = self._timezone(timezone_name)
        passes = payload.get("passes") or []
        logger.info("Building ISS result data from %s API pass(es)", len(passes))
        pass_items = [self._pass_to_data(pass_payload, timezone) for pass_payload in passes]

        # These base fields are always present, even when there are no passes,
        # so templates can safely reference location/system values.
        base_data: dict[str, Any] = {
            "satellite": payload.get("satellite", "ISS"),
            "latitude": self._round_number(payload.get("observer", {}).get("lat", self._setting_default("latitude", 0)), 4),
            "longitude": self._round_number(payload.get("observer", {}).get("lon", self._setting_default("longitude", 0)), 4),
            "timezone": timezone.key,
            "generated_at_utc": payload.get("generated_at", ""),
            "tle_epoch_utc": payload.get("tle_epoch", ""),
            "tle_age_hours": payload.get("tle_age_hours", ""),
            "pass_count": len(pass_items),
            "passes": pass_items,
        }

        if not pass_items:
            logger.info("ISS API returned no matching passes")
            # "No passes" is not a plugin failure. It means the API responded
            # successfully and no pass met the configured filters/window.
            base_data.update(self._empty_next_pass_data())
            return base_data

        # Pollux returns passes ordered by time, so the first item is the next
        # occurrence and gets promoted to top-level variables for easy templates.
        next_pass = pass_items[0]
        logger.info(
            "ISS next pass selected: rise_local=%s visible=%s max_elevation=%s",
            next_pass.get("rise_local"),
            next_pass.get("is_visible"),
            next_pass.get("max_elevation_deg"),
        )
        base_data.update(
            {
                "status": "VISIBLE" if next_pass["is_visible"] == "yes" else "UPCOMING",
                "summary": self._summary(next_pass),
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
        return base_data

    def _pass_to_data(self, pass_payload: dict[str, Any], timezone: ZoneInfo) -> dict[str, Any]:
        # Pollux nests rise/culmination/set details. Flattening them here keeps
        # the public template variables short and board-friendly.
        rise = pass_payload.get("rise") or {}
        culmination = pass_payload.get("culmination") or {}
        set_data = pass_payload.get("set") or {}

        rise_utc = rise.get("time", "")
        rise_dt = self._parse_utc(rise_utc)

        # Convert once, then derive all local time variants from the same
        # datetime so 12h/24h/day/timezone fields stay internally consistent.
        local_rise_dt = rise_dt.astimezone(timezone) if rise_dt else None

        # Capture countdown seconds once per pass conversion; minutes are then
        # derived from the same value so the two fields cannot disagree around
        # a second boundary.
        seconds_until = self._seconds_until(rise_dt)
        visible_start_utc = pass_payload.get("visible_start", "")
        visible_end_utc = pass_payload.get("visible_end", "")
        culmination_utc = culmination.get("time", "")
        duration_seconds = int(pass_payload.get("duration_sec") or 0)
        visible_duration_seconds = int(pass_payload.get("visible_duration_sec") or 0)

        return {
            # Raw UTC fields preserve the API truth for users who want exact
            # timestamps or their own formatting.
            "rise_utc": rise_utc,

            # Local fields are meant for Vestaboard-sized templates.
            "rise_local": self._format_timestamp(rise_utc, timezone, include_date=True),
            "rise_date_local": self._format_date(rise_utc, timezone),
            "rise_time_local": self._format_timestamp(rise_utc, timezone),
            "time": self._format_time_no_period(local_rise_dt),
            "time_12h": self._format_time_12h(local_rise_dt),
            "time_24h": self._format_time_24h(local_rise_dt),
            "timezone_abbr": local_rise_dt.tzname() if local_rise_dt else "",
            "day_of_week": local_rise_dt.strftime("%A") if local_rise_dt else "",
            "day": local_rise_dt.day if local_rise_dt else "",
            "seconds_until_next_occurrence": seconds_until,
            "minutes_until_next_occurrence": seconds_until // 60,

            # Visible start/end can differ from rise/set when the ISS is not
            # sunlit for the full above-horizon pass.
            "visible_start_utc": visible_start_utc,
            "visible_start_local": self._format_timestamp(visible_start_utc, timezone),
            "visible_end_utc": visible_end_utc,
            "visible_end_local": self._format_timestamp(visible_end_utc, timezone),

            # Culmination is the highest point in the pass, usually the most
            # useful "look up around this time" marker.
            "culmination_utc": culmination_utc,
            "culmination_local": self._format_timestamp(culmination_utc, timezone),

            # Keep both machine-friendly seconds and human-friendly duration.
            "duration_seconds": duration_seconds,
            "duration": self._format_duration(duration_seconds),
            "visible_duration_seconds": visible_duration_seconds,
            "visible_duration": self._format_duration(visible_duration_seconds),

            # Compass strings are usually better than azimuth numbers on a
            # small board, but both are exposed for flexibility.
            "rise_heading": rise.get("compass", ""),
            "rise_azimuth_deg": self._round_number(rise.get("azimuth_deg", ""), 1),
            "set_heading": set_data.get("compass", ""),
            "set_azimuth_deg": self._round_number(set_data.get("azimuth_deg", ""), 1),
            "max_elevation_deg": self._round_number(culmination.get("elevation_deg", ""), 1),
            "is_above_horizon": self._yes_no(pass_payload.get("above_horizon", False)),
            "is_visible": self._yes_no(pass_payload.get("visible", False)),
        }

    def _empty_next_pass_data(self) -> dict[str, Any]:
        # Return every top-level "next pass" key with a neutral value. This
        # avoids unresolved template variables when the forecast has no match.
        return {
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

    def _format_display(self, data: dict[str, Any]) -> list[str]:
        # FiestaBoard/Vestaboard flagship layout is six lines. Keep each line
        # short enough to work on a split-flap style display.
        if data.get("pass_count", 0) == 0:
            lines = ["ISS", "NO VISIBLE", "PASSES FOUND", f"{data.get('timezone', '')}", "", ""]
            logger.info("ISS formatted display generated for no-pass state: %s", lines)
            return lines[:6]

        visible_label = "ISS VISIBLE" if data.get("is_visible") == "yes" else "ISS PASS"
        duration = data.get("visible_duration") or data.get("duration") or ""
        lines = [
            visible_label,
            data.get("next_rise_local", ""),
            f"RISE {data.get('rise_heading', '')} SET {data.get('set_heading', '')}",
            f"MAX {data.get('max_elevation_deg', '')} DEG",
            f"DUR {duration}",
            "",
        ]
        logger.info("ISS formatted display generated: %s", lines)
        return lines[:6]

    def _summary(self, pass_data: dict[str, Any]) -> str:
        # A compact string for users who want one variable in a custom page.
        rise_time = pass_data.get("rise_local", "")
        rise_heading = pass_data.get("rise_heading", "")
        set_heading = pass_data.get("set_heading", "")
        return f"ISS {rise_time} {rise_heading}->{set_heading}".strip()

    def _timezone(self, timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            # Invalid timezone should not break the plugin after install. Config
            # validation reports it, but runtime still falls back safely.
            fallback = str(self._setting_default("timezone", "America/New_York"))
            logger.warning("Invalid timezone %s, falling back to %s", timezone_name, fallback)
            return ZoneInfo(fallback)

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

    def _format_date(self, value: str, timezone: ZoneInfo) -> str:
        dt = self._parse_utc(value)
        if dt is None:
            return ""
        local_dt = dt.astimezone(timezone)
        return f"{local_dt.strftime('%b')} {local_dt.day}"

    def _format_time_no_period(self, value: datetime | None) -> str:
        if value is None:
            return ""
        hour = value.strftime("%I").lstrip("0") or "0"
        return f"{hour}:{value.strftime('%M')}"

    def _format_time_12h(self, value: datetime | None) -> str:
        if value is None:
            return ""
        return f"{self._format_time_no_period(value)} {value.strftime('%p')}"

    def _format_time_24h(self, value: datetime | None) -> str:
        if value is None:
            return ""
        return value.strftime("%H:%M")

    def _parse_utc(self, value: str) -> datetime | None:
        if not value:
            return None
        # Python's fromisoformat understands "+00:00" but not every runtime
        # accepts "Z", so normalize the UTC suffix explicitly.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _now_utc(self) -> datetime:
        # Isolated for tests so countdown math can be deterministic.
        return datetime.now(datetime_timezone.utc)

    def _seconds_until(self, value: datetime | None) -> int:
        if value is None:
            return 0
        # Clamp at zero once the predicted rise time has passed. The next API
        # refresh will eventually drop old passes; until then, templates should
        # not show negative countdowns.
        seconds = int((value - self._now_utc()).total_seconds())
        return max(seconds, 0)

    def _minutes_until(self, value: datetime | None) -> int:
        return self._seconds_until(value) // 60

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

    def _float_config(self, config: dict[str, Any], key: str) -> float:
        # Configuration defaults are manifest-backed. A bad user value falls
        # back to the manifest default instead of crashing fetch_data().
        default = self._setting_default(key, 0)
        try:
            return float(config.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _int_config(self, config: dict[str, Any], key: str) -> int:
        # Same behavior as _float_config, but for integer settings like n/days.
        default = self._setting_default(key, 0)
        try:
            return int(config.get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def _bool_config(self, config: dict[str, Any], key: str) -> bool:
        # The UI should send booleans, but string handling makes manual config
        # edits and environment-style values less brittle.
        default = bool(self._setting_default(key, False))
        value = config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

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

    def _yes_no(self, value: Any) -> str:
        return "yes" if bool(value) else "no"

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

    def _setting_default(self, key: str, fallback: Any) -> Any:
        # Single place for manifest-default lookup. This keeps module-level
        # constants from drifting away from manifest.json.
        return self._settings_properties().get(key, {}).get("default", fallback)

    def _setting_bound(self, key: str, bound: str, fallback: int | float) -> int | float:
        return self._settings_properties().get(key, {}).get(bound, fallback)

    def _cache_ttl_seconds(self) -> int:
        # Respect the configured refresh interval but never below the manifest
        # minimum. The current manifest defaults this to one hour.
        config = getattr(self, "config", {}) or {}
        default = int(self._setting_default("refresh_seconds", 3600))
        minimum = int(self._setting_bound("refresh_seconds", "minimum", default))
        value = config.get("refresh_seconds", default)
        try:
            return max(int(value), minimum)
        except (TypeError, ValueError):
            return max(default, minimum)

    def _request_cache_key(self, params: dict[str, Any], timezone_name: str) -> tuple[Any, ...]:
        # Do not call this `_cache_key`: PluginBase already has a `_cache_key`
        # method used by FiestaBoard's board-size cache. Shadowing it breaks
        # host calls to plugin.get_data(board).
        return (
            params["lat"],
            params["lon"],
            params["n"],
            params["visible_only"],
            params["days_ahead"],
            timezone_name,
        )

    def _get_cached_payload(self, cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
        # Cache is valid only for identical request inputs and only inside the
        # refresh interval. Finished PluginResult objects are never cached here.
        # Expired first-pass filtering happens in fetch_data() so that a failed
        # refresh can still fall back to this exact stale payload if needed.
        if self._fetch_cache_key != cache_key or self._fetch_cache_time is None:
            logger.info("ISS cache unavailable for current request")
            return None
        cache_age_seconds = (datetime.now() - self._fetch_cache_time).total_seconds()
        ttl_seconds = self._cache_ttl_seconds()
        if cache_age_seconds >= ttl_seconds:
            logger.info("ISS cache expired: age=%.0fs ttl=%ss", cache_age_seconds, ttl_seconds)
            return None
        logger.info("ISS cache valid: age=%.0fs ttl=%ss", cache_age_seconds, ttl_seconds)
        return self._fetch_cache_payload

    def _first_cached_pass_has_set(self, payload: dict[str, Any]) -> bool:
        # Use set.time rather than rise.time because a pass should stay active
        # while the ISS is still above the horizon or potentially visible.
        passes = payload.get("passes") or []
        if not passes:
            return False

        first_set_time = (passes[0].get("set") or {}).get("time", "")
        first_set_dt = self._parse_utc(first_set_time)
        if first_set_dt is None:
            return False

        has_set = first_set_dt <= self._now_utc()
        if has_set:
            logger.info("ISS first cached pass set time is past: set_utc=%s", first_set_time)
        return has_set

    def _get_stale_cached_payload(self, cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
        # Stale fallback is intentionally stricter than "any old payload": it
        # must match the same location/options/timezone cache key.
        if self._fetch_cache_key != cache_key:
            logger.info("ISS stale cache unavailable for current request")
            return None
        logger.info("ISS stale cache available for current request")
        return self._fetch_cache_payload

    def _set_cached_payload(self, cache_key: tuple[Any, ...], payload: dict[str, Any]) -> None:
        # Store the API payload timestamp using local monotonic-ish wall time.
        # The payload itself may contain generated_at/tle_epoch from Pollux;
        # those are data fields, not cache expiration controls.
        self._fetch_cache_key = cache_key
        self._fetch_cache_time = datetime.now()
        self._fetch_cache_payload = payload
        logger.info("ISS cache updated")
