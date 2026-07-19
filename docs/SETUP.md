# ISS Flyover Tracker Setup

This plugin shows upcoming International Space Station passes for a configured observer location. It uses the Pollux Labs ISS Pass API and does not require an API key.

## Required Configuration

The plugin can run with its defaults, but users should update the location fields for accurate pass predictions.

| Setting | Description | Default |
| --- | --- | --- |
| `enabled` | Enables the plugin in FiestaBoard. | `false` |
| `latitude` | Observer latitude in decimal degrees. | `39.9526` |
| `longitude` | Observer longitude in decimal degrees. | `-75.1652` |
| `max_passes` | Maximum number of passes to request. | `5` |
| `visible_only` | Only return passes visible to the naked eye. | `true` |
| `days_ahead` | Forecast window in days. | `10` |
| `timezone` | IANA timezone used for local display strings. | `America/New_York` |
| `refresh_seconds` | How often to refresh Pollux API predictions. | `3600` |

## Location

Set `latitude` and `longitude` to the observer's decimal coordinates. The defaults are for Philadelphia, Pennsylvania.

Examples:

| City | Latitude | Longitude | Timezone |
| --- | ---: | ---: | --- |
| Philadelphia | `39.9526` | `-75.1652` | `America/New_York` |
| Los Angeles | `34.0522` | `-118.2437` | `America/Los_Angeles` |
| London | `51.5074` | `-0.1278` | `Europe/London` |
| Tokyo | `35.6762` | `139.6503` | `Asia/Tokyo` |

## Pass Options

`max_passes` controls how many passes the plugin asks Pollux to return. FiestaBoard caps this plugin at `5` because Vestaboard templates usually need the next pass or a short list.

`visible_only` defaults to `true`. With this setting on, Pollux only returns passes that should be observable with the naked eye, meaning the ISS is sunlit while the observer is in twilight or night.

`days_ahead` controls how far ahead to search. The default is `10`; the maximum is `14`.

## Timezone

Pollux returns timestamps in UTC. The plugin keeps UTC variables available and also converts pass times into the configured local timezone.

Use an IANA timezone name, such as:

- `America/New_York`
- `America/Los_Angeles`
- `Europe/London`
- `Asia/Tokyo`
- `UTC`

## Caching

FiestaBoard calls this plugin as live data so countdown variables can update on each render. The plugin still caches the Pollux API payload internally for `refresh_seconds`, which defaults to one hour.

The plugin refreshes early if the first cached pass has already reached its `set.time`. This keeps a request for the next `5` passes replenished instead of shrinking after each completed pass.

If the API refresh fails and the cached payload matches the same location/options, the plugin uses the stale cache rather than returning an empty result.

## Example Template

```text
{{iss_flyover_tracker.status}}
{{iss_flyover_tracker.next_rise_local}}
RISE {{iss_flyover_tracker.rise_heading}} SET {{iss_flyover_tracker.set_heading}}
MAX {{iss_flyover_tracker.max_elevation_deg}} DEG
VISIBLE {{iss_flyover_tracker.visible_duration}}
```

## No API Key Needed

This plugin calls:

```text
https://iss-api.polluxlabs.io/iss-pass
```

No API key or environment variable is required.
