# HC day-ahead forecasting — local implementation

Base: published HEMS dev.329, main d7ced9b3f0ed255144d87a3e48187f9a2e37e4d7.
Alex confirmed recovery live and authorised this separate HC extension. He selected
recent measurements as provisional fallback rather than a fixed kWh reserve.

## Implemented

- HC independently builds and persists a downstairs day forecast covering remaining
  today and tomorrow. Noon, restart, schedule/settings, material temperature/model/
  weather changes and periodic refresh cause publication without waiting for prices.
- Existing learned steady, warmup and cooling evidence is reused. Whole-day setback,
  warmup and maintenance are integrated with a simulated indoor temperature.
- Hourly weather takes precedence; daily weather is explicitly a cold-side scenario.
  Sparse compatible evidence supports a labelled provisional estimate. Without usable
  evidence the status is unavailable, never an invented zero requirement.
- HEMS captures the new source in Planning Input and replaces exact historical airco
  attribution before candidate calculation. It preserves other household/EV demand,
  the current-load guard and reviewed CV auxiliary attribution. Existing accepted HC
  profiles can subsequently replace the day forecast using a rebased component.
- Provisional forecast intervals have confidence capped at 0.5 and revision provenance.
- HC displays date, per-period kWh, limitations and whether HEMS has adopted the same
  revision. Forecast plus HEMS receipt are included in building-export metadata.

See V2ADR-069 for estimation assumptions, ownership and fallback policy.

## Fresh verification

Python 3.12 integrated suite: **160 passed**, 155.42 seconds. Command:

```text
python -m pytest picot_hc/tests/test_day_ahead.py tests/test_hc_day_ahead.py
  tests/test_load_replacement.py tests/test_accepted_loads.py
  tests/test_controlled_load_history.py tests/test_v2_live_storage_ingestion.py
  tests/test_v2_live_household_load_fallback.py picot_hc/tests/test_energy_outlook_hc.py
  picot_hc/tests/test_energy_proposals.py picot_hc/tests/test_cooling.py
  picot_hc/tests/test_warmup_energy.py -q
```

Final focused suite after formatting: **16 passed**. Tests cover noon without HEMS
prices, next-day warmup/maintenance, 23/25-hour days, persistence/restart, withdrawal,
minor-change stability, weather precedence, unknown energy, malformed payloads,
staleness, exact replacement and near-term replacement of that replacement.
An assembly test verifies 1000 Wh historical house demand with a 200 Wh airco share
becomes 2000 Wh when HC forecasts 1200 Wh, while the separately reviewed 50 Wh CV
component remains attributed. Actual observation/history is unchanged.

Ruff passes for both new modules/tests and touched Planning Input. Targeted strict
Mypy passes for the new HEMS module and Planning Input. Node syntax check passes for
the dashboard script. No physical device or Home Assistant instance was controlled.

The first broader run used an unwritable Windows sandbox temporary directory.
Rerunning with a workspace temporary directory resolved those setup/cleanup failures.
The HTTP API schedule test still fails with WinError 10013 (socket access denied),
reproduced independently on the untouched dev.329 baseline. Full browser/HTTP,
Linux release CI and live adoption remain unverified; do not represent these as passed.

## Operational boundaries

This is an airco electricity scenario under the configured schedule, not a forecast
of future CV source selection. Accepted near-term source plans take precedence.
Exact historical attribution is required to replace heating without duplication;
if unavailable, HEMS visibly retains its house forecast. Usable complete energy
measurements are still required for a provisional estimate. This does not promise
that this installation already has enough evidence, or that tomorrow's live forecast
will be adopted immediately after installation.

HEMS retains its existing planning horizon, commitments, recovery checks and physical
limits. No changes to the learned-model recording requirements, compressor controls,
phone notification delivery, version manifests, release or live installation.
