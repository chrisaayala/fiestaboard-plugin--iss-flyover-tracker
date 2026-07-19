# ISS Flyover Tracker

FiestaBoard plugin that shows upcoming International Space Station passes for a configured location using the Pollux Labs ISS Pass API.

## Configuration

- `latitude`: Observer latitude. Defaults to Philadelphia, PA (`39.9526`).
- `longitude`: Observer longitude. Defaults to Philadelphia, PA (`-75.1652`).
- `max_passes`: Maximum passes to request. Defaults to `5`, max `5`.
- `visible_only`: Only return naked-eye visible passes. Defaults to `true`.
- `days_ahead`: Forecast window in days. Defaults to `10`, max `14`.
- `timezone`: Timezone for local display strings. Defaults to `America/New_York`.
- `refresh_seconds`: Refresh interval. Defaults to `3600`.

See [docs/SETUP.md](docs/SETUP.md) for setup details and example location values.

## Variables

Use variables in FiestaBoard templates with the `iss_flyover_tracker` prefix, for example:

```text
{{iss_flyover_tracker.next_rise_local}}
```

### Next Pass

| Variable | Description | Example |
| --- | --- | --- |
| `{{iss_flyover_tracker.status}}` | Current ISS pass status. | `VISIBLE` |
| `{{iss_flyover_tracker.summary}}` | Compact one-line summary of the next pass. | `ISS Jul 19 8:58 PM EDT NNW->NE` |
| `{{iss_flyover_tracker.pass_count}}` | Number of passes returned by the API. | `3` |
| `{{iss_flyover_tracker.next_rise_utc}}` | Next pass rise time in UTC. | `2026-07-20T00:58:32Z` |
| `{{iss_flyover_tracker.next_rise_local}}` | Next pass rise time formatted in the configured timezone. | `Jul 19 8:58 PM EDT` |
| `{{iss_flyover_tracker.next_rise_date_local}}` | Next pass local date. | `Jul 19` |
| `{{iss_flyover_tracker.next_rise_time_local}}` | Next pass local time. | `8:58 PM` |
| `{{iss_flyover_tracker.time}}` | Next pass local time without AM/PM. | `8:58` |
| `{{iss_flyover_tracker.time_12h}}` | Next pass local 12-hour time with AM/PM. | `8:58 PM` |
| `{{iss_flyover_tracker.time_24h}}` | Next pass local 24-hour time. | `20:58` |
| `{{iss_flyover_tracker.timezone_abbr}}` | Timezone abbreviation for the local pass time. | `EDT` |
| `{{iss_flyover_tracker.day_of_week}}` | Local day of week for the next pass. | `Sunday` |
| `{{iss_flyover_tracker.day}}` | Local day of month for the next pass. | `19` |
| `{{iss_flyover_tracker.seconds_until_next_occurrence}}` | Seconds until the next pass rise time, recalculated each fetch. | `42212` |
| `{{iss_flyover_tracker.minutes_until_next_occurrence}}` | Whole minutes until the next pass rise time, recalculated each fetch. | `703` |
| `{{iss_flyover_tracker.culmination_utc}}` | Time when the ISS reaches maximum elevation in UTC. | `2026-07-20T01:00:10Z` |
| `{{iss_flyover_tracker.culmination_local}}` | Local time when the ISS reaches maximum elevation. | `9:00 PM` |
| `{{iss_flyover_tracker.duration_seconds}}` | Total pass duration in seconds. | `197` |
| `{{iss_flyover_tracker.duration}}` | Total pass duration formatted for display. | `3m 17s` |
| `{{iss_flyover_tracker.rise_heading}}` | Compass heading where the ISS rises. | `NNW` |
| `{{iss_flyover_tracker.rise_azimuth_deg}}` | Rise azimuth in degrees. | `339.3` |
| `{{iss_flyover_tracker.set_heading}}` | Compass heading where the ISS sets. | `NE` |
| `{{iss_flyover_tracker.set_azimuth_deg}}` | Set azimuth in degrees. | `37.1` |
| `{{iss_flyover_tracker.max_elevation_deg}}` | Maximum elevation above the horizon in degrees. | `12.8` |

### Visibility

| Variable | Description | Example |
| --- | --- | --- |
| `{{iss_flyover_tracker.is_above_horizon}}` | Whether the pass rises above the configured horizon threshold. | `yes` |
| `{{iss_flyover_tracker.is_visible}}` | Whether the pass is observable with the naked eye. | `yes` |
| `{{iss_flyover_tracker.next_visible_start_utc}}` | Visible portion start time in UTC. | `2026-07-20T00:59:38Z` |
| `{{iss_flyover_tracker.next_visible_start_local}}` | Visible portion start time in the configured timezone. | `8:59 PM` |
| `{{iss_flyover_tracker.next_visible_end_utc}}` | Visible portion end time in UTC. | `2026-07-20T01:01:49Z` |
| `{{iss_flyover_tracker.next_visible_end_local}}` | Visible portion end time in the configured timezone. | `9:01 PM` |
| `{{iss_flyover_tracker.visible_duration_seconds}}` | Visible portion duration in seconds. | `130` |
| `{{iss_flyover_tracker.visible_duration}}` | Visible portion duration formatted for display. | `2m 10s` |

### Location

| Variable | Description | Example |
| --- | --- | --- |
| `{{iss_flyover_tracker.latitude}}` | Observer latitude used for the API request. | `39.9526` |
| `{{iss_flyover_tracker.longitude}}` | Observer longitude used for the API request. | `-75.1652` |
| `{{iss_flyover_tracker.timezone}}` | Timezone used for local display strings. | `America/New_York` |

### System

| Variable | Description | Example |
| --- | --- | --- |
| `{{iss_flyover_tracker.satellite}}` | Satellite name returned by the API. | `ISS (ZARYA)` |
| `{{iss_flyover_tracker.generated_at_utc}}` | API response generation time in UTC. | `2026-07-19T18:06:09Z` |
| `{{iss_flyover_tracker.tle_epoch_utc}}` | TLE epoch used by the API in UTC. | `2026-07-19T04:27:19Z` |
| `{{iss_flyover_tracker.tle_age_hours}}` | Age of the orbital elements in hours. | `13.6` |

### Passes Array

The plugin also exposes a `passes` array with details for each returned pass. Use indexed fields such as:

```text
{{iss_flyover_tracker.passes.0.rise_local}}
{{iss_flyover_tracker.passes.1.max_elevation_deg}}
```

Available pass fields:

- `rise_utc`
- `rise_local`
- `rise_date_local`
- `rise_time_local`
- `time`
- `time_12h`
- `time_24h`
- `timezone_abbr`
- `day_of_week`
- `day`
- `seconds_until_next_occurrence`
- `minutes_until_next_occurrence`
- `visible_start_utc`
- `visible_start_local`
- `visible_end_utc`
- `visible_end_local`
- `culmination_utc`
- `culmination_local`
- `duration`
- `visible_duration`
- `rise_heading`
- `set_heading`
- `max_elevation_deg`
- `is_above_horizon`
- `is_visible`

## API

Data comes from `https://iss-api.polluxlabs.io/iss-pass`.
