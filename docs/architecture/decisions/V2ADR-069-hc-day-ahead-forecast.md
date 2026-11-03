# V2ADR-069 — HC day-ahead electricity forecast

Status: implemented locally, pending release verification. 3 November 2026.

HC owns the downstairs thermal forecast. With automatic heating and the weekly
schedule enabled, it publishes `sensor.picot_hc_day_ahead` independently of
Nordpool, HEMS feasibility or device-start permission. Publication occurs at
startup, noon Europe/Amsterdam, relevant inputs changing and at least every
30 minutes. It covers remaining today and all tomorrow, including setback,
preheating and maintenance. UTC intervals preserve actual DST durations.

`hc-day-ahead:v1` carries delivery date, generation/expiry, source identity,
input fingerprint, revision, interval Wh and explicit quality reasons. It is
persisted in HC SQLite and republished after a fresh restart assessment.
Transport failure is retried; stale data expires after two hours. Disabling
automatic scheduled heating withdraws the forecast. No forecast grants device
execution permission or changes compressor protection.

## Estimation policy

Reuse the existing measured warmup, steady-load and cooling models. Simulate
indoor temperature forward between intervals; do not copy today's temperature
unchanged into tomorrow. Warmup consumes a finite energy/time trajectory.
Forecasts assume the schedule is followed and airco supplies the heat. This is
an explicit electricity scenario, not a prediction of future CV selection.
An accepted short-term source proposal takes precedence through existing load
replacement. Gas is never presented as electricity.

Real hourly weather takes priority. Daily-only Buienradar data supplies its
lowest reported temperature as a labelled cold-side scenario throughout that
date. This is not an hourly weather forecast. Missing weather uses current
outdoor temperature, with a visible limitation. No invented wind/cloud curve.

Alex selected recent measurements as provisional fallback. One or more recent
compatible completed samples can therefore support a provisional estimate even
before the normal three-sample model is ready. Same equipment identity and
seven-day freshness are required. Provisional steady heat scales measured power
by indoor/outdoor difference within 5 degrees outdoor and 3 degrees target;
warmup scales measured energy and duration by temperature rise. Both retain a
25% margin. These are labelled estimates, not calibrated guarantees. Unknown
cooling assumes the setback is reached rather than promising free retained heat.
Without usable energy/warmup evidence, HC publishes unavailable with a reason,
not a zero-kWh forecast. No arbitrary fixed reserve is introduced.

## HEMS ownership and precedence

Planning Input captures and validates the forecast before candidate generation.
It replaces only the exact airco component of the existing historical forecast.
The separate reviewed CV auxiliary component, EV exclusion and other household
load remain intact. Current excess-load guard remains protected for its existing
15-minute window. Application is bounded by the existing HEMS planning horizon.
The combined replacement basis is rebased to let accepted HC profiles replace
the day forecast later, rather than add another heating demand.

If exact attribution is unavailable, use the existing household forecast with
the explicit reason `hc_forecast_exact_heating_attribution_missing`. Do not
subtract an unproved historical component or silently add duplicate heating.
Provisional intervals carry confidence capped at 0.5 and revision provenance.
The original observation/history is never changed. Existing planning triggers,
commitments, recovery and SOC/physical constraints remain authoritative.

HC displays forecast intervals, estimated kWh, limitations and the HEMS receipt
revision. It distinguishes waiting for a new revision from adoption. Forecast
and HEMS status are also included in HC export metadata. A receipt proves input
adoption, not that a particular battery route has already been replaced.
