# HC day-ahead heating forecast — investigation, 3 November 2026

Status: investigated scope, NOT implemented in the safe-mode repair.
Requirement: with automatic scheduled heating enabled, HC publishes tomorrow's
heating energy by interval around 12:00 Europe/Amsterdam. HEMS captures it before
building tomorrow's main plan on Nordpool price publication (typically 12:30–14:00
per user). Current scope is downstairs, without adding other zone control.

## Existing capabilities and gaps

HC has learned startup, warmup, maintenance and cooling models. Proposals address
the current or next comfort window and depend on a fresh HEMS replacement basis.
Delayed-start candidates are bounded to 15 hours. The proposal contract permits
at most twelve slots, requires a matching current HEMS snapshot and expires within
180 seconds. HC reservations renew within 120 seconds. This is not a durable
forecast for tomorrow. HEMS has controlled-load attribution/replacement machinery
and a shared live input capture seam.

Recorded HEMS snapshots on 2–3 November contain no accepted-load profile. The HC
export is building measurements, not runtime proposal state, so it does not establish
which prerequisite blocked proposals or whether learning was enabled.
Buienradar hourly status is unsupported. Current code then uses existing models
without hourly adjustment: unsupported is NOT by itself an automatic proposal blocker.
Daily weather data must not be represented as hourly forecast evidence.

## Required implementation

1. Build an HC forecast independent of Nordpool availability, HEMS selected plans
   and start permission. Expand tomorrow's entire schedule, including warmup before
   midnight. Predict indoor temperature at future starts using learned cooling and
   heating rather than today's temperature unchanged. Include warmup AND maintenance,
   weather and presence assumptions, and airco electricity versus CV gas/auxiliary load.
2. Define a versioned durable forecast: source/scope, delivery date/timezone,
   generation time, revision, schedule/model/weather fingerprints, interval Wh,
   confidence/range, provenance and explicit missing-data/fallback status. Persist
   and regenerate at noon, restart, late enablement and material input changes.
   Forecast publication grants no device execution permission.
3. Define conservative weather/learning fallback from evidence or configuration.
   Real hourly forecasts take priority. Daily-only weather and insufficient learning
   remain visible limitations; neither means zero demand. Do not fabricate hourly
   values from daily extremes without an explicitly documented estimation policy.
4. Capture the forecast in HEMS Planning Input before Candidate Generation. Replace
   only the attributed historical heating component, preserving household/EV load.
   Specify interval precedence with near-term accepted HC profiles to avoid duplication
   and a documented fallback for incomplete attribution.
5. Trigger main planning on price publication using the captured revision. Missing
   HC data must cause a visible fallback, not silent zero demand or a planning deadlock.
   Subsequent material updates use existing shortfall/replanning rules; preserve
   committed plans unless repair is necessary.
6. Expose forecast time/date, interval kWh, learning/weather quality, adopted revision
   and fallback reason. Include forecast and proposal/reservation status in diagnostics.

## Acceptance evidence

- At noon tomorrow evening's heating is forecast before its prices are available.
- The first main plan uses the captured HC revision; no duplicated heating load.
- Warmup and maintenance affect projected SOC/refill needs.
- Restart, late enablement, edits, weather changes and delayed prices recover.
- Disabling the automatic schedule withdraws the explicit forecast without deleting
  actual historical consumption or bypassing running-device safety.
- DST 23/25-hour days, midnight warmup, missing weather and sparse learning are covered.
- Unchanged forecasts cause no plan churn; credible shortfalls remain repairable.
- No direct HEMS thermostat control or short compressor cycles; ADR 1–37 ownership remains.

Sequence: publish/verify the isolated HEMS correction first, then implement the
HC–HEMS day-ahead feature with contract and integration tests as separate work.
