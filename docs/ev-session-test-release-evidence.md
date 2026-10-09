# EV session test release evidence — 2026-10-09

Prepared source versions: Energy Devices 0.4.0-dev.1; HEMS 2.0.0-dev.290.
Baseline: current main d45049208f495253767715df6e1aeb9dfe8b889f (fetch confirmed no divergence).
These changes have not been published, merged, installed or live-qualified.

## Implemented outcome

Energy Devices persists a recognized EV session, permits confirmed future placement after explicit vehicle-resume verification, and owns only the configured charger switch. The original meter and switch are sensor.shellyplugsg3_d885ac1e8c94_vermogen and switch.shellyplugsg3_d885ac1e8c94. Short pauses keep identity; unavailable readings cannot prove completion. Natural low-power completion requires five minutes of available evidence, and a confirmed end time provides a separate hard deadline. Switch service acknowledgement is checked via subsequent observed state. Explicit cancellation stops the selected charger, including a manually started recognized session. Restart, failed service calls and manual interruption are covered. Commands cannot target storage or arbitrary payload-selected entities.

A first thirty-second probe estimates power and integrates measured energy; it does not infer full duration. Duration is user-entered until complete usable session history exists. No BMW source has been configured or claimed. Energy is integrated power, with measurement gaps and uncertainty exposed.

HEMS reads the optional dated session snapshot, preserves physical RAW, and separates accepted forecast demand from actual battery-support policy. Only proven EV-covered historical observations provide a residual baseline when a confirmed session contribution is admitted; otherwise the existing conservative fallback/guard is used. Forecast energy is bounded by remaining energy and confirmed deadline. Heartbeat/revision and normal remaining-energy countdown do not request replanning. Meaningful session transitions use the existing 30-second material observation producer and canonical Runtime Monitor/MEP/Evaluation/Plan Builder path.

## Fresh checks on final source

- 93 affected pytest cases passed, including EV controller, HTTP UI, session planning, existing regulation API, external load policy, materiality, household-history persistence, packaging and version alignment.
- Real canonical MEP regression demonstrates session demand in Planning Input, a winner in Evaluation and output from Plan Builder with the same run/snapshot lineage.
- Ruff passed on src/picot and src/picot_energy_devices plus affected test files.
- Mypy passed on all 251 source files with a fresh cache. An earlier stale-cache tool internal error was resolved by fresh-cache verification.
- Node syntax check passed for embedded Energy Devices dashboard JavaScript.
- git diff --check passed.

A prior broad pytest run reported 1,997 passed, one skipped and two failures in 490.46 seconds. One was an in-process version import retained while release metadata was being updated; the other was a missing declared awesomeversion dependency in the local test tools. The dependency was installed and version assertions updated to the prepared release. All version checks passed in the fresh final affected suite. This report does not claim a second complete broad-suite run on final source.

## Practical acceptance still required

1. Publish/install the two independently switchable test updates; both session options default off.
2. Enable Energy Devices EV sessions and HEMS session ingestion using DOCS.md. Leave EV correction off.
3. Verify physical charging, manual plug off/on and actual BMW resumption; confirm that test in the UI.
4. Confirm one short future session, watch switching acknowledgement, actual power and snapshot/HEMS reason.
5. Test interruption, explicit resume, cancellation and completion; review resulting plan/SOC and logs.
6. Battery protection and long-running stability remain separate acceptance tests. A producer crash can leave the charger on until restart or manual off; independent HA P1 RAW fallback does not control the charger.

Original Gielz remains unchanged; the already-live HA RAW hold/fallback configuration is not altered by this feature.
