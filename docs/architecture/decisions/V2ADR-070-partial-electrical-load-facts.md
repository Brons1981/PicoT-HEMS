# V2ADR-070: Independent electrical load facts and bounded recovery evidence

Status: implemented locally, not released. Date: 2026-11-06.
Baseline: main daa1d5e1b5be971c1a12735a6d14dc4d25bc269c (HEMS333 / HC31).

## Ownership and contract

HC owns comfort, targets, source choice and restart protection. HEMS receives electrical
load windows, expected energy when supported, validity, provenance and uncertainty.
No climate targets are transmitted in the day-ahead publication. Climate targets remain
inside HC's local forecast/dashboard. The existing hc-day-ahead:v1 envelope is extended
with load_facts; older consumers safely fall back on status=partial. Existing complete
forecasts remain compatible. Both apps must be updated to use partial forecasts.

Each fact has start/end, timing_status, operation, energy_status, nullable energy_wh and
reason. HEMS records validated facts in PlanningInputSnapshot.external_load_facts as
immutable ExternalLoadFact values, with source/revision/generated_at/valid_until.
Known schedule timing survives absent warmup measurements, missing thermal context and
energy-model failures. Unknown energy is never represented by zero. Timing alone does
not authorize removal of unmeasured household demand: historical household estimates
remain for unknown energy periods and absent exact airco attribution.

HC may independently quantify current maintenance using valid steady measurements and
an initial off period using measured cooling. The latter is explicitly provisional:
continued scheduled heating until release is assumed to preserve the lower of current
indoor temperature and the current target. The off estimate ends at the predicted
room-limit crossing, next schedule boundary or conservative earliest preheat start.
These climate calculations stay in HC. Potential later heat remains unknown/fallback.
No whole-night zero demand is inferred just because an evening window ends.

HEMS validates freshness, times, sources and bounded energy separately. Independently
valid energy intervals replace only the exactly attributed historical airco component;
unknown periods, EV exclusions, other house demand, CV auxiliary attribution and the
near-term actual-load guard remain intact. Replacement attribution is rebased for later
accepted HC near-term profiles. Confidence is capped at 0.5 for provisional/partial energy.

## Bridge recovery

Generate a shortest sufficient contiguous standby span for each eligible starting
interval, including spans crossing quarter-price changes. Binary search probes are not
added to the portfolio. Export, committed charging, reserve and PV-surplus boundaries
are excluded from these new spans. Existing financial selection and the EUR0.01
financial equivalence rule remain unchanged. No replacement main charge window is
invented. This is bounded candidate discovery, not exhaustive global optimization of
all disjoint standby combinations.

## Evidence

An incident larger than 8 MiB still drops the full replay payload. It now retains compact
financial/validity/selection evidence, winner/incumbent first, with a 512-candidate and
512-KiB bound. Explicit completeness/omission metadata avoids claiming the summary is
full replay evidence. Aging and download preserve this compact explanation.

## Limits

This does not establish which live plan would have won on 5 November at 21:42: its full
input/comparison was not retained. No live device settings, plans, release or installation
are changed. Missing historical attribution or unknown energy still requires fallback;
there is no fabricated fixed heating-power assumption.
