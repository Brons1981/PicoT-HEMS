# PicoT v2 Development Log

## 2026-08-19 — dev.118 scheduled PV baseline and diagnostic plan history

PicoT version: `2.0.0-dev.119`
Branch: `agent/dev118-plan-history-smart-discharge`
Baseline main commit: `ae38869dae1f2d9eacf7a4affa2893187e0913a0`
Architecture authority: ADR-001 through ADR-039 plus accepted V2ADR-051
State: **IMPLEMENTED and locally verified; not CI or live verified**

### COMPLETED

- Corrected the canonical storage baseline outside a selected PV-acquisition
  window to `BALANCE_DISCHARGE_ONLY`, translated by the existing adapter to
  `Alleen slim ontladen`.
- Preserved `BALANCE_BIDIRECTIONAL` / `Nul op de meter` for the selected
  PV-acquisition window itself.
- Added passive persistence of a complete canonical planning snapshot whenever
  the semantic plan outcome changes, including evaluation, candidates,
  outcomes, execution plans and vendor result.
- Kept existing fallback lifecycle history and five preceding in-memory polls.
- Bounded diagnostic growth by fingerprinting semantic plan state instead of
  persisting an unchanged multi-megabyte candidate set every planner cycle.

### DECISIONS MADE

- A future `pv_charge_only` winner does not activate NOM before
  `valid_from`.
- The normal mode before and after the selected acquisition window is
  `Alleen slim ontladen`, independent of the household optimisation regime.
- A plan-history snapshot is persisted when evaluation status/reason,
  decisive step, winning family, future window, lifecycle, primitive or vendor
  mode changes.
- Diagnostic persistence remains a passive consumer of immutable canonical
  output and does not calculate or alter planner decisions.

### VERIFIED

- Pytest: **875 passed**.
- Ruff: changed v2 source and tests green.
- Mypy: **Success**, 51 v2 source files checked.
- The repository-wide Ruff command still reports 83 pre-existing legacy
  findings outside this change; no unrelated legacy files were modified.

### NOT LIVE VERIFIED

- dev.118 has not yet been installed in Home Assistant.
- The overnight transition must confirm `Alleen slim ontladen` before the
  selected window, NOM at `valid_from`, and return to smart discharge at
  `valid_until`.
- A fresh diagnostics export must confirm `planning_outcome_changed` records
  after dev.118 without a fallback incident.

### DO NOT CHANGE / CRITICAL CONTEXT

- Do not let low-confidence future PV activate NOM before the selected window.
- Do not persist every unchanged minute-level candidate set; the live candidate
  payload can be many megabytes.
- Preserve manual override and fallback/storing behaviour.
- Do not move vendor mode names into Core decision logic.

### EXACT CURRENT POSITION

Phase: canonical storage lifecycle correction and diagnostics
Version: `2.0.0-dev.119`
Position: implementation prepared from dev.117; CI and live verification remain.

### FIRST NEXT ACTION

Run CI, merge the dev.118 release PR after it is green, install it in Home
Assistant, and verify the scheduled smart-discharge → NOM → smart-discharge
lifecycle plus normal plan-history export.


## 2026-08-15 — Actual PV evidence, confidence and sunset-relative attenuation foundation

PicoT version: `2.0.0-dev.43`  
Branch: `main`  
Last verified main commit: `b33903cd2944e59434b2c1a08d363bd4eae0f608`  
Architecture authority: ADR-001 through ADR-039 plus accepted V2ADRs  
State: **CI_VERIFIED and LIVE_VERIFIED**

### COMPLETED

- Replaced inferred actual-PV behaviour with read-only GoodWe history from the configured Home Assistant power entity.
- Defined deterministic GoodWe state-transition/sample-hold energy conversion with explicit method version and bounded history reads.
- Preserved unavailable source states, interruptions and gaps instead of silently interpolating them.
- Actualised all closed PV forecast intervals using one bounded history read and a bounded runtime cache.
- Added complete per-interval actual-versus-forecast deviation evidence, including:
  - central, lower and upper Solcast forecast energy;
  - actual PV energy;
  - signed and absolute deviation;
  - percentage and direction;
  - forecast-range assessment;
  - forecast and actual confidence;
  - evidence IDs and conversion/evaluation method versions.
- Added cumulative closed-interval PV evidence with explicit coverage ratio, gap count, total actual/forecast energy and range assessment.
- Preserved Solcast estimate10/central/estimate90 ranges and interval confidence as canonical, traceable Planning Input.
- Added future PV forecast assumptions to Candidate Engine without allowing missing or weak evidence to become hidden certainty.
- Accepted `V2ADR-048` for confidence-aware PV planning across the complete household HEMS scope, not only battery planning.
- Accepted `V2ADR-049` for evidence-backed PV attenuation profiles.
- Built the V2ADR-049 foundation in test-first slices:
  - immutable attenuation evidence and profile contracts;
  - evidence capture;
  - eligibility classification;
  - sunset-relative bucket aggregation;
  - side-by-side original and corrected forecast ranges;
  - observer-only runtime projection;
  - live derivation of future attenuation ranges;
  - deterministic interval-midpoint offsets relative to sunset;
  - read-only Home Assistant `sun.sun.attributes.next_setting` source;
  - visible sunset source, timezone and offset lineage;
  - live coupling of sunset offsets into attenuation range derivation.
- Added explicit add-on options:
  - `pv_installation_scope_id`;
  - `pv_local_timezone`, default `Europe/Amsterdam`.
- Kept every attenuation result observer-only and prevented any Candidate, Evaluation, execution-plan or device-control influence.
- Advanced and live-validated releases from dev.22 through `2.0.0-dev.43`.

### DECISIONS MADE

- ADR-001 through ADR-039 remain authoritative.
- ADR-040 through ADR-047 are not reliable v2 authority and must not be used.
- New v2 decisions use the `V2ADR-` namespace.
- Solcast confidence is interval-specific. A poor earlier forecast may not invalidate a later interval with stronger confidence.
- PV evidence and corrections apply to PicoT's complete household planning scope, including storage and future controllable devices.
- Solcast's installation-wide dampening is insufficient for this installation because the east/west roof can have different shading behaviour.
- The first generic PicoT attenuation implementation uses evidence-backed total-installation output versus forecast, grouped by time relative to sunset.
- A fixed hard-coded evening reduction is forbidden.
- A profile may only arise from eligible historical evidence with explicit sample count, confidence, method version, installation scope and local timezone.
- Missing profile or missing sunset evidence must remain explicit. PicoT must use factor `1` and may not invent a correction.
- Home Assistant currently proves only the next sunset. PicoT does not synthesize additional horizon-day sunsets.
- The live runtime remains observer-only until a learned profile is separately validated and deliberately allowed into planning.

### CI VERIFIED

All feature and release pull requests through PR #260 completed with green PicoT Core CI, PicoT v2 Rebuild and Tests workflows.

Relevant final slices:

- PR #254 — live attenuation range derivation;
- PR #256 — deterministic sunset offsets;
- PR #257 — Home Assistant sunset source;
- PR #258 — visible sunset runtime diagnostics;
- PR #259 — live sunset attenuation coupling;
- PR #260 — release alignment to `2.0.0-dev.43`.

### LIVE VERIFIED

The Home Assistant add-on is live on `2.0.0-dev.43`.

Planning Input showed:

- `pv_sunset_source_status: available`;
- `pv_sunset_source_entity_id: sun.sun`;
- `pv_sunset_local_timezone: Europe/Amsterdam`;
- `pv_sunset_date_count: 1`;
- `pv_sunset_offset_interval_count: 45`;
- `pv_sunset_offset_method_version: pv-sunset-offset:interval-midpoint:v1`;
- `pv_sunset_source_method_version: home-assistant-sun-next-setting:v1`;
- no sunset source error.

Attenuation runtime showed:

- 72 future forecast intervals;
- zero available corrected intervals;
- `pv_attenuation_runtime_status: unavailable`;
- `pv_attenuation_runtime_unavailable_reason: all_ranges_unavailable`;
- original and corrected central totals both `28276.6 Wh`;
- correction delta `0 Wh`;
- `observer_only: true`.

This is the expected safe state because sunset evidence is live but no learned attenuation profile exists yet.

### INSTALLATION CONTEXT FOR TOMORROW

- PV installation: east/west, tilt 24 degrees.
- East: 10 panels × 330 Wp; Solcast resource capacity DC 3.3 kW.
- West: 4 panels × 390 Wp; Solcast resource capacity DC 1.6 kW.
- Solcast provides separate east/west daily resource entities but the detailed interval forecast currently used by PicoT is installation-wide.
- GoodWe exposes total inverter power plus two PV-string currents and voltages; the validated actual-energy path currently uses total inverter power.
- Trees cause a repeatable production falloff toward sunset. The effect is strongest on the west side and may also affect the east side.
- Clear days show a recognisable, similarly shaped sunset-relative decline. This is evidence to evaluate, not permission to hard-code a curve.

### NOT YET IMPLEMENTED

- Historical attenuation evidence persistence across days.
- Selection of sufficiently clear and comparable historical days.
- Learned attenuation buckets with minimum sample count and bounded confidence.
- A live non-empty attenuation profile.
- Corrected future forecast totals other than the original factor-`1` fallback.
- Any Candidate, Evaluation, planning or control response to attenuation.

### DO NOT CHANGE / CRITICAL CONTEXT

- Do not hide confidence, source ranges, profile factors or reasons inside calculations.
- Do not use one unexplained whole-day percentage reduction.
- Do not infer tomorrow's sunset from today's single `sun.sun` value.
- Do not treat zero nighttime PV as useful attenuation evidence.
- Do not learn from gaps, unavailable GoodWe states or intervals without aligned forecast ranges.
- Do not let diagnostic projection become a second calculation or decision path.
- Do not enable control while building or validating the profile.
- Preserve the red-test → approved implementation → green CI → manual merge → separate release bump → live validation workflow.

### EXACT CURRENT POSITION

Phase: V2ADR-049 evidence-backed PV attenuation  
Version: `2.0.0-dev.43`  
Position: sunset evidence and sunset-relative offsets are live; the runtime can derive traceable future ranges but has no historical learned profile.  
State: foundation complete, CI verified and live verified; correction intentionally remains zero.

### FIRST NEXT ACTION

Start the historical attenuation-profile slice read-only:

1. inspect the accepted V2ADR-049 contract and the existing attenuation evidence, eligibility and bucket modules;
2. identify the smallest persistence boundary for eligible closed-interval evidence across multiple days;
3. define explicit clear/comparable-day eligibility without assuming that every forecast miss is shading;
4. specify minimum sample count, bounded factor and confidence rules per sunset-relative bucket;
5. preserve installation scope, local timezone, source evidence IDs and method versions;
6. present one exact failing test patch before implementation.

The first implementation must remain observer-only. It may produce and display a learned profile, but it may not alter Candidate Engine, Evaluation, execution planning or device control.


## 2026-08-14 — dev.20 live pipeline enrichment and dashboard

PicoT version: `2.0.0-dev.20`  
Branch: `main`  
Last verified main commit: `e981f3b31e088b464979de6d3715d776bb39db87`  
Architecture baseline: `8197abbefd969f10da5a8f27244862be07998299`  
Pipeline contract: v1  
State: **CI_VERIFIED and LIVE_VERIFIED**

### COMPLETED

- Rebuilt and incrementally enriched one canonical v2 pipeline from stage ① through ⑨.
- Connected Planning Input directly to configured Home Assistant source entities for:
  - P1 grid power;
  - PV power;
  - Zendure state of charge;
  - validated signed Zendure power plus power to/from house;
  - Solcast detailed PV forecast;
  - Nord Pool today/tomorrow prices.
- Added immutable lineage through the complete pipeline using one run and snapshot.
- Added current storage-state evidence.
- Added canonical PV-energy intervals and a readable PV timeline.
- Added household-load observations from the complete live power balance.
- Added persistent household-load history and a 36-hour quarter-hour forecast.
- Retained a configured constant-power fallback while historical coverage is insufficient.
- Added real price-opportunity detection for low-price and high-export-value windows.
- Kept stages ③ through ⑨ safely connected in observer-only mode.
- Added a live read-only ingress dashboard that refreshes every five seconds.
- Made source data, pipeline attributes and technical details readable without Lovelace YAML.
- Preserved open quarter-hour details during dashboard refresh.
- Added a price chart covering local market days from today 00:00 through tomorrow 24:00.
- Added faded elapsed prices, a clear `Nu` marker, detected-window colours and a grey unpublished region.
- Kept display-only historical prices separate from the future-only canonical Planning Input.
- Raised runtime and add-on versions together through dev.20 so Home Assistant reliably detects releases.

### CURRENT PIPELINE STATUS

| Stage | Status | Current responsibility |
| --- | --- | --- |
| ① Planning Input | Functional and live | Real HA evidence, prices, PV, storage and household-load forecast |
| ② Opportunity Engine | Functional first detector | Real low-price and high-export-value windows |
| ③ Candidate Engine | Scaffold | One fixed `reserve_first` baseline candidate |
| ④ Evaluation Engine | Scaffold | Selects the only technically valid baseline candidate |
| ⑤ Execution Plan Builder | Scaffold | Produces an empty plan set |
| ⑥ Execution Engine | Safely inactive | `no_due_segment` |
| ⑦ Execution Primitive | Safely inactive | `not_emitted` |
| ⑧ Device Adapter | Safely inactive | `not_invoked` |
| ⑨ Vendor / Result | Safely inactive | `not_dispatched` |

### DECISIONS MADE

- ADR-001 through ADR-039 remain the frozen architectural authority.
- ADR-040 and higher belong to the incorrect v1 trajectory and must not be used as v2 authority.
- A genuinely necessary new v2 decision is named `V2ADR-...`; no new V2ADR was necessary in this session.
- Existing ADRs are checked before inventing any new decision.
- The canonical planning horizon remains a rolling 36 hours with nominal 15-minute intervals; no clock-quarter alignment is required.
- The price dashboard is a separate calendar-day presentation window and does not change the canonical planning horizon.
- Historical display prices may not be reintroduced into Opportunity Engine decision input.
- Observer-only remains mandatory until the downstream execution contracts are deliberately implemented and verified.
- The custom ingress dashboard is the primary v2 diagnostic view; the old HA/ApexCharts dashboard is not the v2 source of truth.
- The configured live fallback is currently 250 W in Home Assistant for realistic testing. The repository default remains 500 W and must not silently overwrite the user's live option.

### MANDATORY GITHUB WORK METHOD

To avoid connector failures and preserve narrow reviewable changes:

1. Start from the four bootstrap documents in `SESSION_PROTOCOL.md`; do not perform a full repository sync.
2. Inspect only the relevant ADRs and source files read-only.
3. Prepare and present the exact test diff before writing.
4. Write only after explicit user approval.
5. Use one repository, one branch and one file path per write operation.
6. Reread every written file immediately.
7. Confirm the expected red test failure and verify it fails for the intended missing behaviour.
8. Apply the approved implementation one file at a time and reread each file.
9. Require Pytest, Ruff and Mypy to be green.
10. ChatGPT leaves the PR as draft; Alex performs `Ready for review` and the merge manually.
11. Reread `main` after the merge before starting the next step.
12. Never write directly to `main` and never retry a timed-out write before read-only verification.

### CI VERIFIED

- PR #202 — calendar-day price chart:
  - Tests workflow green;
  - PicoT v2 Rebuild green;
  - PicoT Core CI green.
- PR #203 — dev.20 release alignment:
  - Tests workflow green;
  - PicoT v2 Ruff, Mypy and Pytest green;
  - PicoT Core Ruff, Mypy and Pytest green.
- Runtime and Home Assistant add-on versions both equal `2.0.0-dev.20`.

### LIVE VERIFIED

- dev.20 runs in Home Assistant.
- The nine-stage dashboard refreshes continuously from one live pipeline run.
- Live source cards are readable and available.
- PV-energy and household-load forecast details render correctly.
- The price chart shows today and tomorrow, fades elapsed hours and marks the current time.
- Price-window colours and unpublished future periods render correctly.
- Observer-only status remains active; no device command is emitted or dispatched.

### NOT VERIFIED

- The automatic transition from household-load fallback to a history-derived forecast still requires sufficient recorded history and has not yet been live confirmed.
- Candidate generation from real opportunities, storage state, PV and household-load forecast is not implemented.
- Multi-candidate evaluation is not implemented.
- Execution plan segments and downstream control are not implemented or live enabled.

### KNOWN ISSUES / EXPECTED INCOMPLETE BEHAVIOUR

- Household-load forecasting may continue to report `fallback_active` and zero confidence until enough historical observations exist.
- Candidate Engine currently produces exactly one hard-coded baseline candidate.
- Evaluation currently has no meaningful alternative to compare.
- Execution Plan Builder intentionally produces no controllable segment.
- Stages ⑥ through ⑨ therefore remain safely inactive.

### DO NOT CHANGE / CRITICAL CONTEXT

- Do not use ADR-040 or higher as v2 architecture.
- Do not create a new V2ADR unless ADR-001 through ADR-039 genuinely leave a required decision unresolved.
- Do not bypass Candidate, Evaluation, Execution Plan or Execution Engine boundaries.
- Do not enable device control or add vendor commands while building stage ③.
- Do not let diagnostics calculate planner decisions or become a parallel data path.
- Do not mix historical display prices into future canonical decision data.
- Do not silently change Alex's live 250 W fallback configuration.
- Preserve one immutable snapshot, lineage and observer-only behaviour through all nine stages.

### EXACT CURRENT POSITION

Phase: canonical v2 pipeline enrichment  
Version: `2.0.0-dev.20`  
Position: stage ② has its first real price-opportunity detector; stage ③ remains a baseline scaffold.  
State: dev.20 is merged, CI verified and live verified.

### FIRST NEXT ACTION

Begin stage ③ Candidate Engine read-only:

1. read the Candidate Engine requirements in frozen ADR-001 through ADR-039 and the canonical pipeline contract;
2. inspect the current Candidate, EnergyPath, capability and evaluation contracts;
3. define the smallest first real candidate behaviour using existing price opportunities, storage state, PV forecast and household-load forecast;
4. confirm that no new V2ADR is necessary;
5. present one exact failing test patch before any write.

Do not implement the candidate logic until that test patch has been explicitly approved.

## 2026-08-13 — Phase B dev.1 bootstrap

PicoT version: `2.0.0-dev.1`
Branch: `rebuild/canonical-pipeline`
Architecture baseline: `8197abbefd969f10da5a8f27244862be07998299`
Pipeline contract: v1

### COMPLETED
- Phase A canonical rebuild contract frozen.
- V2ADR-001 accepted for direct configured HA source entities at the ingestion boundary.
- Isolated `src/picot/v2` package created; no v1 planner imports.
- Minimal canonical bootstrap pipeline created.
- Passive nine-card diagnostic projection created.
- Diagnostic runtime cost measurement added.
- HA projection sink isolated from planner/projection logic.
- Add-on version changed to `2.0.0-dev.1`.
- Add-on `run.sh` starts only `picot.v2.live_runtime`.
- Add-on Dockerfile installs `rebuild/canonical-pipeline`, not `main`.
- Legacy v1 add-on options removed from dev.1 config.
- v2-only pytest/Ruff/Mypy workflow added.
- v2 lineage/no-dispatch tests added.

### DECISIONS MADE
- One repository remains in use so the existing HA add-on repository identity remains valid.
- v2 is isolated inside the repository and may not import v1 planner/runtime code without explicit ADR review.
- dev.1 contains no price, PV, storage or control intelligence.
- dev.1 performs one canonical bootstrap run only and then remains idle.
- Nine dashboard cards are a passive projection of canonical outputs, not an additional control path.

### CI VERIFIED
- None yet.

### LIVE VERIFIED
- None yet.

### NOT VERIFIED
- GitHub v2 CI has not yet run for current branch state.
- Home Assistant add-on build/install has not yet been tested.
- Nine HA entities have not yet been observed live.
- CPU/RAM impact has not yet been measured live.

### KNOWN ISSUES
- Draft PR creation via the GitHub connector was blocked by tool safety; no PR was created in this session.
- Existing package metadata in `pyproject.toml` still belongs to the legacy package line and has not yet been reviewed for v2 packaging identity.

### DO NOT CHANGE / CRITICAL CONTEXT
- Do not merge v2 to `main` before CI and HA live validation.
- Do not reintroduce `runtime_snapshot_entrypoint` or other v1 runtime/planner modules into v2.
- Do not add planner intelligence before the 1→9 bootstrap route is live and traceable.
- Diagnostic projection remains passive and must not reread HA or recalculate canonical planner values.

### EXACT CURRENT POSITION
Phase: B
Step: `2.0.0-dev.1` canonical pipeline bootstrap
State: IMPLEMENTED, not CI verified, not live verified

### FIRST NEXT ACTION
Run the isolated v2 CI against the current rebuild branch. Fix only v2 CI defects. When green, install/update the add-on from the rebuild branch in Home Assistant and verify all nine cards plus diagnostic performance before adding any intelligence.
## 2026-08-16 — canonical live Zendure control, dev.84 dashboard health and next roadmap

PicoT version: `2.0.0-dev.84`  
Branch: `main`  
Last verified main commit: `3f74754a246f4cdfebb85785bfaeed7c5d213859`  
Architecture baseline: `8197abbefd969f10da5a8f27244862be07998299`  
Pipeline contract: v1  
State: **MERGED, LIVE and initial dashboard behaviour verified**

### COMPLETED TODAY

- Closed the first real canonical battery-control path from Planning Input through Vendor Result.
- Enabled canonical live execution through the validated Zendure mode selector without moving vendor-specific decisions into PicoT Core.
- Added V2ADR-051 plan continuity and storage-mode lifecycle behaviour:
  - ordinary PV acquisition prefers `Nul op de meter` so short household-load changes remain delegated to the Zendure controller;
  - the baseline outside the PV acquisition window requests `Alleen slim ontladen`;
  - `Alleen slim opladen` remains available for an explicit non-discharge purpose, for example preventing battery discharge while an EV consumes PV;
  - a user-selected mode remains a manual override until explicit release;
  - previously selected rolling price quarters receive lower preference than a materially better future block rather than becoming permanently fixed.
- Added validated Zendure BMS calibration evidence so autonomous vendor-side cell balancing can be distinguished from an unexplained grid charge when PicoT is not commanding it.
- Added the dashboard authority-release action and fixed local-HTTP compatibility where `crypto.randomUUID()` is unavailable.
- Confirmed that authority release succeeds; the initial HTTP 409 was caused by the dashboard briefly re-reading an older projected snapshot after the backend had already released the override.
- Replaced observer-only Dutch summary text that remained visible during live execution.
- Added a prominent **Zendure nu** view with:
  - currently observed mode;
  - planned mode;
  - control origin;
  - last observation;
  - persisted PicoT application time;
  - latest vendor result.
- Added independent health indicators to pipeline cards 1 through 9:
  - green means the stage is technically healthy, including a valid no-op or already-active mode;
  - red means a real error, invalid/unavailable required state, or an essential mapping/provenance failure;
  - the dashboard shows an aggregate result such as `Pipeline werkt correct – 9/9 groen`.
- Made the dashboard header state-aware: `Live uitvoering` or `Alleen meekijken`.
- Upgraded persisted storage-mode provenance to schema v2 for `last_planner_applied_at`, while retaining read compatibility with existing schema-v1 state.
- Released and installed `2.0.0-dev.84`.

### GITHUB / VERIFICATION

- PR #341 — canonical storage-mode lifecycle, normal PV mode selection and calibration evidence.
- PR #343 — local-HTTP authority reset ID fallback.
- PR #344 — release `2.0.0-dev.83`.
- PR #345 — pipeline health, Dutch live summaries and Zendure-now status.
- PR #346 — release `2.0.0-dev.84`.
- Integrated feature verification before publication:
  - Pytest: **796 passed**;
  - targeted Ruff: green;
  - targeted Mypy: green.
- Home Assistant live verification:
  - dev.84 installed and running;
  - the dashboard appears healthy;
  - authority release works;
  - the first autonomous future plan/mode transition remains to be observed over time.

### CURRENT CANONICAL STATUS

| Stage | Status | Current responsibility |
| --- | --- | --- |
| ① Planning Input | Live | Configured HA evidence, Nord Pool, Solcast/GoodWe PV, household load, storage, provenance and capability evidence |
| ② Opportunity Engine | Live first scope | Low-price and high-export-value windows with explicit evidence |
| ③ Candidate Engine | Live battery scope | Baseline plus timed delegated PV-storage Candidates |
| ④ Evaluation Engine | Live initial policy | Selects a technically valid battery path through explicit storage progress/requirement rules |
| ⑤ Execution Plan Builder | Live battery scope | Converts the winning timed storage path into scope-specific segments |
| ⑥ Execution Engine | Live | Selects the due segment and grants or blocks execution authority |
| ⑦ Execution Primitive | Live | Emits validated delegated storage-mode requests |
| ⑧ Device Adapter | Live | Translates generic primitives to the configured Zendure mode selector |
| ⑨ Vendor Result | Live | Dispatches or records already-active/awaiting-feedback behaviour |

The first end-to-end battery slice is now real and live. This is not yet proof that every accepted function in ADR-001 through ADR-039 is implemented.

### ADR-001 THROUGH ADR-039 GAP FINDINGS

Implemented or substantially integrated:

- vendor-independent Core and deterministic no-AI runtime;
- one immutable Planning Input per run and complete ①→⑨ lineage;
- generic Execution Primitives and scope-specific execution plans;
- real price Opportunities;
- Current Storage State;
- canonical actual-plus-forecast PV Energy Timeline;
- household-load forecast, Projected Household Energy Balance and Storage Energy Requirement;
- timed delegated PV-storage Candidates and Outcomes;
- first deterministic Evaluation and live Zendure adapter route;
- manual mode provenance and explicit authority release.

Largest remaining development areas:

1. real Planner Strategy, User Objectives and full ADR-032 per-objective comparison;
2. broader complete Candidate outcomes, especially an explicit net-charge Candidate;
3. generic Runtime Monitor, resource-pressure state and material-change coordination;
4. generic commitments, switching budget and anti-flipper rules across devices;
5. Simple/Expert input, User Rules, Energy Profiles and Preferences Wizard;
6. EV and other flexible-device profiles plus household/per-phase capacity management;
7. full capability discovery, semantic mapping validation, mapping lifecycle/history and controlled replacement.

ADR-014 and ADR-022 allow progressive implementation. Missing future functions must remain explicit and may not be silently presented as complete.

### ACCEPTED ROADMAP REORDERING

The net-charge Candidate moves forward before the full Planner Strategy. Once it exists, PicoT can represent all currently relevant energy sources in the canonical Candidate pipeline:

- PV;
- the home battery;
- grid import;
- household demand;
- dynamic market prices;
- later flexible devices.

Accepted order:

1. preserve and observe dev.84 autonomous behaviour without unnecessary changes;
2. design and implement a historical energy/decision dashboard on one shared time axis;
3. implement the net-charge Candidate observer-only under ADR-037;
4. harden planning for autumn and winter;
5. run a 2027 no-saldering valuation in shadow mode inside the same canonical pipeline;
6. implement full Planner Strategy and comparable Candidate Outcomes;
7. complete generic Runtime Monitor and anti-flipper behaviour;
8. add User Objectives, Preferences Wizard and User Rules;
9. add EV/appliance profiles and phase-capacity planning;
10. complete capability discovery and persistent mapping management.

### HISTORICAL DASHBOARD REQUIREMENT

The next dashboard step must make it easy to identify what happened around a selected time. Relevant records share one time axis:

- PV production;
- grid import/export;
- household consumption;
- battery charge/discharge power;
- battery SoC;
- dynamic price;
- selected and observed Zendure mode as a time band;
- planned windows;
- planner decisions and decision reasons;
- command/feedback transitions;
- pipeline faults.

This requires durable event/decision history. The latest dashboard snapshot alone is insufficient.

### AUTUMN / WINTER HARDENING

The planner must be verified against:

- little or no usable PV;
- multiple dark days;
- short and interrupted PV windows;
- strongly changing cloud cover;
- insufficient PV before the required reserve deadline;
- cheap night-time grid energy;
- expensive morning/evening demand;
- an empty battery before the morning peak;
- optimistic or incomplete forecasts;
- insufficient remaining charge time;
- vendor-side tapering near full SoC;
- missing price or forecast evidence.

The planner may not keep waiting for PV when the canonical evidence proves that PV is insufficient or no longer recoverable.

### NET-CHARGE CANDIDATE — NEXT PLANNER SLICE

The observer-only Candidate must state explicitly:

- required grid energy and target deadline;
- selected low-price quarter-hours;
- expected later PV and battery headroom reserved for it;
- conversion and round-trip losses;
- charge-power/capability limits;
- minimum and maximum SoC;
- vendor tapering near full SoC as observed evidence, not invented Core control;
- source policy and why grid supplementation is allowed;
- why waiting for PV is or is not recoverable;
- switching impact and plan continuity.

Initial comparison set:

- PV-only;
- PV plus grid supplementation;
- grid-first for insufficient winter PV;
- hold current mode / no additional action.

Construction and simulation belong to Candidate processing. Evaluation may only compare already-derived outcomes.

### END OF SALDERING — 2027 SHADOW MODEL

External fact verified on 2026-08-16: the Dutch statutory saldering obligation ends on **2027-01-01**. Export remains eligible for supplier compensation; through 2030 the statutory minimum is 50% of the supplier's bare delivery tariff. Contract terms and permitted return costs remain relevant.

Authoritative public reference:

- https://www.rijksoverheid.nl/themas/klimaat-milieu-en-natuur/energie-thuis/salderingsregeling

PicoT must prepare early because direct self-consumption becomes materially more valuable.

Accepted boundary:

- do not build a second planner;
- calculate current-contract and 2027 valuation as explicit, versioned Candidate Outcome evidence inside the same canonical pipeline;
- start observer-only and show which Candidate would win under the 2027 valuation;
- do not let the shadow result control live execution until deliberately accepted.

Required tariff-policy inputs:

- all-in import price;
- bare delivery tariff;
- export compensation;
- return costs;
- tax and VAT treatment;
- contract validity interval;
- dynamic quarter-hour pricing where applicable;
- mapping/policy version and evidence source.

The dashboard should show current-policy cost, 2027-policy cost, direct self-consumption value, avoided import, export value and the difference between the two outcomes.

### DO NOT CHANGE / CRITICAL CONTEXT

- ADR-001 through ADR-039 remain the frozen architecture authority.
- ADR-040 through ADR-047 remain excluded from the v2 baseline.
- Use a V2ADR only when ADR-001 through ADR-039 leave a real unresolved decision.
- The 2027 calculation is Candidate Outcome evidence, not a parallel planner.
- Diagnostics display canonical records and may not become a second calculation path.
- Net charging requires explicit source permission and may not be implied by a generic charge primitive.
- PicoT continues to select generic primitives; the adapter alone maps them to Zendure modes.
- Preserve minimal mode switching and explicit manual authority.
- Keep the red-test → approved implementation → green CI → manual merge → separate release bump → live-validation workflow.

### EXACT CURRENT POSITION

Phase: canonical live battery pilot and expansion planning  
Version: `2.0.0-dev.84`  
State: first canonical battery route live; initial dashboard appears healthy  
Pending live evidence: first autonomous future mode/plan transition and persisted application timestamp  
Next implementation target: historical energy/decision dashboard foundation plus observer-only ADR-037 net-charge Candidate

### FIRST NEXT ACTION

Start tomorrow read-only with two narrow contracts:

1. identify the smallest durable event-history boundary for the shared-time-axis dashboard;
2. specify the net-charge Candidate and Outcome fields using ADR-024/030/031/032/037 and existing V2ADR-050 delegated-mode constraints.

Before implementation:

- prove that no second planner or diagnostic calculation path is introduced;
- define exact red tests;
- confirm how the Zendure adapter can execute the winning grid-charge primitive without Core vendor knowledge;
- keep the 2027 valuation observer-only and versioned.


## 2026-08-20 — 2.0.0-dev.119

- Fixed delegated storage evaluation so a requirement-satisfying PV-only path cannot lose to an earlier generated partial candidate.
- Active charge windows are preferred over future windows after hard constraints and grid-energy use.
- Partial candidates now rank by actual storage progress before deterministic generation order.
- Regression verified against planning incident run-426744e8c00cc75f; PR #421.

## 2026-08-20 — 2.0.0-dev.120

- Suppressed charge sessions of at most one percent when projected storage remains above the live Zendure minimum SoC until the next charge opportunity.
- Passed the live minimum SoC into the canonical storage capability as explicit reserve evidence.
- Limited baseline `Alleen slim ontladen` execution to a 15-minute replan window instead of the full rolling horizon.
- Replaced lowest-interval plan confidence with energy-weighted confidence across the intervals the plan actually depends on.
- Added explicit micro-charge suppression reasoning and regression coverage; PR #423.

## 2026-08-20 — 2.0.0-dev.121

- Restored future PV charging after a full battery when remaining evening PV delays the first discharge phase.
- Full storage now skips the first discharge phase and targets the next support phase after a real PV recovery window.
- Prevented delegated storage simulation from acquiring forecast PV beyond physical usable capacity.
- Preserved preferred price-window ordering, one-percent micro-charge suppression and Slim ontladen as the current baseline mode.
- Added a regression covering evening PV, overnight discharge and next-day PV replenishment; PR #425.

## 2026-08-20 — 2.0.0-dev.122

- Prevented zero-energy price and PV reservations from becoming active NOM execution segments.
- Limited a delegated PV execution window to the first and last interval with real storage acquisition.
- Preserved internal intervals within one charging phase to avoid unnecessary Zendure mode switching.
- Restored the 15-minute `Alleen slim ontladen` baseline until a future charging window actually starts.
- Added regression coverage for empty leading and trailing intervals while retaining preferred price-window ordering; PR #427.

## 2026-08-20 — 2.0.0-dev.123

- Ranked physically feasible PV charging plans by their real duration-weighted quarter-hour price.
- Removed broad `LOWEST_PRICE_WINDOW` candidate order as the deciding factor between feasible plans.
- Preserved dynamic charging duration from required energy and available PV instead of imposing a fixed window.
- Retained an already active valid charging window to prevent unnecessary Zendure mode switching.
- Added price-coverage and weighted-average regression coverage; PR #429.

## 2026-08-20 — 2.0.0-dev.124

- Prevented a moving 15-minute `due` baseline expiry from generating repeated false planning incidents.
- Retained complete incident evidence for 36 hours and compacted older records to essential decision and execution facts.
- Bounded dashboard incident reads to the final records instead of loading the complete JSONL history into memory.
- Rebuilt Home Assistant power history in retryable two-hour chunks so an initial timeout cannot leave graphs permanently incomplete.
- Added incident-retention, bounded-read and history-bootstrap regression coverage; PR #431.

## 2026-08-21 — 2.0.0-dev.125

- Committed canonical execution to an active PV-only NOM phase until its planned end.
- Prevented forecast-driven candidate trimming from alternating NOM and smart discharge during one charge session.
- Kept explicit completion, fallback, override and dispatch blockers as legitimate interruption paths.
- Added regressions for plan retention and target-completion release using incident runs from 21 August.

## 2026-08-21 — 2.0.0-dev.126

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Accepted V2ADR-052 for persistent plan commitment and material replanning.
- Persisted active delegated storage commitments atomically per execution scope
  and restored them after restart only when time, capability and execution
  invariants still validate.
- Preserved an active plan as an incumbent Candidate and Outcome so Candidate
  construction, Evaluation and Execution Plan Builder retain their canonical
  ownership instead of relying on a pipeline shortcut.
- Completed each storage Energy Path with its normal smart-discharge baseline
  before Plan Builder conversion and removed downstream baseline invention.
- Limited active-plan replanning to material completion, BMS calibration,
  manual-authority and capability changes; ordinary SoC, PV, price and vendor
  feedback progression no longer replaces the committed plan.
- Accepted V2ADR-053 and exposed versioned, traceable confidence components for
  PV, household load, storage state, requirement, charge window and capability.
- Kept unavailable future confidence explicitly unavailable instead of
  presenting or using an artificial zero or one hundred percent value.
- Corrected timed Candidate projection to select the charge segment from a
  complete Energy Path rather than its preceding discharge baseline.
- Verified the complete repository test suite: 900 tests passed. Ruff passed
  for every changed Python file; `git diff --check` and bytecode compilation
  passed. Mypy passed for all 53 v2 source files after explicit narrowing of
  persisted commitment, source-policy and decoded JSON types.

Not live verified:

- restart during an active PV-only charge commitment;
- one complete live charge-window lifecycle followed by smart discharge;
- live confidence-component presentation with current Home Assistant evidence.

Live installation finding and correction:

- the first dev.126 add-on image stopped at import time because its Dockerfile
  packaged `picot.v2`, `picot.domain` and `picot.adapters`, but not the canonical
  `picot.planner` owner of the delegated storage Evaluation Engine;
- the image now packages `picot.planner` explicitly and the add-on packaging
  contract test protects that runtime dependency;
- the corrected image still requires live verification after PR merge/rebuild.

Known release boundary:

- this remains a development release;
- an explicit grid-charge Candidate and autumn/winter validation remain future
  work before PicoT can be considered 2.0-ready.

Exact next action after installation: observe one complete live plan lifecycle,
including commitment recovery across a controlled add-on restart.

## 2026-08-21 — 2.0.0-dev.127

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Released the dev.126 add-on packaging correction under a new version so Home
  Assistant can discover and rebuild the image instead of reusing the broken
  dev.126 package.
- Packaged the canonical `picot.planner` layer required by
  `DelegatedStorageEvaluationEngine`.
- Added a regression assertion for the exact add-on Docker packaging boundary.
- Mypy passed for 53 v2 source files, Ruff passed and all 900 tests passed.

Exact next action: install dev.127, confirm the live runtime starts, then observe
one complete plan lifecycle before classifying the ADR restoration live verified.

## 2026-08-22 — 2.0.0-dev.128

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Removed price-opportunity margin and Candidate generation order as indirect
  authorities over delegated PV-window selection; Evaluation now compares the
  real duration-weighted average price of every technically available window.
- Constructed PV-only acquisition paths from the explicit lower Solcast basis
  when its validated forecast range is available, so charging duration expands
  conservatively instead of repeatedly appearing as three optimistic half-hour
  intervals.
- Added traceable equal-price ordering by confidence, distance to the
  PV-energy-weighted centre and finally the earlier window.
- Persisted a selected future PV plan before its execution phase, restored it
  after restart and retained it as the incumbent through ordinary progress.
- Limited commitments to their contiguous acquisition phase and projected the
  correct Zendure mode per execution segment.
- All 903 tests passed; Ruff passed for every changed file and Mypy passed for
  all 68 v2 and planner source files.

Exact next action: install dev.128 and verify that the selected future window,
its duration and plan identity remain stable through ordinary forecast and SOC
updates.

## 2026-08-22 — 2.0.0-dev.129

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Removed the separate forecast-independent incumbent calculation that reused
  only `target energy - current energy` and therefore omitted expected battery
  support before a future charge window.
- Rebuilt a committed window through the same complete remaining household
  Energy Path as every challenger, preserving its time bounds while updating
  expected storage use, energy at charge start, required addition and technical
  feasibility from current evidence.
- Made a full executable-interval change or loss of target feasibility an
  explicit material replanning boundary while preserving non-material plan
  stability.
- Added visible charge-start energy, projected pre-window storage use, gross
  required addition and forecast-basis evidence to the chosen-plan dashboard.
- Added an explicit confirmed `Planning resetten` action that atomically clears
  commitments and pending dispatch state, preserves history, learning and
  configuration, records an audit incident and immediately wakes a fresh
  Planner Run.
- Invalidated legacy commitments without the household-simulation method once
  on upgrade so dev.128 planning state cannot bypass the corrected calculation.

Exact next action: install dev.129, verify the first fresh plan's expected
storage energy at charge start, then exercise the manual planning reset once.

## 2026-08-22 — 2.0.0-dev.130

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Reproduced the live dev.129 regression from the 777 MB incident export: a
  continuous PV-surplus envelope yielded only its full selection, whose
  backward requirement projection collapsed onto the last possible
  15:00–18:30 acquisition window.
- Restored one progressive technical Candidate per possible surplus endpoint,
  allowing Evaluation to compare rolling minimal charge windows by actual
  feasibility and duration-weighted average price without moving price policy
  into Candidate construction.
- Tightened incumbent identity to both commitment start and end, preventing a
  challenger sharing only the old end time from receiving stability authority.
- Made requirement satisfaction a mandatory condition for commitment
  retention; an infeasible scheduled or active plan can no longer win through
  a stability step.
- Verified that the existing incident retention already reduced 73 records
  older than 36 hours to basic facts. The remaining size belongs to 534 full
  records inside the explicitly retained diagnostic window, so no recent
  evidence was silently discarded.
- Added regressions for progressive endpoint construction and replacement of
  an infeasible incumbent by a feasible challenger.

Exact next action: install dev.130 and confirm the first plan exposes multiple
PV Candidates and does not retain any Candidate with `Doel gehaald=false`.

## 2026-08-22 — 2.0.0-dev.131

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Separated the full charge-window target from the later reserve requirement:
  a PV Candidate must reach 100% at the end of its acquisition window and must
  still retain the storage capability's configured minimum SoC at the planning
  deadline. Normal post-charge household support no longer makes an otherwise
  valid full-charge plan appear infeasible merely because energy is below 100%
  at 20:00.
- Kept compatibility fail-closed when no explicit capability minimum SoC is
  available: the existing full deadline target remains authoritative instead
  of inventing a reserve value.
- Made the existing household confidence policy explicit for PV timing. When
  forecast confidence is below its established recovery threshold, equal-price
  and otherwise equivalent windows prefer the earlier feasible start. Only a
  confident PV forecast may use distance to the PV-energy centre as tie-break.
- Kept duration-weighted average price ahead of the timing tie-break. No price
  margin, confidence uplift or synthetic score was added.
- Exposed separate `Laaddoel 100% gehaald`, `Reserve bij deadline gehaald` and
  minimum-reserve evidence in the chosen-plan dashboard and JSON contract.
- Added focused regressions for both the separated energy requirements and the
  low-/high-confidence equal-price selection behavior.

Exact next action: install dev.131 and confirm an equal-price live plan chooses
the earlier feasible window at the current low PV confidence, while showing
both charge-target and deadline-reserve results separately.

Live verification, 2026-08-22:

- PicoT selected 12:30–16:00 from the equal-price period, confirming that the
  low-confidence earlier-window rule works live as intended.
- The plan projected 5.89 kWh at charge start, 2.27 kWh required addition and
  8.16 kWh at the end of the PV-only acquisition window; the separate 100%
  charge-window target was therefore correctly reported as satisfied.
- The later energy projection was 8.10 kWh, but the dashboard exposed a minimum
  reserve of 8.16 kWh instead of the configured 10% / 816 Wh. Consequently the
  reserve result and combined target result were incorrectly false.
- This proves that the accepted fail-closed compatibility path is active in the
  live runtime because `minimum_soc` is not reaching the canonical storage
  capability. The defect is not in average-price selection or household energy
  simulation.

First action next session: trace the configured Zendure minimum SoC through
adapter mapping and `LogicalCapabilitySnapshot`, then supply the real 10%
minimum to delegated storage simulation. Preserve the fail-closed fallback for
genuinely unavailable capability evidence and add an end-to-end regression that
8.10 kWh satisfies an explicit 816 Wh deadline reserve after reaching 8.16 kWh
at the charge-window end.

## 2026-08-22 — 2.0.0-dev.132

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Confirmed from the live add-on log and 765 MB incident export that dev.131
  completed exactly one canonical run at 02:04 and did not crash afterwards.
  The active commitment deliberately stabilized its planning signature, but
  the same skip path also prevented power-history and dashboard refreshes.
- Confirmed that there was one execution plan, not two overlapping plans. Its
  23-8 14:04 timestamp was the 36-hour plan horizon; the actual local segments
  were smart discharge until 12:30, PV-only NOM from 12:30 to 16:00 and smart
  discharge afterwards.
- Decoupled observer chart refresh from Planner execution. Every unchanged
  poll now advances canonical Home Assistant power history and atomically
  overlays both power-history and self-consumption views while retaining the
  existing Planner Run and commitment.
- Added the scheduled/active commitment phase to decision-input identity. The
  exact acquisition start therefore triggers canonical execution even when
  ordinary SoC, power and forecast progress remains intentionally suppressed;
  commitment removal at its end already triggers the return to baseline.
- Preserved the V2ADR-052 stability invariant: ordinary commitment progress
  does not become authority for selecting a new plan.
- Added regressions for observer refresh without replanning, immutable Planner
  identity during that refresh, and a material scheduled-to-active boundary.
- Ruff and Mypy passed; all 913 tests passed.

Exact next action: install dev.132 and verify that graph data progresses beyond
the initial two-hour bootstrap while the plan identity remains stable, then
confirm NOM is applied at the committed charge-window start.

## 2026-08-22 — 2.0.0-dev.133

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

- Live dev.132 selected a new PV-only window starting exactly at its 08:48:56
  capture time and immediately requested NOM, despite the intended favourable
  window being later in the day.
- Traced this to an Evaluation tie-break that ranked any uncommitted Candidate
  containing the current instant ahead of duration-weighted average price.
  That made “can start now” an undocumented optimization objective and allowed
  it to override the established cost-first ordering.
- Removed only that active-now preference. Hard feasibility, grid contribution
  and valid incumbent commitment retention remain ahead of price; average
  price, explicit PV-timing confidence and deterministic timing tie-breaks keep
  their existing order.
- Added a regression proving that an uncommitted, more expensive window active
  now cannot outrank an otherwise equivalent cheaper future window.
- Ruff and Mypy passed; all 914 tests passed.

Exact next action: publish dev.133 and confirm PicoT remains in smart discharge
until the selected favourable PV-only acquisition window actually starts.

Live verification, 2026-08-22:

- Dev.133 correctly moved the selected PV-only window to 13:00–15:30 and the
  canonical plan correctly exposed smart discharge before that window.
- The vendor mode nevertheless remained NOM. This isolated the remaining fault
  to execution rather than selection or plan construction.

## 2026-08-22 — 2.0.0-dev.134

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

## 2026-09-02 — 2.0.0-dev.226 household-safe stored-energy trading

- Kept ADR-001 through ADR-037 as the only authoritative design set. No
  terminal replacement-value policy or later ADR/V2ADR rule was introduced.
- Corrected the DEV.225 trading hourglass for energy already present in the
  battery. Its export budget is now bounded by the lower-PV baseline energy
  remaining after the complete projected household path, the technical lower
  SoC, the household unexpected reserve and the configured additional reserve.
- Kept linked grid-charge-and-export routes independently bounded by the user
  trading percentage because those routes acquire their own trading energy.
- Removed `stored_energy_export` from the PV-preference overlay. A high export
  price is an Opportunity, not evidence of available PV, and therefore no
  longer creates a NOM/PV interval before evening export.
- Added regressions for the household-safe stored-energy budget, unchanged
  linked trading budget, and absence of NOM when PV is unavailable.

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Local verification: all 29 market-planner tests and all 37 canonical MEP
  pipeline/version tests passed. Ruff passed on every changed Python file,
  mypy passed on the planner and all 59 canonical v2 source files, and
  `git diff --check` passed.

## 2026-09-02 — 2.0.0-dev.225 bounded market SoC path

- Restored MEP market charging and export only behind the explicit
  `market_daily_maximum_trading_soc_percent` User Rule, defaulting to 25%.
- Converted that percentage to one stored-energy budget before Candidate
  construction. PicoT further clamps the budget by the physical lower SoC,
  the household unexpected reserve and an additional 10 percentage-point
  reserve; full cross-scenario simulation remains the final safety authority.
- A broad low-price opportunity now contributes one cheapest, latest-safe
  charge window instead of every feasible start. A high-price opportunity
  contributes one peak-anchored export hourglass sized to the same energy
  budget. This removes the former Cartesian growth while preserving linked
  charge-and-export accounting.
- Market grid input is no longer rejected merely because the household reserve
  was already met: its purpose is financial acquisition, and it must instead
  pass the existing RTE, wear, margin, total-profit and physical-reserve tests.

- Verification: 64 focused planner/pipeline/version tests passed; the full
  suite passed 1128 tests, with its two environment-dependent checks then
  repeated successfully using an isolated socket run and the bundled Node.js
  runtime. Ruff passed on all changed files, mypy passed all 187 PicoT source
  modules and `git diff --check` passed.

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

## 2026-09-01 — 2.0.0-dev.222 household reserve and next-day PV path

- Live dev.221 showed an unnecessary late grid charge from roughly 82% to the
  effective maximum and only a generic household-support segment for the next
  day. The diagnostic download was also truncated before its ZIP central
  directory, so it contained no current dev.221 detail poll.
- Restored ADR-037's separation between desired PV capture and required stored
  household energy. Grid necessity now uses the configured lower SoC plus the
  configurable `household_unexpected_reserve_percent` User Rule (default 10%),
  capped by the effective maximum. Free battery capacity is no longer treated
  as required grid energy.
- Kept a separate conservative PV-capture Candidate. Every interval with PV on
  the confidence-selected lower/central basis is published as NOM, including
  next-day PV intervals, even when that PV cannot fill the battery completely.
- A grid or hybrid Candidate is invalid when the baseline already preserves the
  household requirement at its deadline. Grid completion remains available
  when the projected path actually falls below the requirement.
- Diagnostic ZIPs are now completely constructed before HTTP headers are sent
  and include an exact `Content-Length`; clients cannot receive an archive
  whose central directory is still being written.
- Regression coverage proves no grid fill from 60% or 82% when household and
  reserve are covered, a delayed next-day NOM/PV segment, retained necessary
  grid recovery for a late invalid incumbent, and a complete downloadable ZIP.
- Pre-release verification: all 1124 tests passed, including embedded
  JavaScript syntax validation; Ruff, mypy and `git diff --check` passed.

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

## 2026-09-01 — 2.0.0-dev.221 bounded physical MEP recovery

- Restored ADR-001 through ADR-037 as the authoritative planning boundary and
  kept MEP focused on complete physical energy paths. Optional battery market
  trading is disabled in the live runtime for this recovery release; it will
  return only behind an explicit bounded user rule in a later slice.
- Applied PV confidence before Candidate Generation. The planning basis now
  moves continuously from Solcast lower toward central as confidence rises;
  live actual-PV evidence can still replace that forecast basis for today.
- Bounded charge-path discovery before full simulation. MEP retains the
  physical NOM/PV path and at most one necessary grid or hybrid completion path
  selected inside published low-price windows. Without a price window, no
  speculative grid window is added unless a physical deadline requires one.
- Retained the 36-hour horizon and next-day planning. Existing three-scenario
  domain labels remain as validation compatibility, but no upper-specific
  Candidate family or market-route search is generated.
- Regression evidence covers confidence weighting, no-market live defaults,
  bounded Candidate counts, next-day coverage, required grid completion and
  price-window selection. The representative 36-hour fixture produces three
  Candidates in approximately 3.2 seconds instead of 52 Candidates in 5.8
  seconds before bounding.
- Pre-release verification: the complete pytest suite passed 1123 tests
  (including the JavaScript syntax check with the bundled Node runtime); Ruff,
  mypy and `git diff --check` passed. Live observer validation remains required
  before enabling any new execution behavior.

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Corrected the V2ADR-052 execution guard so NOM is protected only while the
  committed PV acquisition phase is actually active: `start <= now < end`.
- A future commitment remains durably persisted, but no longer blocks the due
  household baseline segment from dispatching smart discharge before its
  scheduled start.
- Preserved the existing protection against forecast-driven interruption once
  the PV phase has genuinely started.
- Added a runtime regression matching the live state: current vendor mode NOM,
  a persisted future PV commitment and a due smart-discharge baseline segment.

Exact next action: publish dev.134 and verify that PicoT applies smart discharge
before 13:00 while retaining the 13:00–15:30 PV-only commitment.

Live verification, 2026-08-22:

- Dev.134 restored smart discharge before the selected future PV window.
- Candidate inspection showed repeated window drift despite identical storage
  results. Every Candidate still reported `requirement_satisfied=false` because
  the deadline reserve remained the full 8.16 kWh rather than 10% / 816 Wh.

## 2026-08-22 — 2.0.0-dev.135

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Traced the false reserve result to the exact live ingestion seam: canonical
  mode capability construction received supported primitives but not the
  commissioned minimum SoC. Pipeline therefore correctly used its fail-closed
  full-target fallback.
- Added the explicit add-on option `storage_minimum_soc_percent`, default 10.0,
  and validates/converts it from percent to the canonical 0.0–1.0 fraction.
- Projects that minimum only when storage state and mode capability identifiers
  match, preserving fail-closed behavior for absent, invalid or mismatched
  configuration.
- The 8.16 kWh installation now exposes a canonical 816 Wh minimum reserve.
  A Candidate reaching 8.16 kWh at charge-window end and 8.10 kWh at deadline
  can therefore be requirement-satisfying and eligible for commitment
  stability instead of drifting between equivalent windows.
- Added ingestion, capability-projection and add-on-contract regressions.

Exact next action: publish dev.135 and confirm the chosen Candidate reports
`Reserve bij deadline gehaald=true`, `Doel gehaald=true` and remains committed.

Live verification, 2026-08-22:

- Dev.135 correctly exposed the 816 Wh reserve, reported both charge target and
  deadline reserve satisfied and retained the selected commitment.
- The newly eligible plan started at the current morning instant. This exposed
  a conflicting dev.131 low-confidence tie-break that explicitly preferred the
  earliest equal-price feasible window.

## 2026-08-22 — 2.0.0-dev.136

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Removed the low-confidence `earliest start` tie-break that conflicted with
  the agreed equal-price midday behavior.
- For equal average price and low PV timing confidence, Evaluation now compares
  Candidate midpoints with the temporal centre of the remaining positive-PV
  availability period. This is a robust day-shape centre and does not pretend
  that uncertain interval energy magnitudes are precise.
- For high PV timing confidence, the existing energy-weighted PV centre remains
  authoritative and may deliberately move the window earlier or later.
- Duration-weighted average price remains ahead of both timing rules; valid
  incumbent commitments remain ahead of price.
- Added a regression proving low-confidence equal-price selection prefers the
  PV availability centre rather than the earliest executable Candidate.

Exact next action: publish dev.136, reset the dev.135 morning commitment once,
and verify the replacement equal-price window is centred on the PV period.

## 2026-08-22 — 2.0.0-dev.137

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Serialized the explicit planning reset with canonical Planner Runs. The
  reset now clears state only after any older run is complete and exposes a
  monotonic reset generation, preventing that older run from restoring the
  commitment after reset acknowledgement.
- Preserved V2ADR-052 commitment stability outside the explicit reset path;
  price ranking and incumbent-selection priority are unchanged.
- Completed the bounded Home Assistant power-history bootstrap within one
  dashboard refresh by reading consecutive two-hour chunks. A failed chunk
  retains proven history and resumes from the missing tail on the next poll.
- Added concurrency and complete-bootstrap regressions.

Exact next action: publish dev.137, perform one planning reset and verify that
the replacement window is selected from current price/PV evidence and that the
current-day graphs are complete immediately after startup.

## 2026-08-22 — 2.0.0-dev.138

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

- Replaced the low-confidence equal-price PV-availability-centre tie-break
  introduced in dev.136. A long positive but uncertain evening PV tail could
  move its centre into the late afternoon and recreate the previously visible
  late-window selection failure.
- Equal average-price Candidates with low PV timing confidence now compare
  their midpoint with 12:00 in the explicit Dutch market timezone. Price and
  technical feasibility remain higher-priority selection criteria.
- Preserved the V2ADR-048 high-confidence behavior: sufficiently trustworthy
  interval timing continues to use the energy-weighted PV centre and may move
  an otherwise equal-price window earlier or later.
- Preserved the canonical whole-household Energy Path simulation. Expected
  battery use before a future charge window remains the forecast household
  deficit after direct PV consumption, without a hidden load multiplier.
- Added a regression reproducing an equal-price plateau with a positive PV
  tail through 21:00: low confidence selects 12:30–14:30 while high confidence
  may select the later energy-weighted window.

Exact next action: publish dev.138, reset the dev.137 commitment once and
verify that the fresh plan selects the equal-price window nearest local midday.


## 2026-08-23 — 2.0.0-dev.141

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Packages the independent daily observer runtime and the purple dashboard
  comparison beside the unchanged canonical planner.
- Restores only the dev.139 Home Assistant projection recovery boundary from
  PR #466: transient HTTP/URL/timeout/OS publish failures stop publication for
  the current cycle, emit `picot_v2_ha_projection_publish_error` and retry on
  the next planner poll.
- Does not restore the rolled-back grid/planner chain from PRs #448–#465.
- Keeps the daily simulation observer-only: no canonical selection,
  commitment or Zendure authority.

Exact next action: install dev.141, verify both dashboard plans are visible,
and run the accepted 48-hour observer trial including one deliberate manual
battery-discharge stress event.


## 2026-08-23 — 2.0.0-dev.142

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Completes the observer-only physical input contract after the first live
  dev.141 run blocked on `daily_reference_power_limit_missing`.
- Carries explicit 10–100% storage bounds and separate 2400 W charge and
  discharge limits in the exact Planning Input snapshot observed by the
  independent daily simulation.
- Keeps these limits outside the canonical storage capability consumed by
  Candidate Engine, Evaluation and Commitment, so the current strategy and
  live Zendure control remain unchanged.
- Adds compatible defaults for existing add-on installations and exposes a
  readable observer blocking reason on the purple dashboard card.

Exact next action: install dev.142, confirm the daily observer changes from
`blocked` to `completed`, then start the accepted 48-hour observer comparison
including one deliberate manual battery-discharge stress event.


## 2026-08-23 — 2.0.0-dev.143

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Corrects the independent daily observer horizon from the canonical 36 hours
  to one exact rolling 24-hour period while retaining the same Planning Input
  snapshot and lineage.
- Truncates household, PV and financial tariff inputs at the same daily
  boundary without estimating unknown prices or modifying source evidence.
- Treats missing next-day Nordpool coverage before its normal publication
  around 15:00 as an explicit wait state and shows a readable Dutch reason on
  the purple dashboard card.
- Leaves the canonical 36-hour planner, Candidate Engine, Evaluation,
  Commitment and Zendure control unchanged.

Exact next action: install dev.143 and confirm the observer reaches
`completed` when 24 hours of prices are available. Then start the accepted
48-hour comparison and perform one deliberate manual discharge stress event.


## 2026-08-23 — 2.0.0-dev.144

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Corrects observer-only financial settlement when a rolling physical
  simulation interval crosses a fixed Nordpool quarter-hour tariff boundary.
- Splits such an interval at every applicable tariff boundary and allocates
  energy and conversion losses proportionally while preserving the physical
  totals and storage trajectory.
- Keeps settlement fail-closed when tariff coverage contains a real gap or
  overlap and exposes that condition as a readable Dutch dashboard reason.
- Leaves the canonical 36-hour planner, Candidate Engine, Evaluation,
  Commitment and Zendure control unchanged.

Exact next action: install dev.144 and confirm the independent daily observer
reaches `completed`. Then start the accepted 48-hour observer comparison and
perform one deliberate manual battery-discharge stress event.


## 2026-08-23 — 2.0.0-dev.145

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Corrects the observer-only run contract after financial settlement began
  splitting physical intervals at fixed Nordpool quarter-hour boundaries.
- Allows multiple financial tariff segments inside one physical interval
  while requiring exact start and end coverage of the same daily horizon.
- Retains fail-closed contiguous coverage and now explicitly rejects financial
  segments without positive duration.
- Leaves the canonical 36-hour planner, Candidate Engine, Evaluation,
  Commitment and Zendure control unchanged.

Exact next action: install dev.145 and confirm the independent daily observer
reaches `completed`. Then begin the accepted 48-hour observer comparison and
perform one deliberate manual battery-discharge stress event.


## 2026-08-23 — 2.0.0-dev.146

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Makes physical admission precede financial ranking in the observer-only
  daily simulation.
- Excludes every grid-supported candidate when a complete, reserve-safe
  no-grid/PV path proves that the target remains reachable.
- Allows PV plus grid only when no no-grid path proves sufficient across the
  daily uncertainty scenarios.
- Retains PV storage opportunity cost as traceable evidence without deducting
  it twice from the physical financial result.
- Leaves the canonical 36-hour planner, Candidate Engine, Evaluation,
  Commitment and Zendure control unchanged.

Exact next action: install dev.146 and confirm one daily observer run reaches
`completed` with the PV-first exclusion reason visible where applicable. Then
begin the accepted 48-hour side-by-side comparison and perform one deliberate
manual battery-discharge stress event during that observation period.


## 2026-08-23 — 2.0.0-dev.147

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Replaces internal daily-observer identifiers with a Dutch advice and reason.
- Shows one merged local-time window instead of repeated UTC intervals.
- Explains the 24-hour worst-case financial result and minimum confidence.
- States explicitly when proven PV sufficiency excludes grid charging.
- Leaves simulation, canonical planning and live control unchanged.

Exact next action: install dev.147, confirm the explanation is readable, and
then continue the accepted 48-hour observer comparison.


## 2026-08-23 — 2.0.0-dev.148

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Keeps PV-only as the hard preference and permits grid supplementation only
  when no complete PV-only path proves the target reachable.
- Compares feasible charge windows using their duration-weighted average
  relevant tariff, without a fixed EUR 0.02 margin contract.
- Uses export value for NOM/PV opportunity cost and import price for proven
  grid supplementation.
- Aligns future observer charge windows to Nordpool market-quarter boundaries.
- Separates proposed-window confidence from minimum confidence over 24 hours.
- Marks the canonical planner window in blue and the daily observer window in
  purple in the price timeline.
- Leaves the daily simulation observer-only without selection, commitment or
  live Zendure control authority.

Exact next action: install dev.148 and begin the accepted 48-hour side-by-side
observation. During that period, perform one deliberate manual battery
discharge stress event and compare both planners' reactions.


## 2026-08-23 — 2.0.0-dev.149

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Replaces the small planner-window marks above the price bars with transparent
  vertical bands spanning the complete price plot.
- Shows the exact chosen start and end time for the canonical planner and the
  daily observer in separate blue and purple labels above the chart.
- Uses a solid blue boundary for the canonical window and a dashed purple
  boundary for the daily observer so overlapping windows remain distinguishable.
- Leaves price data, candidate evaluation, daily simulation and live execution
  unchanged.

Exact next action: install dev.149, confirm both selected windows and their
quarter-hour boundaries are readable, and then start the accepted 48-hour
side-by-side observation with one deliberate manual-discharge stress event.


## 2026-08-23 — 2.0.0-dev.150

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Removes the full-height planner-window overlays from the price bars.
- Places the canonical and daily-observer windows as two horizontal bars in
  the grey strip below the price bars, aligned to their actual start and end.
- Keeps the exact blue and purple time labels above the price chart.
- Leaves price data, planner decisions, simulation and live execution unchanged.

Exact next action: install dev.150, confirm the two bars align with their
displayed quarter-hour windows, and then begin the accepted 48-hour comparison
with one deliberate manual-discharge stress event.


## 2026-08-24 — 2.0.0-dev.151

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Releases the persistent observer-only comparison between the canonical
  planner and the independent daily simulation.
- Freezes both decisions per shared Planning Input and replays them after the
  horizon against the same measured PV, household, grid and battery evidence.
- Uses the same physical limits, configured conversion efficiencies and
  versioned import/export tariff contract for both replays.
- Persists open and closed comparison dossiers across restarts and exposes the
  latest 48 hours on the dashboard and in the diagnostic export.
- Adds an explicit manual-discharge stress marker and proves that the next
  comparison starts from the newest measured battery state.
- Remains fully observer-only and cannot influence candidates, Evaluation,
  commitments, execution or Zendure control.

Exact next action: install dev.151, begin the accepted 48-hour side-by-side
observation, and perform one deliberate manual discharge above the configured
minimum reserve using the dashboard stress marker.


## 2026-08-24 — 2.0.0-dev.152

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Fixes the dashboard-wide JavaScript syntax failure introduced in dev.151 by
  preserving the intended newline escape in the generated HTML.
- Adds a regression test that parses the complete embedded dashboard script
  with Node.js, so a syntax error cannot pass the release suite again.
- Leaves both planners, their persisted comparison evidence, commitments,
  execution and Zendure control unchanged.

Exact next action: install dev.152, confirm the dashboard loads, and then begin
the accepted 48-hour side-by-side observation with one deliberate manual
discharge above the configured minimum reserve using the dashboard stress
marker.


## 2026-08-24 — 2.0.0-dev.153

Status: `CI_PENDING`; not yet `LIVE_VERIFIED`.

- Corrects the daily observer's tariff horizon to the contiguous Nordpool
  prices actually published from the snapshot time, capped at 24 hours.
- Uses that exact same bounded horizon for household demand, PV scenarios,
  physical intent simulation and financial settlement.
- Prevents the normal pre-15:00 absence of next-day prices from blocking all
  daily planning; the horizon expands automatically when those prices arrive.
- Shows the exact simulation start, end and available price-coverage duration
  on the observer dashboard.
- Keeps the canonical planner, preferences, commitments, execution and Zendure
  control unchanged.

Exact next action: install dev.153, confirm the observer completes before
15:00 with a horizon ending at the published tariff boundary, and begin the
accepted 48-hour side-by-side observation.


## 2026-08-24 — consolidated recovery log and start of 48-hour observation

Status: `LIVE_VERIFIED`; 48-hour observer-only comparison started after the
live dev.153 confirmation in this session.

### PURPOSE AND RECOVERY DECISION

The independent daily simulation is now running beside the canonical pipeline
to determine, from real operation, whether it produces demonstrably better
plans. It is not a patch inside Candidate Engine, Evaluation, Commitment or
Execution and it has no control authority. This preserves an honest comparison
and prevents another cycle in which observer code changes the pipeline it is
supposed to assess.

The recovery conclusion remains:

- retain the current canonical pipeline unchanged as the live authority;
- retain reusable physical, tariff, financial and dashboard contracts outside
  the canonical decision path;
- do not restore the earlier broad coupling that was rolled back after roughly
  7,500 lines had affected the pipeline;
- assess replacement only from persisted, same-input, same-reality evidence;
- require a separate explicit decision after the observation period before any
  daily-simulation result may influence selection, commitment or execution.

### IMPLEMENTED TODAY

- Completed the independent physical daily path over current storage state,
  household demand, lower/central/upper PV, physical storage limits,
  conversion efficiencies, reserve and target state.
- Included explicit import/export financial settlement from the start so the
  simulator does not need to be reopened later for grid acquisition.
- Applied the agreed strategy contract to the observer:
  - PV charging is preferred;
  - grid supplementation is permitted only for a proven residual shortage;
  - PV-recoverable plans exclude unnecessary grid charging;
  - no dynamic trading preference or fixed EUR 0.02 selection contract is
    used;
  - charge windows are financially compared using their relevant
    duration-weighted average tariff.
- Retained the versioned 2026/2027 Dutch tariff treatment, including the
  changed export tax treatment from 2027.
- Restored the recoverable Home Assistant 502 behaviour without changing
  planner decisions.
- Added the purple observer result beside the blue canonical result and marked
  both selected windows in the price chart.
- Added plain-language observer advice, proposed window, average window price,
  window confidence and worst-case financial result.
- Added persistent comparison dossiers for the latest 48 hours. Both decisions
  are frozen from the same Planning Input and later replayed against the same
  measured PV, household, grid and battery evidence.
- Added an explicit manual-discharge stress marker. The next comparison starts
  from the latest measured battery state; the marker has no control authority.
- Preserved comparison evidence across restarts and added it to diagnostics.

### RELEASE CORRECTIONS AND LESSONS

- dev.151 introduced the persistent comparison ledger but its dashboard did
  not load because a newline was emitted inside an embedded JavaScript string.
- dev.152 corrected the escape and added a Node.js syntax test for the complete
  embedded dashboard script. The PicoT runtime itself had remained healthy.
- dev.153 corrected a deeper tariff-horizon contract error. Requiring exactly
  24 future hours of Nordpool prices would block the observer every day between
  midnight and publication of next-day prices around 15:00.
- The final rule is now: use the contiguous published tariff horizon from the
  snapshot, capped at 24 hours, and use that exact same boundary for household,
  PV, physical simulation and financial settlement. The horizon expands
  automatically when new prices arrive.
- The dashboard shows the exact horizon start, horizon end and available price
  coverage. Missing prices only block when no contiguous coverage exists from
  the current snapshot.

### VERIFIED END STATE

- PR #511 merged as merge commit
  `cbf396188c1dd0a3b54e7c67ca472effa38236ed`.
- Installed version: `2.0.0-dev.153`.
- Alex confirmed live that the dashboard and daily observer work again.
- Local release verification before merge: 1,019 tests passed.
- PicoT Core CI, PicoT v2 Rebuild and Tests workflows passed.
- Ruff and mypy passed on every changed file.
- The daily observer remains observer-only and cannot change the canonical
  winner, commitments, live execution or Zendure mode.

### 48-HOUR OBSERVATION PROTOCOL

For the full observation period:

1. Do not tune either planner merely because one intermediate decision looks
   surprising; first preserve the complete evidence.
2. Compare canonical and daily decisions only when they share the exact same
   Planning Input snapshot.
3. Verify selected window, required energy, PV contribution, any proven grid
   shortage, average window price, confidence, reserve and target outcome.
4. Let closed dossiers replay both decisions against the same measured energy
   flows and tariff contract; incomplete measurement coverage produces no
   winner.
5. Perform one deliberate manual battery discharge above the configured 10%
   minimum reserve. Create the dashboard stress marker immediately before the
   discharge and record a concise note.
6. Check whether both planners replan from the newly measured battery state,
   whether PV remains preferred and whether grid supplementation appears only
   after a proven shortage.
7. Export diagnostics after the period before making a replacement decision.

### ACCEPTANCE DECISION AFTER 48 HOURS

The daily simulation may be considered as a replacement strategy only if the
stored evidence shows that it is physically correct, consistently at least as
good financially, more explainable, responsive to the manual-discharge stress
event and free of unnecessary grid charging. A favourable dashboard suggestion
alone is not sufficient. Until that assessment is explicitly accepted, the
canonical pipeline remains the sole live authority.

Exact next action: allow dev.153 to run unchanged for 48 hours, perform the one
marked manual-discharge stress test, then export diagnostics and evaluate every
closed comparison dossier before deciding whether the daily strategy should
replace the canonical strategy.


## 2026-08-28 — 2.0.0-dev.193 MEP sole canonical planner

Status: `CI_VERIFIED`; not yet `LIVE_VERIFIED`.

Branch: `feature/mep-sole-canonical-planner`.

Last verified repository commit before this working tree:
`b4a5bb6` (`2.0.0-dev.192`).

### Decisions

- Accepted V2ADR-055. MEP is the sole planner and enters the one canonical
  nine-stage pipeline. CP, the separate EP observer runtime, private MEP
  execution and the live-PV canary control route are removed from production.
- The validated EP physical schedule/simulation logic is retained only as
  internal MEP candidate-generation logic. It has no worker, persistence,
  dashboard, commitment or dispatch authority of its own.
- Evaluation exclusively owns native/market winner selection and the
  incumbent-versus-challenger decision. The Plan Store exclusively owns
  durable continuity and revision evidence.
- Market routes may be generated only from canonical `OpportunitySet`
  evidence and must retain the originating opportunity identifiers.
- Vendor mode translation occurs only in the canonical Home Assistant adapter.
- One `execution_mode` option controls observer versus live authority.

### Implemented

- Replaced the production CP pipeline with required MEP composition and moved
  the former CP pipeline to `tests/legacy_cp_pipeline.py` as a frozen regression
  fixture.
- Removed the EP runtime/worker/dashboard, planner-comparison ledger, private
  MEP runtime execution/dashboard, live-PV canary runtime and their obsolete
  side-channel tests.
- Split MEP generation from Evaluation. MEP runtime returns an unselected
  portfolio; the canonical Evaluation engine selects exactly one winner.
- Routed the shared `storage_target_required_by` deadline into MEP charge-window
  discovery. A later cheap window cannot be used when it misses that deadline.
- Added incumbent-first Evaluation with an explicit configurable
  `plan_switching_margin_eur` default of EUR 0.05.
- Extended durable commitments with the complete remaining canonical segment
  sequence, selection reason and replaced plan identity. Ordinary recalculation
  retains the existing plan and revision; accepted necessity or material total
  objective improvement creates an explicit revision.
- Moved Zendure mode mapping from planning into the adapter boundary. Core
  execution plans now carry canonical primitives and source policy only.
- Removed CP/EP/private-MEP comparison views and overlays. The dashboard now
  presents only the canonical MEP plan, including calculation timestamp and SoC
  at calculation.
- Bumped the add-on and Core version to `2.0.0-dev.193`.

### Local verification

- Full test suite: `1056 passed`.
- Ruff: all changed production and acceptance-test files passed.
- mypy: `Success: no issues found in 183 source files`.
- New acceptance coverage proves one runtime planner, one execution authority,
  no production CP fallback, OpportunitySet lineage, adapter-only vendor
  mapping, deadline-aware replacement, material switching margin, full plan
  persistence and canonical-only dashboard presentation.

### GitHub CI verification

- PR #561: `release: PicoT 2.0.0-dev.193 MEP sole planner`.
- Remote head after the CI import-order correction:
  `479704499901f14cf7cb132c3d79cdf3b5b1dc82`.
- Tests run 1921: passed.
- PicoT Core CI run 1866: passed.
- PicoT v2 Rebuild run 795: passed.

### Not verified / known issues

- dev.193 has not been installed or observed live; execution, restart recovery,
  target completion and real Home Assistant/Zendure feedback remain to be
  verified before `LIVE_VERIFIED`.
- The dev.193 implementation is published on
  `feature/mep-sole-canonical-planner` in PR #561.

### DO NOT CHANGE / critical context

- ADR-001 through ADR-037 plus accepted V2 ADRs, including V2ADR-055, remain the
  authority. Legacy ADR-038 and higher are excluded unless deliberately accepted
  into V2.
- Do not restore CP, a separate EP worker/dashboard, planner comparison, private
  MEP commitment/dispatch or a canary control route.
- Do not let Opportunity, Execution, Device Adapter, dashboard or vendor
  feedback select or replace a plan.
- Do not tune confidence to compensate for planning behaviour; MEP consumes the
  designed confidence evidence unchanged.

Exact current position: dev.193 is implemented and CI-verified in PR #561 on
`feature/mep-sole-canonical-planner`, with one MEP planner connected to the
canonical pipeline and no parallel production control route.

Exact first next action: merge PR #561 and install dev.193 for controlled live
verification of plan continuity and deadline-aware overnight charging.


## 2026-08-28 — 2.0.0-dev.194 remove residual CP deadline authority

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Live incident

- The first dev.193 live run at 2026-08-28 18:11:20 Europe/Amsterdam produced
  zero MEP candidates with
  `daily_reference_charge_windows_unavailable`.
- The storage state was 41% and the residual CP requirement demanded 100% by
  19:00. At the physical 2400 W charge limit this target was already
  unreachable, even before conversion loss.
- MEP correctly rejected the impossible hard deadline, but that deadline was
  not MEP input: `live_runtime.py` still invoked the removed CP
  `CandidateEngine().derive_storage_requirements()` and dev.193 forwarded its
  result into MEP.

### Decision and implementation

- Confirmed the deadline was a historical CP measure that prevented CP from
  moving a same-day charge window to tomorrow. It is not an MEP planning rule.
- Removed CP Candidate Engine and remaining-PV feasibility invocation from the
  live runtime.
- Removed consumption of `household_planning_regime.storage_target_required_by`
  from the canonical MEP composition.
- MEP now derives its own physically feasible daily schedule. Evaluation and
  the canonical Plan Store remain the sole owners of incumbent continuity and
  replacement.
- Added an architecture regression that forbids `CandidateEngine` and
  `derive_storage_requirements` throughout the live runtime.
- Added an incident regression proving a legacy 100%-within-49-minutes CP
  deadline cannot block MEP candidate generation.
- Bumped add-on and Core version to `2.0.0-dev.194`.

### Local verification

- Incident and affected integration suite: `61 passed`.
- Full repository suite: `1056 passed`.
- Ruff production package: `All checks passed!`.
- mypy: `Success: no issues found in 183 source files`.
- `git diff --check`: passed.

## 2026-08-28 — 2.0.0-dev.199 align grid-supported charging with PV

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Live finding

- Inside the broad 08:45 through 16:45 low-price Opportunity, MEP selected the
  final admissible 15:15 through 16:30 charge block even though the forecast PV
  peak was around 12:00.
- The exact financial comparison and remaining later-start tie-break allowed a
  negligible sub-cent route difference to displace the PV-aligned timing.

### Decision and implementation

- Extended V2ADR-056 with an explicit EUR 0.01 complete-route financial
  equivalence tolerance. A financially better route outside that tolerance
  remains decisive.
- Simulation evidence now records PV and grid input inside only the explicit
  grid-supported charge phase for every scenario.
- Evaluation uses the already selected canonical MEP planning-basis lane for
  timing. For tomorrow that lane contains `(Solcast lower + central) / 2` from
  the daily PV-basis stage; Evaluation does not average it again.
- Within the financially equivalent cohort, Evaluation maximises useful PV in
  the explicit charge phase, then minimises grid supplement in that phase. The
  former later-start preference has been removed.
- Advanced the market-planner evidence method to v3 and commitment contract to
  v4. Future v3 commitments are replanned; already active v2 or v3 phases remain
  fixed until their accepted end.
- Bumped add-on and Core version to `2.0.0-dev.199`.

### Verification

- Regression first failed on dev.198 because a EUR 0.005 advantage selected the
  last subwindow; it now selects the financially equivalent PV-aligned route.
- The same regression proves a EUR 0.011 advantage remains financially
  decisive.
- Affected planner, PV-basis, canonical-pipeline, commitment and version suite:
  `55 passed`.
- Full repository suite: `1065 passed`.
- Ruff on all changed production and test files: `All checks passed!`.
- mypy: `Success: no issues found in 183 source files`.
- `git diff --check`: passed.

### GitHub CI verification

- PR #562: `fix: PicoT 2.0.0-dev.194 remove CP deadline authority`.
- Tests run 1925: passed.
- PicoT Core CI run 1870: passed.
- PicoT v2 Rebuild run 797: passed.


## 2026-08-28 — 2.0.0-dev.195 present canonical MEP plan

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Live incident

- Diagnostics 54 proved that dev.194 generated and retained a five-segment MEP
  plan for 29 August, while the dashboard did not present it as tomorrow's
  battery plan.
- The MEP run intentionally has no legacy delegated-storage Candidate Outcomes.
  The dashboard still depended on those removed CP/EP projection fields for its
  battery-plan summary and price-window overlay.
- A manual override remains active. This release does not reset or bypass it;
  @gielz retains control while the user is unavailable.

### Decision and implementation

- Project the selected plan directly from the canonical `ExecutionPlanSet`, as
  required by ADR-016, ADR-033 and V2ADR-055.
- Present every exact segment with local day, start, end, canonical action,
  requested power, source policy and purpose.
- Mark canonical MEP charge and export segments in the today/tomorrow price
  chart instead of deriving one legacy charge window from Candidate Outcomes.
- Show an explicit notice when manual authority blocks dispatch; presentation
  never changes authority or execution state.
- Removed the dashboard's dependency on CP-era `storage_source_needs` for the
  battery-plan card.
- Bumped add-on and Core version to `2.0.0-dev.195`.

### Verification

- Regression proves an MEP plan is projected when the legacy Outcome Set is
  empty and preserves the exact Execution Plan segments.
- Affected MEP, dashboard and version suite: `53 passed`.
- Full repository suite: `1057 passed`.
- Ruff on all changed production and test files: `All checks passed!`.
- mypy: `Success: no issues found in 183 source files`.
- Embedded dashboard JavaScript syntax check and `git diff --check` pass.


## 2026-08-28 — 2.0.0-dev.196 colour MEP price bars by action

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Decision and implementation

- Keep the established dashboard energy palette as the single colour
  vocabulary.
- Colour complete price bars green (`#35a862`) while MEP charges the battery.
- Colour complete price bars grey (`#aab2bd`) while MEP trades by exporting
  stored energy to the grid.
- Use the same action colours for the legend, plan chips and lower window
  markers. Unselected price bars remain blue.
- This is presentation only. Planning, commitment, execution and manual
  authority are unchanged.
- Bumped add-on and Core version to `2.0.0-dev.196`.

### Verification

- Affected MEP, dashboard, override and version suite: `72 passed`.
- Full repository suite: `1058 passed`.
- Ruff on changed production and test files: `All checks passed!`.
- Embedded dashboard JavaScript syntax check and `git diff --check` pass.


## 2026-08-28 — 2.0.0-dev.197 present MEP commitment facts

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Live finding

- The exact MEP execution segments and coloured price bars were visible in
  dev.196, but the upper chosen-plan facts still depended on the removed CP
  Candidate Outcome contract.
- Missing confidence was rendered as `0%` because JavaScript converted `null`
  to zero, even though no confidence value had been supplied.

### Decision and implementation

- Keep MEP, evaluation, the Plan Store and execution unchanged.
- Project chosen-plan identity, validity, charge window and current storage
  energy directly from the canonical Execution Plan and Planning Input.
- Project target, source policy and scenario and financial facts only from the
  matching active MEP commitment when that commitment is present in the run.
- Hide unavailable legacy outcome facts instead of displaying rows of dashes.
- Render absent confidence, price and currency facts as unavailable, never as
  numeric zero.
- Bumped add-on and Core version to `2.0.0-dev.197`.

### Verification

- Regression coverage proves a fresh MEP plan is presented without legacy
  outcomes and a retained commitment exposes its exact stored facts.
- Dashboard formatter coverage proves absent confidence is not shown as `0%`.


## 2026-08-28 — 2.0.0-dev.198 preserve PV room in broad charge windows

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

### Live finding

- MEP retained a broad low-price Opportunity from 08:45 through 16:30 as one
  explicit 2400 W grid-supported charge phase.
- The linked energy requirement needed only part of that duration. Starting at
  08:45 could therefore fill storage before the expected midday PV peak and
  unnecessarily displace PV generation to grid export.

### Decision and implementation

- Accepted V2ADR-056. Opportunity Detection continues to preserve the complete
  relative-price window and does not select device timing or power.
- MEP Candidate construction now enumerates interval-minimal contiguous charge
  subwindows inside that immutable Opportunity, with explicit source lineage
  and one canonical trailing safety interval when spare duration permits.
- Each complete market Candidate uses `BALANCE_BIDIRECTIONAL` around only the
  exact `CHARGE_AT_POWER` phase. Its source policy remains
  `PV_PREFERRED_GRID_ALLOWED` at 2400 W.
- Evaluation remains the sole selector. It compares financial outcome first,
  then lower worst-scenario grid-to-storage input, then the later recoverable
  subwindow and finally the stable schedule identity.
- Negative all-in import windows and the frozen native daily physical planner
  remain unchanged.
- Advanced the commitment contract to v3. A future v2 commitment is cleared at
  restart for fresh MEP planning; an already active v2 phase remains fixed until
  its normal end or an accepted hard abort.
- Bumped add-on and Core version to `2.0.0-dev.198`.

### Verification

- Regression proves a broad cheap Opportunity produces multiple exact,
  physically minimal alternatives and preserves NOM/PV acquisition around the
  selected 2400 W subwindow.
- Canonical pipeline coverage proves the Winning Energy Path reaches execution
  unchanged with `PV_PREFERRED_GRID_ALLOWED` source policy.
- Restart coverage proves future old-semantics commitments are replanned while
  active phases remain continuous.
- Affected planning, canonical pipeline and commitment suite: `49 passed`.
- Full repository suite: `1063 passed`.
- Ruff on all changed production and test files: `All checks passed!`.
- mypy: `Success: no issues found in 183 source files`.
- `git diff --check`: passed.
## 2026-08-30 — 2.0.0-dev.200 live MEP dispatch and visibility

- Removed the ambiguous Zendure translation for canonical charge/discharge
  power primitives by selecting the integration-configured fast modes.
- Added measured-PV/SoC admission at the primitive boundary: NOM is retained
  only when central-promoted measured-PV evidence proves the target; lagging PV
  continues to permit the planned grid acquisition.
- Expanded the price chart to all MEP primitives and added a plan-coloured
  projected SoC overlay anchored at the current measured SoC.
- Bumped add-on and Core version to `2.0.0-dev.200`.
## 2026-08-30 — 2.0.0-dev.201 roomier price and SoC chart

- Increased the price/SoC chart canvas and margins so the 100% SoC line,
  right-hand SoC axis, time labels and plan lane have their own visual space.
- Put sequential plan-window markers on one dedicated lane instead of stacking
  them into the plot and time labels.
- Reused PicoT's household-load blue (`#3994e6`) for smart household discharge
  across legend, chips, price-bar outlines, plan markers and projected SoC.
- Kept all MEP planning and execution behavior unchanged.
- Bumped add-on and Core version to `2.0.0-dev.201`.
## 2026-08-30 — 2.0.0-dev.202 adaptive market feedback and peak export

- Added V2ADR-058 for explicit measured-progress execution feedback, complete
  market-commitment lifetime and acquisition-free stored-energy export.
- Preserved future export segments when NOM/PV makes explicit grid charging
  unnecessary or the acquisition target is reached.
- Added peak-anchored contiguous export candidates and made marginal export
  return decisive inside the complete-route EUR 0.01 cohort.
- Reclassified measured-PV charge admission as `execution_deferred`; genuine
  authority, provenance, calibration and capability blockers remain
  `dry_run_blocked`.
- Bumped add-on and Core version to `2.0.0-dev.202`.
## 2026-08-30 — 2.0.0-dev.203 preserve post-export recovery

- Restricted `acquisition_target_reached` to charge phases that precede a
  still-future export and can therefore contribute to that export.
- Preserved grid/PV recovery phases that follow export; the safe post-export
  target can no longer be mistaken for a completed pre-export acquisition.
- Coalesced contiguous equal commitment segments after every revision so a
  replaced charge phase produces one continuous NOM window.
- Advanced the commitment contract to v5 and reject dev.202 v4 commitments on
  restart, forcing MEP to reconstruct any already-corrupted live route.
- Bumped add-on and Core version to `2.0.0-dev.203`.
## 2026-08-30 — 2.0.0-dev.204 financially bounded late grid fallback

- Added V2ADR-059 and kept complete-route financial outcome as the primary MEP
  charge-timing objective.
- Replaced explicit-charge PV overlap with total route-wide grid energy inside
  the existing EUR 0.01 financial-equivalence cohort.
- Added the latest safe charge start only as the final timing tie-break after
  equal route-wide grid demand.
- Preserved peak-anchored export construction and materially cheaper earlier
  charge routes.
- Advanced the commitment contract to v6: future and balance-only dev.203 plans
  replan, while an active explicit-power phase remains uninterrupted.
- Bumped add-on and Core version to `2.0.0-dev.204`.
## 2026-08-30 — 2.0.0-dev.205 fast-mode dispatch containment

- Added V2ADR-060 for the canonical fast-power to fixed Zendure-mode adapter
  contract and external dispatch failure containment.
- Made `CHARGE_AT_POWER` and `DISCHARGE_AT_POWER` executable through their
  admitted `input_select.select_option` mappings while retaining legacy numeric
  charge mappings.
- Contained adapter and transport exceptions as visible `translation_failed`
  and `dispatch_failed` outcomes with their diagnostic reason; the live process
  no longer terminates and a later cycle can retry.
- Added real-adapter regressions for `Snel opladen` and `Snel ontladen` plus a
  canonical runtime fail-closed regression.
- Kept all MEP planning, commitment and financial selection behavior unchanged.
- Bumped add-on and Core version to `2.0.0-dev.205`.
## 2026-08-30 — 2.0.0-dev.206 committed segment clock execution

- Added V2ADR-061 after live dev.205 proved that a healthy measurement loop
  could skip the end of an explicit export segment.
- Added the currently due commitment segment to the stable execution input
  signature, making every segment boundary start one canonical cycle on the
  next normal poll without selecting or replacing the MEP plan.
- Kept ordinary telemetry suppressed during an active commitment so SoC and
  power noise still cannot cause full-plan churn.
- Kept the previous signature after rejected or failed dispatch, allowing the
  required segment transition to retry on the next poll.
- Added regressions for the exact export-to-smart-discharge boundary and retry
  behavior discovered in diagnostics 66.
- Bumped add-on and Core version to `2.0.0-dev.206`.

## 2026-08-31 — ADR-032 incumbent/challenger comparison slice

- Added V2ADR-062 and V2ADR-063 for material replanning, symmetric commitment
  comparison and explicit committed-trajectory materiality thresholds.
- Routed live material observations through the general Runtime Monitor and
  retained household-load and storage-corridor baselines in commitment v8.
- Added one canonical MEP Candidate/Outcome producer. It emits every native and
  market alternative plus a freshly simulated incumbent over the same snapshot
  and horizon before any winner exists.
- Replaced the live pipeline's private MEP and historical commitment decisions
  with ADR-032 `EvaluationEngine` comparison. Equivalent outcomes retain the
  incumbent; invalid incumbents are excluded; historical financial fields are
  provenance only.
- Exposed per-candidate horizon, validity, financial, self-consumption, reserve,
  recoverability and switching-margin evidence in diagnostics.
- Preserved exact storage-export targets in persisted commitment segments and
  reject older commitments that lack sufficient comparison provenance.
- Added machine-readable ADR ownership boundaries and a mandatory session-start
  routing document.
- Verification: `1107 passed`; Ruff all changed production/test files; mypy
  `Success: no issues found in 186 source files`; `git diff --check` passed.

## 2026-08-31 — ADR-033 canonical Execution Plan Builder slice

- Removed live and dead hand-built `ObserverExecutionPlan` construction from
  `mep_canonical_pipeline.py`.
- Routed the successful canonical `EvaluationResult` exclusively through
  `ExecutionPlanBuilder` before commitment persistence and execution.
- Extended canonical `ExecutionPlanSegment` with exact `ChargeSourcePolicy`
  preservation under ADR-037 and V2ADR-050; primitives, time bounds, power,
  evidence, purpose and capability references remain unchanged.
- Added a policy-free compatibility projection from the canonical domain
  `ExecutionPlanSet` to the existing live v2 DTO. A retained incumbent keeps
  the Store-admitted commitment plan ID; no candidate or commitment evaluation
  occurs in that projection.
- Reused the canonical Evaluation ID and deterministic Builder plan/set IDs so
  lineage no longer depends on a pipeline-local synthetic plan identity.
- Added architecture regressions prohibiting live manual plan construction and
  verifying exclusive ADR-033 Builder use.
- Verification: `1108 passed`; focused Builder/MEP/commitment/runtime chain
  `93 passed`; Ruff passed; mypy `Success: no issues found in 187 source files`;
  `git diff --check` passed.

## 2026-08-31 — 2.0.0-dev.207 ADR boundary recovery release

- PR #575 merged the complete ADR-032/033 recovery on `main` as commit
  `6e99c82f477fdb31ea613ab23652f9ea7ec99a08`.
- GitHub PicoT Core CI, PicoT v2 Rebuild and Tests all passed for the merged
  recovery.
- Bumped the Home Assistant add-on and canonical v2 runtime together to
  `2.0.0-dev.207`; no planning, evaluation, commitment, runtime or adapter
  behavior changes are part of this release-only slice.
- Live verification must confirm clean startup, a fresh v8 commitment with
  comparable incumbent/challenger evidence, retained identity for equivalent
  plans and correct execution at the next committed segment boundary.

## 2026-08-31 — 2.0.0-dev.208 canonical add-on packaging hotfix

- Live dev.207 stopped before runtime startup with
  `ModuleNotFoundError: No module named 'picot.architecture_ownership'`.
- Root cause: the add-on Dockerfile copied only `domain`, `adapters`, `planner`
  and `v2`; the merged canonical runtime additionally imports the top-level
  `architecture_ownership.py` module and `runtime` package.
- Added both missing canonical components to the image while preserving the
  explicit exclusion of legacy `picot.addon`.
- Added a recursive import-closure regression so every local top-level
  `picot.*` dependency reachable from `picot.v2` must be represented in the
  Docker packaging allowlist.
- Bumped the Home Assistant add-on and canonical v2 runtime together to
  `2.0.0-dev.208`; no planning, evaluation, commitment, runtime policy or
  adapter behavior changed.

## 2026-08-31 — 2.0.0-dev.209 canonical entrypoint ownership identity

- Dev.208 proved the canonical modules were packaged, then stopped during
  `python -m picot.v2.live_runtime` because Python sets `__name__` to
  `__main__` for the executed module.
- The architecture registry correctly rejected `__main__` because the
  `live_runtime_composition` owner is `picot.v2.live_runtime`.
- Kept the registry strict and changed only the executable live-runtime
  declaration to its fixed canonical module identity.
- Expanded architecture regressions to permit explicit canonical declarations
  and require the live entrypoint to use one; ordinary modules continue using
  `__name__`.
- Bumped the Home Assistant add-on and canonical v2 runtime together to
  `2.0.0-dev.209`; no planning, evaluation, commitment, execution or adapter
  behavior changed.

## 2026-08-31 — 2.0.0-dev.210 household requirement and lifecycle repair

- Kept ADR-001 through ADR-037 authoritative; no new ADR was required and no
  CP planner or CP-derived planning path was introduced.
- Made MEP derive the ADR-037 storage-energy deadline from the first projected
  household grid dependency, bounded by the earliest physically reachable
  target time. Candidate construction is rerun against that deadline; MEP
  still generates complete paths and canonical Evaluation remains the only
  winner selector.
- Preserved the full Execution Plan lifecycle in commitment persistence: the
  commitment start, primitive and source policy now describe its first
  segment, while target-energy semantics continue to follow the future
  actionable segment.
- Made live execution prefer a currently due persisted segment over a legacy
  top-level future start, repairing dev.209 commitments without inventing or
  re-evaluating a plan in runtime.
- Added regressions for a low-SoC, no-PV horizon with a cheaper later price,
  canonical commitment lifecycle identity, and legacy segment-first execution
  phase classification.
- Pre-release verification: `1112 passed`; Ruff passed on all affected files;
  mypy passed on all affected source; `git diff --check` passed.
- Live validation must release any active manual override, then confirm a new
  plan charges early enough to avoid projected household grid dependency and
  dispatches the currently due segment.

## 2026-08-31 — 2.0.0-dev.211 canonical storage requirement comparison

- Kept ADR-001 through ADR-037 authoritative and retained V2ADR-055 MEP as the
  sole candidate generator; no CP planner or private pipeline selection was
  introduced.
- Published MEP's projected lower-scenario household energy balance and one
  canonical ADR-037 `StorageEnergyRequirement` with the dev.210 physical
  deadline. Every complete candidate path now carries the requirement ID as a
  constraint.
- Made Candidate Outcome production invalidate native, market and incumbent
  paths that cannot reach the required storage energy by the deadline across
  every PV scenario. Canonical ADR-032 Evaluation still performs all winner and
  incumbent/challenger selection; it receives only explicit validity evidence.
- Applied the configured storage-export wear cost symmetrically to native and
  freshly simulated committed outcomes, matching the existing market-route
  calculation. An identical incumbent and challenger therefore receive equal
  current financial outcomes.
- Added regressions proving that a low-SoC, no-PV incumbent charging only after
  the household deadline is replaced by an immediate feasible plan, and that
  identical export schedules compare with equal wear-adjusted finance.
- Extended machine-readable ownership for the Candidate Outcome layer with
  ADR-037 and `storage_requirement_projection`.
- Recovery-environment verification: 19 canonical pipeline scenarios and 59
  related architecture, MEP, market-route and reference-simulation scenarios
  passed through direct execution; Python compilation and `git diff --check`
  passed. The restored workspace lacked pytest, Ruff and mypy, so GitHub CI is
  required before merge.
- Live validation must release any active manual override and confirm that
  diagnostics publish the storage requirement, late commitment is invalid and
  the selected plan reaches the target before its deadline. The flat dashboard
  projection remains a separately scoped UI defect.

## 2026-08-31 — 2.0.0-dev.212 daily target and household reserve separation

- Live dev.211 diagnostics disproved the label attached to its 100% record.
  The value is the conservative daily maximum target with `reached_by`
  semantics; it is not proof that 100% must still be present at the later
  household dependency time after an intentional export segment.
- Kept ADR-001 through ADR-037 authoritative. MEP remains the only Candidate
  generator, complete paths remain mandatory and ADR-032 Evaluation remains
  the only winner selector.
- Added explicit `requirement_kind` and `satisfaction_mode` fields. The live
  MEP target is now published as `daily_storage_target` / `reached_by` and no
  longer labelled as household demand.
- Added per-Candidate Outcome facts for the target deadline, conservative
  cross-scenario target-completion result and completion time, plus the
  separately simulated cross-scenario household-reserve result.
- Preserved the hard daily preference for the effective maximum SoC. A 60%
  state therefore still produces only valid winning alternatives that reach
  the 100% target. Preserved the configured two-percent micro-charge
  suppression and its active-session exception unchanged.
- Did not invent confidence-dependent reserve enlargement. The existing
  ADR-037 relative-confidence policy requires a canonical baseline that is not
  present in the live MEP Planning Input; wiring a fallback or fixed threshold
  here would create hidden planning policy.
- Regression evidence covers a 60% starting SoC, valid linked market routes,
  explicit household reserve, late-incumbent invalidation and the existing
  micro-charge boundary. Direct execution passed all 20 canonical MEP pipeline
  scenarios plus 37 market, ADR-037 contract and charge-window scenarios.
  Python compilation and `git diff --check` passed. GitHub CI remains required
  for real pytest, Ruff and mypy evidence before merge.

## 2026-09-01 — 2.0.0-dev.213 canonical SoC projection

- Live dev.212 showed that the price-chart SoC line could disagree with the
  chosen route. The first bad boundary was Projection/UI: it privately
  re-simulated Execution Plan segments at maximum requested power instead of
  presenting the Winning Energy Path's ADR-030 Projected Energy States.
- Made every MEP market-route Energy Path publish the central-scenario storage
  checkpoints already produced by the complete lower/central/upper physical
  simulation. Native and freshly simulated incumbent paths retain their
  central-scenario projected states under the same explicit assumption.
- Removed the dashboard's private RTE, PV, household-load and segment-power SoC
  calculation. The chart now prepends the measured starting SoC and then
  renders the immutable projected states of the exact Winning Energy Path,
  coloured by the owning Path Segment.
- Kept Evaluation, commitment comparison, Execution Plans, dispatch and
  Zendure mappings unchanged. The missing hybrid NOM/PV plus residual-grid
  Candidate family remains a separate MEP Candidate Generation slice.
- Regression coverage requires market paths to contain canonical projected
  states and requires the published dashboard timeline to equal the Winning
  Energy Path states exactly. Direct execution passed both focused canonical
  projection scenarios, seven architecture-ownership scenarios, eight
  version/configuration scenarios and three dashboard/JavaScript scenarios.
  Python compilation and `git diff --check` passed. The recovered workspace
  still lacks pytest, Ruff and mypy, so GitHub CI remains required before
  merge.

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.
## 2026-09-02 — 2.0.0-dev.227 bounded market hourglasses

- Begrenst netladen-naar-handel tot de financieel beste complete route.
- Begrenst PV-handel en eventueel net-herstel tot één goedkoopste, zo laat mogelijk geplaatst energievenster.
- Behoudt het fysieke 100%-SoC-doel los van de harde huishoudreserve; Evaluation blijft financiële, zelfverbruik- en reserve-uitkomsten vergelijken.
- Legt vast dat uitvoering direct na export terugkeert naar slim huishoudelijk ontladen wanneer geen PV-venster actief is.
- Normatieve basis blijft uitsluitend ADR-001 t/m ADR-037.

## 2026-09-02 — 2.0.0-dev.228 confidence-weighted effective maximum

- Houdt de vroege huishoudreserve als afzonderlijke harde ondergrens in stand.
- Bepaalt per compleet MEP-pad de hoogste opslagstand op een expliciete,
  confidence-gewogen forecastbasis tussen lower en central; upper blijft alleen
  beschikbaar als scenario-evidence.
- Wanneer een PV-only pad op die basis de effectieve fysieke bovengrens kan
  bereiken, zijn paden die die bovengrens niet bereiken ongeldig. Evaluation
  kiest daarna nog steeds uitsluitend tussen de geldige complete paden.
- Publiceert per Candidate Outcome de effectieve maximale energie, gewogen
  piek en piektijd, targetdeadline, bereiktijd, confidence, beslisreden en een
  stabiel evidence-ID. De vroege huishoudreserve blijft afzonderlijk zichtbaar.
- Voegt geen verborgen score, nieuw gebruikersgewicht of terminale
  batterijwaarde toe. Bij onvoldoende PV blijft de bestaande financiële
  vergelijking behouden.
- Normatieve basis blijft uitsluitend ADR-001 t/m ADR-037.

## 2026-09-02 — 2.0.0-dev.230 full PV preservation and saldering rule

- Corrected the PV-preservation User Rule: residual grid charging is now an
  overlay inside the complete Solcast-derived NOM window instead of preserving
  only the immediately adjacent intervals.
- Added the persistent Strategy User Rule
  `saldering_energy_tax_credit_enabled`. It defaults to enabled for backward
  compatibility and can be changed from the Strategy dashboard.
- The active tariff valuation removes the energy-tax credit immediately when
  the rule is disabled; the statutory 2027 boundary remains fail-safe and
  always disables it.
- Candidate generation and physical MEP simulation remain single-pass; the
  rule changes tariff valuation without adding candidate paths.

## 2026-09-02 — 2.0.0-dev.229 canonical user rules

- Verplaatst de handels-SoC-voorkeur naar een persistent canoniek User Rule
  profiel op het Strategie-dashboard; de bestaande add-onwaarde is alleen de
  eenmalige migratiebron.
- Voegt de expliciete User Rule toe dat noodzakelijk netladen de omliggende
  NOM/PV-opvang niet mag uitschakelen. De Candidate-laag vormt één begrensd
  hybride pad waarin netenergie alleen het resterende tekort vult.
- Past beide regels als harde kandidaatbegrenzing toe vóór Evaluation. De
  Opportunity Engine blijft uitsluitend prijsvensters leveren en MEP blijft
  complete fysieke paden vormen en simuleren.
- Een wijziging wordt atomair opgeslagen, zichtbaar voorzien van revisie en
  tijdstip, en activeert direct herplanning.
- De handelszandloper blijft aanvullend begrensd door de technische ondergrens,
  huishoudreserve en 10 procentpunt extra reserve.
- Geen nieuwe optimalisatiedoelstelling, verborgen score of alternatieve
  ADR-basis toegevoegd; normatief blijven uitsluitend ADR-001 t/m ADR-037.

## 2026-09-03 — 2.0.0-dev.231 enforced PV-preserving market parent

- Net-charging market routes must use a bounded hybrid PV/grid parent when the
  canonical PV-preservation User Rule is enabled; the household-only baseline
  can no longer bypass that rule.
- Every projected PV interval remains NOM, with grid charging as the only
  permitted overlay. Market export cannot replace PV capture inside that
  window.
- Added a regression test covering parent lineage and the complete projected
  PV window without adding route combinations.

## 2026-09-03 — 2.0.0-dev.232 preserve explicit market export overlay

- Fixed the DEV.231 regression that allowed projected-PV NOM to overwrite an
  explicit market-export interval, making an otherwise valid hybrid market
  route physically inadmissible.
- The bounded priority is now grid charge, explicit market export, projected
  PV NOM, then the parent household intent. The User Rule is projected onto
  the existing market route instead of replacing it with a different parent.
- Added regression evidence that the existing baseline-derived grid-trade
  route remains physically valid and admitted with NOM over projected PV.

## 2026-09-03 — 2.0.0-dev.233 preserve User Rule continuity

- Projects the existing PV-preservation User Rule onto every already-bounded
  Candidate Generation path on a day that needs residual grid charging.
- Keeps all Solcast-upper positive-PV intervals in NOM while retaining explicit
  grid charge and market export as higher-priority overlays. No candidate,
  route, or timing alternative is added.
- Validates a commitment that is already inside its grid-charge segment against
  the original preceding NOM segment instead of rejecting it because the
  rolling horizon no longer contains elapsed context.
- MEP still simulates the complete paths and Evaluation still selects among
  valid paths using the existing objectives and switching margin.
- Normative basis remains exclusively ADR-001 through ADR-037.

## 2026-09-03 — 2.0.0-dev.234 contain depleted-storage fallback projection

- Keeps the ADR-037 storage source-need balance prior to Candidate grid-energy
  planning, even when the household reference simulation requires residual
  grid import after storage depletion.
- Prevents a valid zero-SoC `mep_planning_blocked` fallback from terminating
  the runtime while the read-only dashboard projection is built.
- Adds regression coverage for a depleted storage snapshot, a blocked MEP
  result, and successful projection of the remaining grid-support need.
- Does not change Candidate construction, MEP simulation, Evaluation, plan
  commitment, or device execution behaviour.
- Normative basis remains exclusively ADR-001 through ADR-037.

## 2026-09-04 — 2.0.0-dev.235 retain maximum PV after grid charge

- Persists the User Rule day on the active MEP commitment, so an elapsed grid
  charge does not remove the requirement during a later rolling replan.
- Candidate Generation projects NOM onto every remaining Solcast-upper
  positive-PV interval on that day. Explicit grid charge and market export
  remain higher-priority overlays on the same complete path.
- MEP rejects any challenger that would discard remaining possible PV on the
  retained day, including a challenger that no longer contains the elapsed
  grid-charge segment itself.
- If forecast PV cannot fill the battery, the rule still captures the maximum
  physically available PV instead of switching early to household-only
  discharge. Evaluation continues to compare the remaining complete paths.
- Adds a two-cycle regression proving that NOM survives successive replans and
  that the User Rule context survives commitment-store reloads.
- No new route or timing alternatives are introduced; normative basis remains
  exclusively ADR-001 through ADR-037.

## 2026-09-04 — 2.0.0-dev.236 PV-first market route

- Retains the independently proven PV-only path even when Candidate Generation
  also discovers a hybrid PV plus residual-grid path.
- Places the interval-minimal NOM window where retaining PV has the lowest
  foregone export value; equal alternatives remain bounded to one latest path.
- Adds one bounded `pv_surplus_export` route: forecast PV is captured first and
  only the protected surplus may be exported later, without invented grid
  charging or a Cartesian expansion of route timings.
- Uses incremental financial value only for route admission. Evaluation compares
  admitted complete paths by their worst-case total financial result, because
  increments against different native parents are not mutually comparable.
- Ordinary grid arbitrage and grid-recovery routes remain available when valid;
  the existing User Rule remains the explicit authority for a non-financial PV
  preservation preference.
- Opportunity Engine remains evidence-only, Candidate Generation constructs the
  bounded paths, MEP simulates them and Evaluation selects the winner. Normative
  basis remains exclusively ADR-001 through ADR-037.

## 2026-09-05 — 2.0.0-dev.237 bounded daily market chain

- Replaces the horizon-wide single `pv_surplus_export` choice with at most one
  bounded zero-grid export route per local calendar day. Profitable routes for
  today and tomorrow therefore no longer suppress each other in a 36-hour run.
- Candidate Generation adds only one daily-chain alternative, MEP simulates its
  complete storage trajectory and Evaluation retains authority over physical
  validity and financial selection. Opportunity Engine remains evidence-only.
- Keeps the route energy target fractional. The financial schedule remains
  tariff-aligned, while the executable Energy Path ends the final full-power
  export segment exactly when its Wh budget is exhausted and returns the
  remainder of that quarter to household support.
- Persists those exact execution boundaries in the active commitment, so a
  live loop wakes at the boundary. The Execution Engine dispatches the next
  already-approved commitment segment before Candidate planning starts, so
  the hourglass transition does not wait for a new Planner Run or the next
  tariff-interval boundary.
- The direct boundary path retains the normal execution guards: observer mode,
  BMS calibration, missing capability evidence and manual override all block
  dispatch. Successful changes retain provenance and transition history.
- Increments the Candidate Outcome and commitment method versions so a stored
  pre-fix commitment is replanned rather than silently retaining coarse export
  timing.
- Verified locally with 1,148 passing full-suite tests; the sole environment
  failure (Node absent from the default PATH) passed separately with the
  bundled Node runtime. An additional 50 direct-boundary, execution, polling
  and live-runtime tests passed after adding the exact wake-up and pre-planner
  dispatch. Ruff and mypy are green on all changed source files. CI and live
  execution remain to be verified.
- Normative basis remains exclusively ADR-001 through ADR-037.

## 2026-09-06 — 2.0.0-dev.238 optional Energy Devices catalog

- Accepted V2ADR-064 for a separate, read-only energy-device profile producer.
  The producer owns only user-selected Home Assistant sensor bindings, samples,
  sessions and learned cards; it has no planning or execution authority.
- Added the `PicoT Energy Devices` Home Assistant add-on with an ingress
  registry, SQLite evidence store, session learning and one neutral catalog
  state. Newly registered devices are cards immediately, even before enough
  sessions exist for a reliable learned profile.
- Added an optional PicoT catalog observer outside Planning Input Snapshot
  assembly. Missing, malformed and unsupported catalogs yield zero cards and
  cannot block or change a Planner Run.
- Added an **Apparaten** dashboard tab. The user may select a discovered card,
  place it on the 48-hour price timeline and remove it again. These placements
  are durable but explicitly observer-only; they do not reset or influence MEP.
- Deferred planning influence until a later slice can form a residual household
  baseline and prove that registered-device energy is not counted twice.
- V2ADR-064 refines the external source and optional optimisation boundary;
  ADR-019, ADR-021, ADR-022, ADR-028, ADR-034 and ADR-037 retain their existing
  ownership, while V2ADR-001 and V2ADR-055 retain single ingestion and sole MEP
  planning authority.

## 2026-09-06 — 2.0.0-dev.241 energy-equivalent PV-first market route

- Corrects the hybrid Candidate construction so residual grid charging can no
  longer replace the NOM intervals that cover forecast PV surplus.
- Builds `grid_trade` only on a bounded PV-first plus residual-grid parent when
  such a complete path exists. The bare household baseline remains the fallback
  for a no-PV situation, so valid winter grid trading is not removed.
- Keeps the parent path's proven residual-grid segments when applying the
  market overlay; only the explicit market charge and export are added.
- Removes the former ambiguous nested parent-selection expression and retains
  one explicit ownership chain: Candidate Generation forms the energy path,
  MEP simulates it, Evaluation compares admitted paths, and commitment retains
  the selected result.
- Adds regressions for full-PV NOM precedence, equal-energy grid-trade parents,
  target attainment across all PV scenarios, no-PV fallback, and the canonical
  executable market path.
- Does not add a planning loop, route family, timing search, User Rule, or
  commitment override. Normative basis remains ADR-024, ADR-037 and ADR-041.

## 2026-09-07 — 2.0.0-dev.242 single market-trade hourglass

- Accepts V2ADR-065 and replaces the overlapping PV, stored-energy,
  grid-recovery and daily-chain export routes with one source-independent
  `grid_trade` decision. The route name denotes grid export and no longer
  implies or creates a grid-charge session.
- Uses one projected availability budget above the physical and configured
  reserves, one configured trading-SoC hourglass and one best peak-anchored
  export window across the planning horizon.
- Values recovery once from the canonical native plan. Forecast PV contributes
  zero cost and residual grid input contributes its actual interval tariff, so
  PV-only, mixed and grid-only days use the same energy-weighted calculation.
- The market overlay changes only the selected export interval. It cannot add,
  shorten or replace NOM or net-loading intervals; those remain exclusively
  owned by the canonical Candidate path.
- Removes `pv_trade`, `pv_trade_grid_recovery`, `pv_surplus_export`,
  `stored_energy_export`, `daily_export_chain`, their route-parent matrix and
  horizon-end equality exception matrix. `negative_capacity` remains separate.
- Keeps one scenario assessment per retained route. Storage inventory origin is
  no longer a route dependency, while full physical simulation and reserve
  protection remain mandatory.

## 2026-09-07 — 2.0.0-dev.243 overlapping-tariff recovery

- Corrects the DEV.242 recovery valuation for live forecast intervals whose
  boundaries differ by seconds from the wall-clock tariff quarters.
- Values grid recovery with the duration-weighted import tariff across every
  overlapping price slice instead of requiring an exact interval-key match.
- Treats incomplete tariff coverage as unavailable evidence for the optional
  `grid_trade` comparison. The canonical native plan remains executable and is
  no longer blocked by this market-route valuation detail.
- Adds no route, planning loop, User Rule or commitment exception. The single
  source-independent trade hourglass and PV-first native planning ownership
  introduced by DEV.242 remain unchanged.


## 2026-09-07 — MEP-2026-09-07 gekoppelde ADR-voorstellen

- Gebruiker bevestigt dev.243 live. Actieve documentatiebranch: docs/session-2026-09-07-linked-adrs.
- Uitsluitend ADR-001 t/m ADR-037 door gebruiker bevestigd als geaccepteerd en bevroren. Latere ADR/V2ADR-acceptatieteksten hierboven zijn historische verslagen, geen autoriteit voor deze nieuwe sessiereeks.
- Toegevoegd: ADR-037.1 (dagelijks laadcommitment) en ADR-019.1 (handel als gebruikersregel met optioneel herstel), plus SESSION-2026-09-07-ADR-INDEX.md.
- Status PROPOSED: sessieafspraken gedocumenteerd; exacte tekst nog ter beoordeling. Geen broncode, runtime of bestaande ADR gewijzigd.
- Documentatiecommits tot 39e2d19b2a03035053edff5f9da70fa52c515e16 aangemaakt; geen CI- of live-verificatie van nieuwe functionaliteit.
- Open specificatiepunten staan in beide voorstellen en mogen niet met verborgen defaults worden ingevuld.
- Eerstvolgende actie: documenten beoordelen; daarnaast dev.243 observeren op de aangekondigde dag met weinig PV. Dit is een test van huidige code, niet van de nog niet geïmplementeerde ADR-voorstellen.


## 2026-09-07 — Acceptatie gekoppelde ADR's en start planningsherbouw

- Gebruiker bevestigt vastlegging en start. ADR-037.1 en ADR-019.1 zijn ACCEPTED voor hun beschreven besluiten; expliciete open specificatiepunten blijven open.
- ADR-001..037 blijven bevroren. Latere ADR's/V2ADR's krijgen geen impliciete autoriteit.
- Pipeline behouden; geen reeks symptoomfixes op live dev.243. Toegevoegd MEP_REBUILD_START_2026-09-07.md met scope, eerste bronoorzaak en HA-verificatiematrix.
- Diagnose run-51f77f69d6acd6b6 toont hybride NOM-voorrang die middagnetladen verhindert en vroege verwijdering van grid-alternatieven; commitment behoudt een gelijkwaardig opnieuw berekend avondpad.
- Status: documentatie vastgelegd tot commit 6f2c08322f2ecbe304116b35f1b461a7f562d38d. Geen productiecode gewijzigd, geen tests uitgevoerd voor nieuwe functionaliteit, geen CI/LIVE-verificatie daarvan.
- Eerste volgende actie: open contractspecificaties afronden en simulator/planner/commitmentgrenzen gericht inventariseren voor de eerste complete laadcyclus.


### Vervolg — eerste hergebruikinventarisatie

- Gelezen op main: independent_daily_intent_simulator.py en plan_commitment_store.py.
- De intent-simulator accepteert een volledig opgegeven schema, actuele opslag, huisvraag, PV-scenario's, conversiemodel en vermogensgrenzen. Vensterselectie staat daarbuiten: kandidaat voor gericht hergebruik, nog niet numeriek/live geverifieerd.
- ActivePlanCommitment bewaart plansegmenten, oude prognose en SOC-checkpoints, maar heeft geen expliciete dagelijkse publicatie-identiteit of blijvende waargenomen doelbehaald-status. Dit is de concrete uitbreidingsbehoefte binnen bestaande opslag.
- De simulator begrenst ontlading op de minimumreserve en wijst resterende huisvraag aan het net toe. Alleen minimum-SOC controleren kan daardoor ongepland netverbruik missen; bewaking moet de resulterende netvraag en energietekort meenemen zonder een nieuw hard verbod op huisimport in te voeren.
- Open ontwerpkeuze: periode koppelen aan de gepubliceerde leveringsdag of exact 24 uur vanaf publicatie. Voorstel ter bespreking: leveringsdag met vaste lokale grenzen; publicatie is alleen startsein. Nog niet besloten of geïmplementeerd.


### Bevestigd: leveringsdag als doelperiode

- Toegevoegd geaccepteerd ADR-037.2, sessiereeks MEP-2026-09-07, zonder bevroren ADR-037.1 te herschrijven.
- Gepubliceerde lokale leveringsdag 00:00–00:00; publicatiemoment start de planning maar niet de doelperiode. Klokwisseldagen volgen 23/25 uur.
- Resterend vandaag plus morgen is ongeveer 36 uur. Lopend commitment behouden; voltooiing wordt niet gereset door opnieuw ontvangen prijzen.
- Uitsluitend documentatie, geen runtimewijziging of nieuwe verificatieclaim.
- Volgende specificatiepunten: doelwaarneming bij start met volle batterij, ontbrekende publicatie/eerste start en grenzen van segmentaanpassing.


### ADR-037.3 — hoofdopdracht is enige eigenaar van doelvoltooiing

- Gebruiker verwerpt automatisch afvinken bij volle batterij aan begin leveringsdag. Alleen de na prijspublicatie oorspronkelijk vastgelegde hoofdopdracht kan het dagdoel voltooien.
- Aanvullende/overbruggingssegmenten tellen niet, ook niet bij 100%. Hoofdopdrachtidentiteit blijft behouden tijdens optimalisatie en herstarts.
- Toegevoegd ADR-037.3 zonder bevroren teksten te herschrijven. Geen runtimewijziging of verificatieclaim.
- Open spanning expliciet benoemd: hoofdsegment mist 100% en aanvullend segment bereikt het wel. Aanvulling mag volgens de nieuwe afspraak niet afvinken; afhandeling nog uitwerken vóór implementatie.


### ADR-037.4 — aangescherpt hoofdopdrachtcontract

- Gebruiker bevestigt één blijvende hoofdopdracht met 100% in het gunstigste haalbare venster; route mag veranderen van PV-only naar lang NOM plus benodigde netaanvulling.
- Netaanvulling om hoofdopdracht te voltooien hoort bij de afvinkbare route. Aparte overbrugging niet. Dit sluit de open spanning uit ADR-037.3.
- Relevante SOC-afwijking, huisbelasting en mee-/tegenvallende PV zijn energietriggers; geen volledige herselectie zonder relevante gevolgen.
- Toegevoegd ADR-037.4 zonder geaccepteerde teksten te herschrijven. Status DECIDED, geen runtimewijziging of CI/LIVE-verificatie.
- Volgende stap: expliciete materialiteitscriteria/forecastbasis en afhandeling reeds vol bij start hoofdroute, eerste start en ontbrekende publicatie uitwerken.


### ADR-037.5 — expliciete PV-basis en terugval

- Gebruiker bevestigt (LOWER + CENTRAL) / 2 zonder extra confidence-weging.
- Snellere SOC-stijging alleen geeft geen herplanning. Onvoldoende PV voor het bestaande laadsegment geeft optimalisatie; rond LOWER of boven CENTRAL geeft beoordeling op uitvoeringsgevolgen.
- Werkelijke PV-energie vergelijken over exact dezelfde verstreken periode; geen losse vermogensmeting.
- Werkelijke 100% bij start hoofdsegment mag hoofdopdracht afvinken. Alleen 100% bij middernacht/overbrugging blijft onvoldoende.
- Ontbrekende planningsgegevens: NOM, behoud commitment, bestaande uitvoeringsgrenzen respecteren.
- Status DECIDED; documentatie toegevoegd, geen runtime gewijzigd of live geverifieerd. Exacte vergelijkingsperiode, betekenis rond LOWER en meetgaten blijven expliciete specificatiepunten.


### ADR-037.6 — grens verduidelijkt

- Gebruiker bevestigt werkelijke PV op of onder LOWER (<=), niet 'rond LOWER'. Bovengrens blijft boven CENTRAL (>).
- Alleen relevante uitvoeringsgevolgen leiden tot routeaanpassing. Open punt rond LOWER gesloten; vergelijkingsperiode en meetgaten nog uitwerken.
- ADR-reeks en index bijgewerkt; geen runtimewijziging of nieuwe verificatieclaim.


### ADR-019.2 — handelsomvang en spread bevestigd

- Gebruiker bevestigt volume-afhankelijke spread: energiegewogen duur ontlaadvenster versus goedkoop fictief laadreferentievenster. Geen enkele hoogste/laagste kwartiervergelijking.
- Handelspercentage betreft bruikbare capaciteit (voorbeeld 25% van 8,16 kWh = 2,04 kWh); percentage en minimumspread zijn gebruikersvelden.
- Fictief referentieladen bepaalt geen werkelijke energiebron en creëert geen laadsegment. Werkelijk herstel en EUR 0,05/kWh nettomarge blijven afzonderlijke optionele toets.
- Vastgelegd ADR-019.2; geen codewijziging of live-verificatie.


### ADR-037.7 — gemiste prijspublicatie en opstart

- Gebruiker bevestigt dat bestaande prijzen bij opstart voldoende aanleiding zijn om een ontbrekende dagelijkse hoofdopdracht alsnog te maken.
- Leveringsdag per scope is de identiteit, niet ontvangsttijd. Bestaande opdracht en voltooiing herstellen; geen duplicaten of verzonnen eerdere voltooiing.
- Late start gebruikt resterende haalbare vensters; onhaalbaarheid expliciet melden. Ontbrekende planningsgegevens geven NOM-terugval.
- Documentatie bijgewerkt; implementatie en live-verificatie staan nog open. Volgende stap blijft eerste complete hoofdlaadcyclus binnen bestaande pipeline, met dev.243-casus en opeenvolgende HA-beslismomenten.

### 2026-09-07 — eerste implementatiestap hoofdlaadcyclus

- PicoT-basis: dev.243; geen versieverhoging of live-installatie. Werkbranch: `implement/first-daily-charge-cycle`, gebaseerd op documentatiecommit `080cbdab55c9b003d2df26386ba5db32ce90dac9` van `docs/session-2026-09-07-linked-adrs` (PR #616).
- Status: **IMPLEMENTED**, uitsluitend de levenscyclus en duurzame opslag van de hoofdopdracht. **De volledige eerste laadcyclus is nog niet geïmplementeerd en niet vrijgegeven.** Dit is geen oplossing voor de live dev.243-planning.
- Eigenaarschap: nieuw onveranderlijk `DailyChargeAssignment`-contract; opslag blijft bij bestaande `ActivePlanCommitmentStore`. Geen nieuwe pipeline, planner, batterijadapter of uitvoeringsroute.
- Geïmplementeerd: identiteit per scope/lokale leveringsdag; 23/25-uursdagen; ontbrekende opdracht reconstrueren uit bestaande aaneengesloten prijzen; huidige opdracht behouden bij volgende publicatie of ontbrekende prijzen; expliciete hoofdsegmenten; blijvende voltooiing op gemeten 100%; route-revisies met expliciete reden en bewijsidentiteit.
- Een hoofdsegment wordt expliciet door plan-ID en segment-ID gekoppeld. Afleiden uit alleen NOM/netladen is onvoldoende: daarmee zou een overbrugging ten onrechte kunnen afvinken. Tussen hoofdsegmenten is geen impliciete afvinkbare periode. Een netaanvulling kan expliciet onderdeel zijn van dezelfde hoofdroute.
- Vol bij start hoofdsegment telt. Vol tijdens een overbrugging, onder een oude plan-ID of bij geblokkeerde uitvoering telt niet. Een waarneming op het exacte einde van het hoofdsegment kan diens voltooiing aantonen, ook bij de daggrens. Telemetrieversheid en bewijs van werkelijk uitgevoerde segmentidentiteit moeten bij runtime-integratie door de bestaande uitvoeringsgrens worden geleverd; de domeinmodule haalt zelf geen metingen op.
- Bestaande JSON-opslag uitgebreid zonder oude commitments te vervangen. Nieuwe publicaties resetten geen voltooiing; verouderde revisies worden geweigerd. Een beschadigd opslagbestand wordt bij mutatie niet langer stilzwijgend door lege staat vervangen. Dit verandert het foutpad van de gedeelde opslag naar een expliciete fout; de runtime-afhandeling richting bewaakte NOM moet nog worden aangesloten voordat dit releasable is.
- Lokaal geverifieerd: 42 tests voor dagelijkse levenscyclus en commitment recovery; eerder in deze werkstap 72 tests geslaagd in gecombineerde run met `test_v2_mep_canonical_pipeline.py` (31 bestaande pipeline-tests plus toen 41 lifecycle/recovery-tests). Daarna is één lifecycle-sequentietest toegevoegd en de set van 42 opnieuw geslaagd. Ruff op gewijzigde Python-bestanden en mypy op beide productiebestanden geslaagd.
- Sequentietest: gemiste publicatie → hoofdroute vastleggen → PV-tekort/netaanvulling onder dezelfde opdracht → herstart zonder prijzen → gemeten voltooiing hoofdsegment → volgende publicatie met behoud voltooiing. Dit is een domein-/opslagtest, **geen HA-replay**.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. Geen replaybewijs van de aangeleverde dev.243-diagnostiek. Een eerdere brede lokale poging om vensterselectie direct te vervangen is niet behouden: die koppelde generieke segmenten impliciet aan de hoofdopdracht en liet bestaande pipeline-tests falen. Die wijzigingen staan niet in deze branch.
- DO NOT CHANGE: ADR-001 t/m ADR-037 bevroren; sessie-ADR's eveneens niet herschrijven. Latere oorspronkelijke ADR's niet als automatisch geaccepteerde beleidsbron gebruiken. Nieuwe afspraken blijven `MEP-2026-09-07`.
- Exacte positie: contract en Plan Store gereed als eerste bouwsteen; nog geen aanroep vanuit de actieve pipeline. Geen impliciete migratie van dev.243-plannen naar een hoofdopdracht.
- Eerstvolgende actie: binnen bestaande Candidate/Evaluation-grenzen vensters maken met `(LOWER + CENTRAL) / 2` als input voor fysieke simulatie, uitsluitend haalbare 100%-routes toelaten en expliciete hoofdsegmentidentiteiten aan de gekozen route koppelen. Daarna publication/recovery en gemeten uitvoering aansluiten, geldige optimalisatietriggers en NOM-terugval implementeren, en pas vervolgens opeenvolgende echte HA-inputs uit dev.243 door dezelfde pipeline verifiëren. Marktroute blijft aparte vervolgstap.

#### Opslagstatus van deze implementatiestap

- Lokale implementatiecommit: `fe11dd1bc09c7c816ffbc9adb3a0664d60056f51`.
- Push van `implement/first-daily-charge-cycle` naar `Brons1981/PicoT-HEMS` is door de automatische goedkeuringscontrole geweigerd: expliciete toestemming voor deze externe write ontbreekt volgens de controle en de bestemming is niet als vertrouwd vastgesteld voor mogelijk private broncode.
- Geen omweg gebruikt. Code en sessielog staan lokaal gecommit; geen nieuwe PR aangemaakt en geen geslaagde push geclaimd. Publiceren van deze concrete branch vereist bevestiging van de gebruiker. Dit staat los van de nog ontbrekende runtime-implementatie hierboven.

#### Vervolg — publicatie expliciet geautoriseerd

- Alex heeft het publiceren van `implement/first-daily-charge-cycle` naar `Brons1981/PicoT-HEMS` expliciet goedgekeurd.
- De gewone Git-push mist HTTPS-aanmeldgegevens in deze omgeving. Publicatie wordt daarom via de gekoppelde GitHub-verbinding uitgevoerd, met dezelfde bestanden en basiscommit. Daardoor kunnen de remote commit-ID's verschillen van de lokale commits hierboven.
- Dit akkoord betreft publicatie van de ontwikkelbranch; geen merge, live-installatie of claim dat de volledige laadcyclus gereed is.

### 2026-09-07 — hoofdlaadvensters op expliciete PV-planningsbasis

- Basis dev.243; geen versie- of live-wijziging. Branch `implement/first-daily-charge-cycle`. Vorige gepubliceerde commit `ad6c3281f9ab55c5fb461959a31750fe535f6516`; lokale inhoud vóór deze stap was daarmee gelijk (tree `61cb2056881ff35d7c229e2c4c959f8ad3a6edf2`).
- Status **IMPLEMENTED** voor vensterontdekking aan de bestaande Candidate-inputgrens. Dit is nog geen volledige financiële selectie, runtime-integratie of release. De nieuwe methoden worden niet door de actieve `CanonicalPipeline` aangeroepen.
- `IndependentDailyReferenceAdapter.main_charge_windows` valideert bestaande prijsdekking en fysieke input voor een expliciete dagelijkse hoofdopdracht. De volledige gepubliceerde horizon tot maximaal 36 uur blijft in de simulatie; alleen de afvinkbare hoofdsegmenten worden door de leveringsdag begrensd. Ontbrekende dekking/ranges geven een expliciete inputfout, geen verzonnen prijzen of forecasts.
- `IndependentDailyIntentSimulator.simulate_planning_basis` maakt een afzonderlijk benoemde `DailyPlanningProjection` met `(LOWER + CENTRAL) / 2` vóór de fysieke berekening. De oorspronkelijke drie scenario's blijven ongewijzigd. De fysieke intent-berekening is in één gedeelde methode ondergebracht: geen kopie van de energiebalans of alternatieve simulator.
- Numerieke regressie: LOWER 0 Wh, CENTRAL 2000 Wh, huisvraag 100 Wh en 1200 Wh laadvermogensruimte per interval geeft 900 Wh opgeslagen energie bij rendement 1. Achteraf middelen van de begrensde scenario-SOC's zou 550 Wh opleveren. Confidence 2% verlaagt die 900 Wh niet.
- `IndependentDailyChargeWindowDiscoverer.discover_main_charge` maakt ongerangschikte haalbare vensters voor de eerste route. Bij voldoende PV blijven PV-vensters over; anders worden de resterende netlaadstarts onderzocht met behoud van PV-opvang. Netladen overschrijft NOM uitsluitend in de eigen laadintervallen, ook midden in het PV-venster. De noodzakelijke duur wordt via dezelfde fysieke simulatie bepaald.
- Alleen routes met aantoonbaar geprojecteerde 100% binnen expliciete hoofdsegmenten worden opgenomen. Geen micro-laadsuppressie voor een open dagdoel. Een geconfigureerd maximum onder 100% en onvoldoende resterende laadcapaciteit geven onhaalbaarheid. Reeds werkelijk voltooid geeft geen nieuwe prijs-/forecastzoektocht. Een reeds gebonden, onvoltooide hoofdroute wordt geweigerd bij eerste ontdekking: daarvoor moet de nog aan te sluiten optimalisatiegrens een geldige trigger leveren.
- Behoud: meegegeven segmenten buiten de nieuwe hoofdroute blijven gelijk en tellen mee in de volledige fysieke projectie. Kandidaatsegmenten dragen expliciete identiteiten; de toekomstige Plan Builder-koppeling moet deze naar werkelijke uitvoeringssegmenten herleiden.
- Eigenaarschap: vensterontdekking kiest geen economische winnaar en gebruikt geen verborgen prijsscore. Het bestaande Evaluation-pad moet de financiële keuze maken. De huidige legacy-planner is niet stilzwijgend met deze methoden vermengd; er is geen tweede runtime of batterijaansturing toegevoegd.
- Toegevoegd `tests/fixtures/dev243_main_charge_inputs.json`: beperkte numerieke invoer uit de aangeleverde diagnose, zonder entiteitnamen, apparaatreferenties of historische bronidentiteiten. 117 prijsintervallen, 59 PV-intervallen en 117 huisvraagintervallen; SOC 91%, bruikbare capaciteit 8160 Wh, gemeten RTE 80,67%. Dit is invoer voor de adaptertest, geen volledige reconstructie van een HA-snapshot of controle van oorspronkelijke telemetrieversheid.
- De dev.243-invoertest toont dat haalbare hybride routes met netladen in de middag (11:00–15:00 lokale tijd) beschikbaar blijven. Zij bewijst niet welke route Evaluation kiest, wat @gielz uitvoert of hoe latere meetmomenten tot revisies leiden.
- Verse lokale verificatie: `pytest` op `test_daily_main_charge_windows.py`, `test_daily_charge_assignment.py`, `test_independent_daily_intent_simulator.py`, `test_independent_daily_charge_window_discoverer.py`, `test_independent_daily_reference_adapter.py`, `test_v2_mep_canonical_pipeline.py`: **100 passed**, 70,25 s. Ruff op de gewijzigde Python-bestanden en mypy op de vijf gewijzigde productiebestanden: geslaagd. `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De oorspronkelijke fysieke intent-simulatie en bestaande pipeline zijn met regressietests gecontroleerd; dit is geen HA-uitvoeringsbewijs. De losse dev.243-invoertest duurde lokaal circa 3,34 s; dit is geen gegarandeerd runtimebudget op de NUC. De telling van fysieke simulaties is expliciet beschikbaar.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's blijven bevroren. Geen parallelle pipeline, impliciete vendorsturing, nieuwe prijsgrenzen of verborgen optimalisatietriggers. Marktroute blijft een afzonderlijke vervolgstap.
- Exacte positie: dagelijkse opdracht/opslag en haalbare vensterontdekking zijn gereed als bouwstenen. Financiële settlement/selectie van de expliciete planningsprojectie, omzetting naar het canonieke winnende pad, binding aan dagelijkse opdracht en uitvoering ontbreken nog.
- Eerstvolgende actie: de ongerangschikte hoofdlaadvensters via de bestaande financiële settlement en Evaluation vergelijken; de winnaar met zijn expliciete hoofdsegmentidentiteiten aan de bewaarde dagelijkse opdracht koppelen. Daarna publication/recovery, uitvoeringstelemetrie, geldige optimalisatietriggers en bewaakte NOM-terugval aansluiten. Voor vrijgave blijven opeenvolgende HA-waarnemingen/herstartproeven noodzakelijk.

### 2026-09-07 — financiële vergelijking en binding van de gekozen hoofdroute

- Basis dev.243; geen versie- of live-wijziging. Branch `implement/first-daily-charge-cycle`, gebaseerd op gepubliceerde commit `f9b507a09ed0c242c0d6a017b8a965e49985e121` (tree `200e5bac471e6a2a7c28e73db6ca960a30343261`).
- Status **IMPLEMENTED** voor de moduleketen venster → settlement → canonieke Candidate/Outcome → bestaande Evaluation → bestaande Execution Plan Builder → opgeslagen dagelijkse hoofdsegmentkoppeling. De actieve `CanonicalPipeline` roept deze keten nog niet aan. Geen release of HA-uitvoeringsclaim.
- `IndependentDailyFinancialSettlement.settle_planning_basis` hergebruikt dezelfde intervalafrekening en fiscale allocatie als de drie bestaande scenario's. De gedeelde berekening is uitgehaald zonder de bestaande scenario-uitkomsten opnieuw te definiëren.
- Belangrijke gecontroleerde valkuil: uitsluitend het totale horizon-kassaldo vergelijken koos in de dev.243-invoer 00:15–01:30. Die route kocht circa 2,80 kWh tegen gemiddeld EUR 0,338/kWh en eindigde op circa 27,7% SOC. Een middagroute kocht meer energie en hield meer voorraad over. Minder uitgeven betekende hier niet het goedkoopste laadvenster. De aanvankelijke middagregressie faalde hierdoor; er is geen nacht-/middagverbod of fictieve restwaarde toegevoegd om deze test groen te maken.
- Uitwerking van de bestaande goedkoopste-haalbare-vensterafspraak (ADR-037.1/037.4): het financiële hoofdlaadcriterium is expliciet `EUR/kWh-stored`, lager is beter. Teller: inkoopkosten van netenergie plus gepubliceerde terugleverwaarde van gebruikte PV binnen de expliciete hoofdsegmenten. Noemer: daadwerkelijk geprojecteerde opgeslagen laadenergie na laadverlies. Huisvraag en andere bewaarde segmenten worden niet als hoofdlaadenergie meegeteld. Laadverlies wordt eenmaal via de noemer verwerkt.
- Het volledige import/export-kassaldo blijft afzonderlijk beschikbaar, samen met eindvoorraad, PV-gebruik, huisvraag en verliesdiagnostiek. Vermeden inkoop wordt niet nogmaals bij dat kassaldo opgeteld. Een hoofdsegment zonder benodigde laadenergie krijgt geen verzonnen nulprijs per kWh: het financiële criterium is dan niet beschikbaar, conform ADR-032.
- `produce_main_charge_portfolio` levert de bestaande canonieke `CandidateSet`, `CandidateOutcomeSet` en `PlannerStrategy` aan de ongewijzigde `EvaluationEngine`. De gebruikersgewichten en bestaande tie-breaks blijven gelden. Geen selectie door settlement of vensterontdekking. Niet-ondersteunde primitives en onbeschikbare opslag blijven expliciet ongeldig.
- Projecties van SOC, huisvraag, PV, netverkeer en conversieverlies komen uit de expliciete midpoint-projectie; geen centrale scenario-SOC of nulwaarden als invulling. Hoofdsegment-ID's blijven intact, ook naast een bewaard segment met dezelfde primitive.
- `ActivePlanCommitmentStore.bind_daily_main_plan` koppelt uitsluitend de expliciete `source_path_segment_id`-referenties van de door de Plan Builder geleverde hoofdsegmenten. De opgeslagen dagopdracht krijgt de uitvoeringsplan-ID, echte uitvoeringssegment-ID's en Evaluation-ID. Verkeerde snapshot/scope, een andere vensterkandidaat of gewijzigde segmentgrenzen worden geweigerd. Herhalen van dezelfde binding is idempotent; een andere route vereist een expliciete optimalisatietrigger. Geprojecteerde 100% voltooit niets.
- De dev.243-moduleketentest kiest nu een netlaadvenster in de middag, maakt het canonieke plan en bewaart de hoofdsegmentbinding. De numerieke invoer komt uit de bestaande beperkte diagnosefixture; capabilitymetadata blijft testmetadata. Dit is geen volledige HA-snapshotreconstructie, telemetrieversheidscontrole of uitvoeringstest.
- Verse lokale verificatie: **124 passed** in 70,32 s voor `test_daily_main_charge_selection.py`, `test_daily_main_charge_windows.py`, `test_daily_charge_assignment.py`, `test_independent_daily_financial_settlement.py`, `test_evaluation_engine.py`, `test_execution_plan_builder.py`, `test_v2_plan_commitment_store.py`, `test_v2_plan_commitment_recovery.py`, `test_v2_mep_canonical_pipeline.py`. Ruff op gewijzigde Python-bestanden, mypy op vier gewijzigde productiebestanden en `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. Deze stap bewaart de hoofdopdrachtbinding; de integratie met opslag/herstel van het volledige actieve uitvoeringsplan via de bestaande runtime is nog nodig. Geen vendorcommando's, deployment of merge uitgevoerd.
- Kritieke integratiegrens: meng in één Evaluation-run geen oude financiële `EUR`-uitkomsten met nieuwe `EUR/kWh-stored`-uitkomsten. Neem de bestaande schakel-/equivalentiemarge in EUR niet over als een marge per kWh. De eerste hoofdroute gebruikt de bestaande Evaluation zonder incumbent en zonder financiële equivalentiemarge. Een eenheidswissel is geen impliciete wijziging van gebruikersgewichten.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's blijven bevroren. Eén pipeline en één selecterende Evaluation. Geen verborgen restwaardetarief, vaste laadkloktijd, prijsgrens of nieuwe triggerdrempel. De marktroute is niet geïmplementeerd in deze stap.
- Exacte positie: alle bouwstenen tot geselecteerd uitvoeringsplan en dagopdrachtbinding zijn op moduleniveau verbonden en getest. De actieve runtime gebruikt nog de legacy-planning.
- Eerstvolgende actie: deze moduleketen binnen de bestaande `build_mep_canonical_run`/`CanonicalPipeline` aansluiten als uitvoering van de nieuwe dagelijkse hoofdopdracht, met één eigenaar per grens. Prijspublicatie en gemiste publicatie herstellen, volledig actief plan bewaren, actuele uitvoeringssegmentidentiteit gebruiken voor voltooiing, bestaande route behouden zonder geldige trigger en NOM-terugval bewaakt uitvoeren. Daarna opeenvolgende HA-waarnemingen en herstartproeven; geen live-vrijgave alleen op basis van deze tests.

### 2026-09-07 — atomair bewaren en exact herstellen van de hoofdroute

- Basis dev.243; branch `implement/first-daily-charge-cycle`. Vorige gepubliceerde commit `c87dea79e3ce3a2091e4b22c81c1d867e34e8c9b`, tree `dac078a1012e72c94234bbee7944b7645458d2be`. Geen versie-wijziging, merge of deployment.
- Status **IMPLEMENTED** voor de Plan Store-herstelgrens. De volledige runtime-aansluiting is nog niet voltooid. De concrete ontbrekende voorwaarde bij inspectie: de opgeslagen hoofdopdracht bevatte uitvoerings-ID's zonder de bijbehorende volledige canonieke planinhoud. Alleen die ID's herstellen is onvoldoende om de oorspronkelijke route te behouden.
- `bind_daily_main_plan` schrijft nu de dagelijkse hoofdsegmentbinding en het volledige onveranderlijke canonieke `ExecutionPlan` in één bestaande atomaire bestandsvervanging. Een fout vóór die vervanging laat de oude toestand intact. De Plan Store neemt geen selectie, uitvoeringstoestemming of vendorsturing over.
- `load_daily_main_plan` herstelt het exacte plan met oorspronkelijke snapshot-/Evaluation-/candidate-/pathreferenties, segmenten, primitives, vermogens, SOC-grenzen, bronbeleid en lifecycle. Geen nieuwe prijzen, forecasts of vensterselectie nodig voor deze opslagoperatie. Actuele fysieke validatie blijft vóór uitvoering noodzakelijk.
- Een onbekende opdracht is een fout; een bestaande nog ongebonden opdracht retourneert geen plan. Een gebonden opdracht zonder planinhoud, een verkeerde scope/plan/Evaluation-koppeling of verdwenen hoofdsegmenten geeft een expliciete herstelincidentmelding en fout. Dit wist of vervangt de opdracht niet. Oudere records met alleen hoofdsegment-ID's worden niet stilzwijgend tot een nieuwe route gemigreerd.
- Herhaald binden van exact dezelfde inhoud is zonder write idempotent. Andere inhoud onder dezelfde plan-ID wordt geweigerd. Een uitvoeringsreset wist de dagelijkse doelhistorie en de herstelinhoud niet; herstel van een `PROPOSED` plan is nadrukkelijk geen nieuwe toelating tot uitvoering.
- Elf nieuwe opslaggrensgevallen controleren exact herladen, idempotentie, een fout bij de atomaire rename plus retry, onveranderlijkheid onder dezelfde plan-ID, zes beschadigingsgevallen, bewezen voltooiing na herstart/reset en onbekende opdracht. De fixtures gebruiken bestaande Candidate → Evaluation → Plan Builder-productiecode. Dit is geen HA-replay en levert geen telemetrieversheids- of dispatchbewijs.
- Verse lokale verificatie: 69 tests geslaagd in 10,71 s voor `test_daily_main_plan_recovery.py`, `test_daily_main_charge_selection.py`, `test_daily_charge_assignment.py`, `test_v2_plan_commitment_store.py` en `test_v2_plan_commitment_recovery.py`. Ruff op gewijzigde Python-bestanden, mypy op `plan_commitment_store.py` en `git diff --check`: geslaagd. Aanvullend: bestaande canonieke pipeline-regressie, 31 passed in 60,88 s. De 69 tests zijn opnieuw uitgevoerd na aanscherping van de oorspronkelijke revision-/Evaluation-evidencecontrole. Totaal 100 geslaagde tests; geen HA-uitvoeringsbewijs.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De actieve pipeline blijft nog legacy-planning gebruiken. Dit is een afgeronde herstelvoorwaarde, niet de eerder aangekondigde volledige runtime-integratie.
- Overige concreet gevonden integratierisico's: `build_mep_canonical_run` kan nog een commitment wissen bij generieke SOC-doelbereiking, en bevat oude uitvoeringsrevisies via `_complete_acquisition_revision` en `_defer_charge_revision`. `live_runtime.prepare` past bovendien vóór planning nog `apply_daily_measured_pv_basis` toe. Die combinatie mag niet als uitvoering van de nieuwe vaste hoofdopdracht met ongewijzigde LOWER/CENTRAL-input worden geactiveerd.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's bevroren; één canonieke pipeline, geen stilzwijgende legacy-marktroute of EUR/EUR-per-kWh-menging. Geen nieuwe beleidsdrempels of tijdelijke parallelle planner toegevoegd.
- Exacte positie en volgende actie: de bestaande moduleketen bewaart nu zowel de hoofdopdracht als het bijbehorende volledige uitvoeringsplan. Binnen de bestaande pipeline moet deze nog de legacy-selectie en impliciete herplanregels vervangen, met publication recovery, actuele uitvoeringsidentiteit/telemetrie voor voltooiing, behoud zonder geldige trigger en bewaakte NOM-terugval. Daarna opeenvolgende HA-observaties/herstarts controleren vóór live-vrijgave.

### 2026-09-07 — dagelijkse publicatie en herstel aangesloten op runtime Planning Input

- Basis dev.243, branch `implement/first-daily-charge-cycle`, vorige gepubliceerde commit `6a3c063d88a7ce805d46f5d3602cd23a462558d5` (tree `2e90ec8523665ad2814f0cc44f9465ea1639501d`). Geen versie-bump, merge of deployment.
- Status **IMPLEMENTED** voor de inputzijde van de runtime-aansluiting. De nieuwe dagelijkse selectie/uitvoering is nog niet geactiveerd. Dit is expliciet een deelstap van de eerder aangekondigde runtime-integratie.
- `live_runtime.main.prepare_bundle` roept nu `_restore_daily_charge_context` aan vóór planning, via dezelfde bestaande inputvoorbereiding als herstel van actieve commitments. Er is geen tweede planner, Evaluation, pollingloop of vendorroute toegevoegd. Deze grens leest eigenaarschap en bewaart ontbrekende dagelijkse identiteiten; zij kiest geen laadvenster.
- `PlanningInputSnapshot.daily_charge_context` bevat de huidige snapshotreferentie, herstelstatus/reden, lokale tijdzone, relevante dagelijkse opdrachten en exact herstelde canonieke hoofdplannen. De oude snapshot-/Evaluation-identiteit binnen het opgeslagen plan blijft intact. Herstel is geen uitvoeringstoelating en een huidige SOC van 100% voltooit hier geen opdracht.
- De beschikbare canonieke prijsdekking wordt bij elke inputvoorbereiding vergeleken met de Plan Store. Het publicatie-event hoeft niet te zijn meegemaakt. Alleen ontbrekende dagidentiteiten worden geschreven. Herhaald ophalen of prijswijzigingen resetten geen bestaande opdracht. Zonder prijzen kunnen opgeslagen opdrachten en routes nog steeds worden hersteld.
- De bestaande geconfigureerde lokale tijdzone (`pv_sunset_timezone`) bepaalt de leveringsdag; geen nieuwe tijdzone-instelling. De tests controleren expliciet 23- en 25-uurs leveringsdagen. Een tijdzonewijziging geeft de bestaande expliciete migratiefout, zonder oude identiteiten te vervangen.
- Het inputvenster voor opgeslagen opdrachten begint bij de oudste huidige SOC-waarneming. Daardoor kan een meting vlak vóór middernacht haar vorige-dag-eigenaar nog behouden. Oudere historie blijft in de Plan Store staan en wordt niet gewist. Bewezen voltooiing blijft ook na ontlading bewaard.
- Onleesbare opslag, een ontbrekend gebonden plan, ongeldig prijsmateriaal, ontbrekende scope en schrijffouten leveren een expliciete geblokkeerde herstelcontext op. Een fout in nieuwe prijzen verwijdert een reeds herstelde route niet. `ready` betekent uitsluitend dat het herstel slaagde, niet dat een laadroute haalbaar of toegelaten is.
- De bestaande input-signatuur neemt alleen stabiele dagelijkse identiteiten, revisies, planreferenties, doelstatus en herstelstatus mee. De hersteltijd en gemeten verwerkingsduur zijn geen herplantrigger. Een echte volgende leveringsdag kan wel een nieuwe run signaleren. Dit vervangt nog niet de legacy SOC/PV-herplantriggers.
- Kaart 1 toont passief herstelstatus/reden, verwerkingsduur, leveringsdagen, hoofdplanreferenties, hoofdsegment-ID's en voltooiingsbewijs. Er is geen nieuwe dashboardkaart of diagnostische selectiecode toegevoegd.
- Verse lokale verificatie: **68 passed in 16,73 s** voor `test_daily_charge_runtime_input.py`, `test_daily_main_plan_recovery.py`, `test_v2_plan_commitment_recovery.py`, `test_v2_live_replan_poll_cycle.py` en `test_v2_live_pv_actual_coupling.py`. De 15 nieuwe inputtests zijn daarna nogmaals geslaagd in 2,02 s, nadat de polltest was aangescherpt naar daadwerkelijk verschillende opnametijden. De bestaande `main`-compositietest controleert dat deze herstelcontext de uitvoeringsinvoer daadwerkelijk bereikt, ook bij ontbrekende opslagscope.
- Ruff op gewijzigde productiebestanden en nieuwe tests: geslaagd. Mypy op beide productiebestanden: geslaagd met een verse lokale cache. De eerste mypy-pogingen strandden op een beschadigde SQLite-cache; er zijn geen typecontroles uitgezet of productieregels gewijzigd om dat te omzeilen. `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. Deze tests gebruiken gefingeerde HA-bronnen en de bestaande runtime-compositie; zij bewijzen geen live batterijsturing, actuele dispatchidentiteit, telemetrieversheid of volledige dev.243-replay.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's bevroren. Geen impliciete koppeling van legacy-plannen aan het nieuwe dagdoel; geen afronden op geprojecteerde SOC; geen nieuwe prijs-/PV-triggerdrempels.
- Exacte positie: publicatie en exact herstel zijn nu aangesloten op de actieve inputvoorbereiding. `build_mep_canonical_run` gebruikt nog de legacy Candidate/Evaluation-keten; `apply_daily_measured_pv_basis`, generieke doelbereiking en legacy uitvoeringsrevisies blijven daar nog actief. De nieuwe hoofdopdrachten blijven dus ongebonden totdat de nieuwe selectie wordt aangesloten; de opslaggrens kan reeds expliciet gebonden plannen herstellen.
- Eerstvolgende actie: de nieuwe hoofdopdracht als bron van kandidaatselectie gebruiken binnen dezelfde canonieke pipeline. Daarbij raw LOWER/CENTRAL voor midpoint-simulatie behouden, bestaand hoofdplan zonder trigger bewaren, eerste geldige selectie binden en gemeten voltooiing aan echte uitvoeringsidentiteit koppelen. Ook bewaakte NOM-terugval bij onbruikbare context/gegevens moet als uitvoerbaar gedrag worden aangesloten; de hier gerapporteerde herstelstatus is op zichzelf geen NOM-commando. De volledige runtime-aansluiting blijft open en is nog niet geschikt voor live-vrijgave.

### 2026-09-08 — lopende hoofdopdracht behouden bij planning van de volgende leveringsdag

- Basis dev.243; branch `implement/first-daily-charge-cycle`. Vorige gepubliceerde commit `e5707b41a8765619beb5d2901b1aff71eb1ea4a3`, tree `ca5a1cde19f27d685f37c403195ddbd7dbe8d977`. Geen versie-bump, merge of deployment.
- Status **IMPLEMENTED** voor behoud en herleidbaarheid van een andere lopende hoofdopdracht in de nieuwe kandidaatketen. De volledige hoofdplanselectie is nog niet omgezet in `build_mep_canonical_run`. Dit is een noodzakelijke deelstap, geen volledige runtime-omzetting.
- Concreet integratieprobleem: de horizon kan twee dagelijkse hoofdopdrachten omvatten. De ongewijzigde Plan Builder maakt voor een nieuwe winnende kandidaat nieuwe uitvoeringsplan-/segment-ID's. Alleen de nieuwe dag aan die ID's binden zou onvoldoende aantonen dat de andere hoofdopdracht nog wordt uitgevoerd. Er is geen nieuw beleid ingevoerd waarbij een prijspublicatie de oude hoofdopdracht herschrijft.
- `IndependentDailyReferenceAdapter.main_charge_windows` neemt nu de herstelde context mee. De bestaande planacties worden over de gemeenschappelijke horizon fysiek meegenomen; nieuw beschikbaar horizonbereik zonder opgeslagen actie gebruikt de bestaande baseline. Expliciet gekoppelde hoofdsegmenten hebben voor hun eigen actie voorrang op een ouder horizonplan dat daar nog een ongebonden baseline had. Als opgeslagen plannen buiten die hoofdsegmenten tegenstrijdige opdrachten bevatten, volgt een expliciete inputfout; er wordt geen winnaar gegokt op basis van prijs of opslagvolgorde.
- Een expliciet aangeleverd afwijkend retained schedule kan de herstelde bron niet overrulen. Ontbrekende dekking, niet-simuleerbare primitives, gewijzigd vastgelegd laadvermogen en een plan uit een toekomstige opname geven expliciete fouten. Er wordt geen marktroute of herstelbeleid bij verzonnen.
- Nieuwe `DailyRetainedMainSegment`-referenties dragen de oorspronkelijke dagopdracht, plan-ID en complete oorspronkelijke uitvoeringssegmentinhoud. De nieuwe `PathSegment` en `ExecutionPlanSegment` dragen optioneel `main_assignment_id` en `retained_execution_origin`. De bestaande Plan Builder en v2-projectie kopiëren die referenties zonder een planningbesluit te nemen. De nieuwe uitvoeringssegment-ID blijft een nieuwe ID; de oorspronkelijke hoofdopdracht wordt niet omgenummerd.
- Het resterende deel van een lopend segment mag bij een nieuwe opname beginnen op de nieuwe horizonstart, met behoud van de oorspronkelijke uitvoeringsreferentie. Primitive, capability, aangevraagd vermogen, bronbeleid, SOC-grenzen en energieprofiel moeten gelijk blijven. De reeds verlopen tijd wordt niet opnieuw ingepland.
- De Plan Store controleert vóór de atomaire eerste binding van de nieuwe dag dat elk overlappend hoofdsegment van een andere dag volledig als resterende actie aanwezig blijft en naar zijn echte opgeslagen eigenaar verwijst. Weggelaten delen, gewijzigde actie-inhoud en onjuiste oorsprong worden geweigerd. Alleen de nieuwe dagopdracht wordt gebonden; de oorspronkelijke dagopdracht, hoofdsegmenten en doelstatus blijven exact gelijk.
- Bij herladen worden oorsprong, scope, hoofdsegmentlidmaatschap, resterende tijdgrenzen en actie-inhoud opnieuw gecontroleerd. Oudere records zonder de optionele nieuwe velden blijven leesbaar. De idempotentiecontrole vergelijkt de gedeserialiseerde planinhoud zodat ontbrekende oude optionele velden geen onterechte inhoudswijziging veroorzaken.
- Haalbaarheid blijft voor alle nog open hoofdopdrachten vereist: een kandidaat voor morgen mag niet verhullen dat de ongewijzigde lopende hoofdroute door bijvoorbeeld SOC-tekort geen 100% meer kan bereiken. Zulke kandidaten worden niet toegelaten; de reden is `retained_main_goal_requires_explicit_optimisation`. Dit signaleert de benodigde optimalisatie, maar voert die nog niet uit. Geprojecteerde 100% voltooit geen van beide opdrachten.
- Negen nieuwe ketentests gebruiken de beperkte numerieke dev.243-fixture en expliciete testcapabilities. Zij controleren twee leveringsdagen via discovery → settlement → bestaande Evaluation → Plan Builder → Store → v2-projectie, behoud van de eerste eigenaar, geen afvinken op forecast, het resterende deel van een al begonnen segment, weigeren van weglating/gewijzigd vermogen/ontbrekende oorsprong, geblokkeerde herstelcontext, oude records, corrupte oorsprong en een onhaalbare lopende hoofdopdracht. Dit is geen volledige HA-replay.
- Verse lokale verificatie: **118 passed in 83,76 s** voor `test_daily_main_horizon_retention.py`, `test_daily_main_charge_selection.py`, `test_daily_main_plan_recovery.py`, `test_daily_charge_runtime_input.py`, `test_daily_main_charge_windows.py`, `test_execution_plan_builder.py`, `test_energy_path_charge_source_policy.py`, `test_v2_canonical_execution_runtime.py` en `test_v2_mep_canonical_pipeline.py`. Ruff op alle negen gewijzigde productiebestanden en de nieuwe tests, mypy op alle negen productiebestanden, en `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De actieve dagelijkse inputvoorbereiding blijft aangesloten zoals in de vorige stap; de nieuwe kandidaatketen gebruikt die context nu op moduleniveau. De actieve Candidate/Evaluation-aanroep gebruikt nog legacy MEP. Geen dispatch- of voltooiingsgedrag voor deze nieuwe referenties geclaimd.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's blijven bevroren. Geen nieuwe hoofdopdracht bij horizonverlenging voor dezelfde leveringsdag, geen impliciete routewijziging, geen nieuwe prijs-/SOC-/PV-drempels, geen tweede pipeline of selecterende service.
- Exacte volgende actie: de legacy selectieaanroep in de bestaande pipeline vervangen door de nieuwe hoofdopdrachtketen. Het globale uitvoeringsplan mag de nieuwe referenties gebruiken om de oorspronkelijke dagopdracht terug te vinden; oude `route_plan_id`-waarden mogen niet simpelweg naar de nieuwe dag worden overgeschreven. De bestaande uitvoeringsgrens moet het werkelijk uitgevoerde plan/segment plus SOC-waarneming bewijzen voordat via die gecontroleerde oorsprong wordt afgevinkt. Ook een duurzame actieve-planverwijzing, geldige optimalisatietriggers en bewaakte NOM-terugval blijven nodig.
- Integratievoorwaarden blijven: oorspronkelijke LOWER/CENTRAL behouden vóór midpoint-simulatie; geen legacy `apply_daily_measured_pv_basis` op die invoer; nieuwe financiële EUR/kWh-stored-uitkomsten niet mengen met oude EUR-uitkomsten of de oude EUR-schakelmarge; generieke SOC-wisregels en legacy uitvoeringsrevisies mogen de dagelijkse hoofdopdracht niet beheren. De volledige runtime-aansluiting blijft open en is nog niet geschikt voor live-vrijgave.

### 2026-09-08 — dagelijkse hoofdselectie aangesloten op de bestaande runtime

- Basis dev.243; branch `implement/first-daily-charge-cycle`. Vorige publicatie `bf015e4995a9e87a95955febe4dd25e3996fa157`, tree `376c18f5ae611c93191982cf212d01635e632879`. Geen versie-bump, merge of deployment.
- **IMPLEMENTED**: de dagelijkse context uit de echte inputvoorbereiding kiest nu de hoofdlaadkandidaten via de bestaande Evaluation en Plan Builder. De legacy generator wordt voor deze context niet aangeroepen. Alleen historische/bootstrap-input zonder dagelijkse context behoudt de oude aanroep voor compatibiliteit; er draait geen tweede planner of pollingloop.
- Eerstvolgende ongebonden leveringsdag wordt geselecteerd, met behoud van de reeds gebonden hoofdsegmenten. De bestaande EUR/kWh-stored-uitkomsten gaan zonder legacy EUR-schakelmarge naar Evaluation. De exacte canonieke uitkomsten worden afzonderlijk in het runtime-resultaat bewaard; ze worden niet als oude worst-case EUR-diagnostiek voorgesteld.
- De eerste binding kan atomair de expliciete actieve hoofdplanverwijzing per scope bewaren, samen met plan en dagopdracht. Herstel leest deze verwijzing; het raadt geen winnaar uit timestamps. Een herhaalde oude binding activeert die oude route niet opnieuw. Een corrupte actieve verwijzing blokkeert en wist niets.
- Een gebonden actieve route wordt zonder vensterontdekking of nieuwe Evaluation hergebruikt. De actuele observatie krijgt eigen lineage; het opgeslagen plan houdt zijn oorspronkelijke Evaluation-, plan- en segment-ID's. De nieuwe actieve verwijzing is onderdeel van de stabiele inputsignatuur.
- De live inputvoorbereiding laat toekomstige LOWER/CENTRAL ongewijzigd. Werkelijke gesloten PV-intervallen blijven aangehecht. `apply_daily_measured_pv_basis` en herstel/wissen van legacy commitments beheren de dagelijkse route niet meer. De gedeelde uitvoeringsgrens past geen legacy PV-uitstelrevisie op deze route toe.
- De bestaande klokgrens voert nu ook de expliciet actieve canonieke segmenten uit, met hun echte plan-/segment-ID's en vastgelegde vermogensvraag. Handmatige blokkades, BMS, capabilitybeschikbaarheid, primitiveondersteuning en de configuratie van vast laad-/ontlaadvermogen blijven uitvoeringsvoorwaarden. De adaptervertaling weigert scope-/capabilitymismatch en onbeschikbaar mappingbewijs.
- Bij geblokkeerde planning vraagt de bestaande uitvoeringsgrens de generieke NOM-primitive via dezelfde adapter. Dit is een expliciete fallback-uitvoeringsreferentie, geen verzonnen winnende kandidaat of nieuwe dagopdracht. Opgeslagen routes en doelen blijven bewaard. Ontbrekende scope/mapping of handmatige/BMS-blokkade wordt niet omzeild. De proceslokale uitvoeringsstatus verhindert dat de volgende klokpoll de zojuist gevraagde fallback zelfstandig terugdraait; een geldige planningsrun heft die opschorting op.
- Werkelijke voltooiing is aangesloten op bevestigde modusfeedback. Dispatch-ack alleen telt niet. De runtime bewaart proceslokaal vanaf wanneer hetzelfde uitvoeringssegment bevestigd is; blokkade, andere uitvoering en herstart wissen dat bevestigingsinterval. Alleen een SOC-meting binnen dit interval en binnen het expliciet gekoppelde hoofdsegment kan 100% bewijzen. De Store controleert het actieve plan en lost gevalideerde retained-origin-referenties op. Het bewijs noemt de werkelijk bevestigde nieuwe uitvoerings-ID's; alleen de oorspronkelijke eigenaar krijgt voltooiing. De opgeslagen voltooiing zelf overleeft herstart.
- Begrenzing voltooiingsbewijs: deze stap verzint geen telemetrieversheidsdrempel en dateert een oude SOC-meting niet opnieuw. Bij een al langdurig onveranderde 100%-waarde vóór eerste bevestiging ontbreekt nog bewijs binnen het bevestigingsinterval. Ook een pas na segmentovergang ontvangen eindmeting wordt hier niet retrospectief aan de vorige uitvoering toegeschreven. Dit vereist nog beoordeling met de echte HA-meetsemantiek; niet als volledig bewezen 100%-registratie in HA presenteren.
- Zes nieuwe actieve ketentests: eerste selectie en exact hergebruik zonder legacy generator/prijsherberekening; ontbrekende PV met behouden plan; corrupte actieve pointer; echte generieke fallback-dispatch met manual block; oude versus nieuwe SOC bij bevestigde modus en herstart; exacte segment-ID/vermogen aan de klokgrens. Eén aanvullende tweedaagse ketentest bewijst voltooiing van de oorspronkelijke eigenaar via de nieuwe uitvoeringsreferentie en voorkomt terugactiveren door een oude binding. De live compositietest verwacht nu oorspronkelijke toekomstige LOWER in plaats van de verwijderde verhoging.
- Verse lokale verificatie: **116 passed in 92,44 s** voor `test_daily_main_active_pipeline.py`, `test_daily_main_horizon_retention.py`, `test_v2_canonical_execution_runtime.py`, `test_v2_mep_canonical_pipeline.py`, `test_daily_main_plan_recovery.py`, `test_daily_charge_runtime_input.py`, `test_v2_live_replan_poll_cycle.py`, `test_v2_live_pv_actual_coupling.py`. Na aanvullende gedeelde capability-/vermogensvalidatie: de zes actieve ketentests opnieuw **6 passed in 5,60 s**. Ruff op vijf productiebestanden en beide nieuwe/aangevulde ketentestmodules, mypy op vijf productiebestanden en `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De nieuwe dispatchtests gebruiken een testadapter en gefingeerde, expliciet getimestampte HA-evidence. Geen echte HA-uitvoering, volledige dev.243-replay of garantie van onveranderde sensor-timestamps geclaimd.
- **Nog niet gereed voor live-vrijgave**: fysieke monitoring van de gebonden route en gerichte optimalisatie bij onhaalbare 100%, PV-afwijkingen, extra belasting of reservekort zijn nog niet aangesloten. In deze stap blijft een gebonden route behouden; expliciet geblokkeerde ontdekking gebruikt NOM-fallback en maakt geen herstelrevisie. De herstelbare uitvoeringsopschorting en retrospectieve meting bij segmentovergang moeten in opeenvolgende HA-observaties worden geverifieerd. Marktroute/user-rule en de passende weergave van nieuwe canonieke uitkomsten in alle dashboardvelden blijven vervolgwerk.
- DO NOT CHANGE: ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's blijven bevroren. Eén selecterende Evaluation en dezelfde generieke adapterroute. Geen nieuwe deadlines, PV/SOC-drempels of impliciete koppeling van legacy doelen aan de dagelijkse hoofdopdracht.

### 2026-09-08 — gerichte revisie bij aantoonbaar tekort van de hoofdroute

- Basis dev.243, branch `implement/first-daily-charge-cycle`; vorige publicatie `92ed8ad170efbc6671df4aa5cd1315e138c2c3bf`, tree `651af1ef0adb69f9a01a7d3375b4267290ab180e`. Geen versie-bump, merge of deployment. ADR-001 t/m ADR-037 en geaccepteerde sessie-ADR's blijven bevroren.
- **IMPLEMENTED** voor de eerste verticale optimalisatiestap: de bestaande hoofdroute wordt met de actuele SOC, midpoint-PV en huisvraag eenmaal fysiek doorgerekend. Dit is geen prijsvensterontdekking, settlement of nieuwe Evaluation. Als de nog open hoofdopdracht binnen haar expliciet gekoppelde hoofdsegmenten 100% kan halen, blijft zij staan. Snellere SOC-opbouw zonder tekort start geen nieuwe vensterzoektocht.
- `DailyMainShortfallTrigger` bevat opdracht-ID, oorspronkelijke route-ID/revisie, actieve horizonplan-ID, snapshot/tijd, geprojecteerde piek binnen de hoofdsegmenten en fysieke 100%-doelenergie. Alleen een aantoonbaar tekort levert dit contract op. De bestaande numerieke behoudstolerantie van 1e-6 Wh is gebruikt; geen nieuwe procent-, prijs-, samplecount- of tijdsdrempel toegevoegd. Een voltooide opdracht levert geen tekorttrigger meer op.
- De trigger staat tevens expliciet in het runtime-Evaluation-record (`daily_main_shortfall`) en wordt bij een geslaagde revisie opgeslagen. Forecast-haalbaarheid is geen gemeten voltooiing. Een ontbrekend resterend hoofdsegment mag niet als bewijs van eerder voltooien worden ingevuld.
- De actieve canonieke pipeline behandelt een tekort van een lopende opdracht vóór het maken van een nieuwe dagroute. Alleen met bij de huidige opdracht en input passend triggerbewijs mag de bestaande vensterontdekking een gebonden opdracht opnieuw onderzoeken. Zij vergelijkt toekomstige haalbare mogelijkheden via dezelfde Evaluation/Plan Builder, met ongewijzigde financiële eenheden en gebruikersgewichten. De tekortopdracht houdt dezelfde identiteit, leveringsdag en 100%-doelstelling; de technische route krijgt een traceerbare revisie.
- Bij het reconstrueren van de baseline is de expliciete actieve planverwijzing leidend buiten andere gekoppelde hoofdsegmenten. Er wordt geen plan gekozen uit timestamps. Bij revisie worden de eigen te vervangen hoofdacties vrijgegeven voor nieuwe discovery; hoofdsegmenten van andere opdrachten blijven expliciet behouden en moeten haalbaar blijven. Historische invoer zonder actieve verwijzing houdt de eerdere gecontroleerde reconstructie; live herstel verzint geen actieve verwijzing.
- De Store controleert opnieuw trigger-snapshot/tijd, actuele revisie, open doel, actieve plan-ID en doelenergie. Revisie, nieuw uitvoeringsplan, actieve verwijzing, triggerbewijs en archivering worden in één bestaande atomaire schrijfoperatie vastgelegd. Verouderd bewijs of een schrijffout kan niet half een nieuwe route activeren.
- Oude uitvoeringsplannen en bijbehorende opdrachtversies blijven in `daily_main_history` onder hun oorspronkelijke plan-ID staan. Dat is noodzakelijk omdat het plan voor morgen nog een expliciete oorsprongsreferentie naar de vorige route van vandaag kan bevatten. Herstel controleert ook die historische owner-/plan-/Evaluation-identiteit en de oorspronkelijke segmentinhoud. Dit verandert geen huidige doelstatus en geeft een historische uitvoering geen bevoegdheid om de nieuwe route af te vinken.
- Gerichte tests: verlies van PV maakt een oorspronkelijke PV-route onhaalbaar en voegt netladen toe onder dezelfde opdracht; hogere SOC houdt een haalbare route zonder vensterzoektocht; verouderde trigger wordt geweigerd; fysiek onhaalbare correctie houdt de oude route en een open doel met NOM-fallback; schrijffout houdt bestand en actieve verwijzing ongewijzigd. De tweedaagse ketentest reviseert vandaag terwijl morgen en haar historische uitvoeringsreferenties intact blijven, en herstelt die combinatie opnieuw uit de Store.
- Verse lokale verificatie: **136 passed in 75,34 s** voor `test_daily_main_route_optimisation.py`, `test_daily_main_horizon_retention.py`, `test_daily_main_active_pipeline.py`, `test_daily_main_charge_windows.py`, `test_daily_main_plan_recovery.py`, `test_daily_charge_runtime_input.py`, `test_daily_charge_assignment.py`, `test_v2_mep_canonical_pipeline.py`, `test_v2_canonical_execution_runtime.py`. Daarna is de schrijffouttest toegevoegd en het triggerbewijs in het runtime-record opgenomen: alle vijf gerichte optimalisatietests opnieuw **5 passed in 3,30 s**. Ruff op zes productiebestanden en beide gewijzigde testmodules, mypy op zes productiebestanden en `git diff --check`: geslaagd.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De tests gebruiken opeenvolgende gefingeerde snapshots, de numerieke dev.243-fixture en echte lokale opslag; geen nieuwe HA-diagnose of live batterijbewijs beschikbaar. Eerder beschreven grenzen van SOC-voltooiingsbewijs bij onveranderde/vertraagde metingen blijven open.
- Afbakening vervolgwerk: deze stap implementeert de expliciete trigger TARGET_UNREACHABLE. Optimalisatie vanwege PV op/onder LOWER of boven CENTRAL zonder dit doeltekort, verkorting bij meevallende PV, en reserve-/overbruggingsoptimalisatie na een voltooid dagdoel blijven open. Ook gelijktijdige tekorten van meerdere hoofdopdrachten kunnen gezamenlijke revisie vereisen: deze stap corrigeert één opdracht en laat geen kandidaat toe die een andere nog onhaalbaar laat. In dat geval volgt expliciete fallback, geen verzonnen gezamenlijke oplossing. Geen claim dat de volledige optimalisatie of live-vrijgave gereed is.

### 2026-09-08 — voorstel voor de nog open PV-vergelijkingsperiode

- Basis dev.243, branch `implement/first-daily-charge-cycle`; vorige publicatie `8803d1c94e4c9481c5e5371d4f29beeadf1fee5a`, tree `f1bd5aaef3c481f5ddfc64d2e2b3856bdf7ecb1b`. Geen versie-bump, merge of deployment.
- De gebruiker bevestigde vervolgwerk na de eerste gerichte tekortcorrectie. Bij het voorbereiden van optimalisatie door meevallende PV is de expliciete open grens in de bevroren ADR-037.5/037.6 vastgesteld: vergelijkingsperiode, vooraf bekende forecastreferentie en omgang met onvolledige metingen zijn nog geen geaccepteerde implementatieregels. Daarom geen willekeurig tijdvak of meetgatbeleid in de sturing geïntroduceerd.
- [ADR-037.8](../../architecture/ADR-037.8-pv-comparison-period-and-missing-observations.md) is als **PROPOSED** vastgelegd. Niet geaccepteerd en niet geactiveerd. Het voorstel vraagt één samenhangend besluit: een vaste referentie per hoofdopdracht en een cumulatieve periode binnen de leveringsdag; normaal vanaf lokale middernacht, bij een late eerste vastlegging vanaf het eerste volledig vooraf gedekte forecastinterval. Routecorrectie en restart resetten deze referentie niet.
- Voorgesteld meetgatbeleid: exacte aaneengesloten dekking van de bedoelde periode is vereist voor deze PV-trigger. Geen nulinvulling, extrapolatie of stilzwijgend verschuiven naar een ander deel. Een onvolledige PV-vergelijking blokkeert niet de reeds actieve zelfstandige tekortcontrole. Bij ontbrekende benodigde planningsgegevens blijft de eerder afgesproken NOM-fallback gelden.
- Voorgesteld herhalingsbeleid: dezelfde inhoudelijke PV-evidence wordt niet opnieuw een trigger door een andere polltijd, restart of de eigen routecorrectie. Nieuwe gesloten intervallen of aantoonbare broncorrecties kunnen nieuw bewijs zijn. Grenzen blijven exact <= LOWER en > CENTRAL; routeaanpassing vereist uitvoeringseffect, zoals minder benodigd toekomstig netladen met behoud van doelhaalbaarheid.
- Inspectie van de bestaande meetketen: `apply_latest_closed_actual_pv` verzamelt gesloten forecastintervallen uit de huidige input en maakt daarmee bestaande cumulatieve diagnostiek. `build_pv_cumulative_evidence` classificeert de algemene LOWER/UPPER-range, bepaalt volledigheid via aantallen en neemt `evaluated_at` mee in zijn bewijs-ID. Dit is geen reeds passend dagelijks LOWER/CENTRAL-stuurcontract. Deze diagnostische code is niet aangepast.
- De bestaande PV-learning-keten archiveert al vooraf bekende intervalforecasts, maar dat archief is niet de expliciete referentie van het geselecteerde hoofdplan. Een toekomstige implementatie moet de planningsreferentie en bronversies aantoonbaar koppelen; het voorstel verklaart bestaand learning-bewijs niet stilzwijgend tot hoofdplanbewijs.
- Verse lokale controle van bestaande meetfunctionaliteit: **8 passed in 0,21 s** voor `test_v2_pv_cumulative_evidence.py` en `test_v2_pv_actual_intervals.py`. Deze controle bewijst alleen de huidige geteste meetfunctionaliteit, niet het voorgestelde toekomstige triggergedrag. `git diff --check`: geslaagd. Productiecode en bestaande bevroren ADR's zijn niet gewijzigd.
- Exacte vervolgstap: expliciete bevestiging vragen van ADR-037.8, omdat ADR-037.6 de periode en meetgaten bewust openlaat. Daarna de boven-CENTRAL-trigger en gerichte vermindering van netladen implementeren via de bestaande pipeline, met vaste referentie, compleet dekkingsbewijs, duurzame verwerking en opeenvolgende HA-waarnemingen. Geen claim van afgeronde PV-optimalisatie of live-vrijgave.

### 2026-09-08 — ADR-037.8 expliciet geaccepteerd

- De gebruiker heeft het voorgelegde besluit expliciet bevestigd. [ADR-037.8](../../architecture/ADR-037.8-pv-comparison-period-and-missing-observations.md) is nu **ACCEPTED en bevroren**. Alleen status, besluitkop en acceptatietoelichting zijn aangepast; de voorgelegde gedragsregels zijn inhoudelijk ongewijzigd.
- Leidende afspraken: vaste vergelijkingsreferentie per hoofdopdracht; cumulatieve vergelijking binnen de lokale leveringsdag tot het laatste gesloten volledige forecastinterval; bij late eerste vastlegging een expliciet later begin met vooraf bekende referentie; volledige dekking vereist; geen herhaalde trigger door uitsluitend polltijd, herstart of eigen routecorrectie. De fysieke toekomstsimulatie blijft actuele LOWER/CENTRAL middelen en een zelfstandig doeltekort hoeft niet op PV-vergelijkingsbewijs te wachten.
- De open periode-/meetgatkeuzes uit ADR-037.5/037.6 zijn hiermee voor deze uitwerking gesloten. Hiervoor is geen nieuwe bevestiging nodig bij implementatie volgens dit besluit. Andere nog open onderwerpen worden niet stilzwijgend geaccepteerd.
- Basispublicatie van het voorstel: `564484e5284134134669c42762b32170a22ff513`, tree `5c52d8e151493f53deaf83750f7791aefbcfe6fc`; branch `implement/first-daily-charge-cycle`. Alleen documentatie gewijzigd; `git diff --check` geslaagd. Geen productiecode, versie-bump, merge, deployment of nieuwe live-verificatie.
- Eerstvolgende implementatiestap: de vaste PV-referentie bij eerste hoofdplanbinding bewaren, de exacte cumulatieve dekking en inhoudelijke bewijsidentiteit herstellen, en daarna gerichte boven-CENTRAL-optimalisatie van toekomstig netladen aansluiten op de bestaande hoofdopdrachtketen. Acceptatie van deze ADR betekent niet dat dit gedrag al geïmplementeerd is.

### 2026-09-08 — vaste PV-referentie en gerichte vermindering van netladen

- Basis dev.243, branch `implement/first-daily-charge-cycle`; vorige publicatie `b752a774c735132d85b0c8ed0b456c55ab09199a`, tree `0091e2fc8e3b5a71767fc0b63b5e21dc5dff7b37`. De gebruiker gaf expliciet opdracht verder te gaan na acceptatie van ADR-037.8. Status van deze stap: **IMPLEMENTED**, lokaal geverifieerd. Geen versie-bump, merge, deployment of vendorcommando.
- De eerste hoofdplanbinding bewaart atomair een eigen `DailyPVComparisonBasis`: opdrachtidentiteit, originele input, opnametijd, lokale leveringsdag, volledige vooraf bekende intervallen en oorspronkelijke LOWER/CENTRAL-bronreferenties. De referentie blijft onveranderd bij tekortcorrectie, boven-CENTRAL-revisie en herstart. Oude reeds gebonden opdrachten krijgen geen achteraf verzonnen oorspronkelijke referentie. De fysieke toekomstplanning blijft de actuele LOWER/CENTRAL middelen.
- Vergelijking telt uitsluitend de volledige gesloten intervallen vanaf het vaste begin. Ontbrekende of anders begrensde ACTUAL-intervallen leveren geen totaalschatting en geen PV-trigger. Cumulatieve grenzen zijn exact <= LOWER en > CENTRAL; gelijk aan CENTRAL is geen overschrijding. De inhoudelijke bewijsidentiteit gebruikt UTC-genormaliseerde grenzen, bronidentiteiten en energie, geen polltijd of routenummer. Zomer-/wintertijd en JSON-herstel veranderen die identiteit niet.
- Volledige nieuwe vergelijking wordt duurzaam als beoordeeld vastgelegd, ook wanneer geen routewijziging nuttig is. Bij een geslaagde revisie staan nieuw plan, opdrachtrevisie, actieve verwijzing, historie en verwerkt PV-bewijs in dezelfde atomaire schrijfoperatie. Een herhaalde poll, eigen revisie of herstart laat dezelfde evidence niet opnieuw de prijzen doorzoeken. Gewijzigde werkelijke brongegevens en gewijzigde toekomstige LOWER/CENTRAL zitten expliciet in de live inputsignatuur.
- `IndependentDailyReferenceAdapter` bewijst vóór vensterdiscovery of één toekomstig eigen netlaadinterval door NOM kan worden vervangen terwijl alle open gebonden hoofddoelen haalbaar blijven. Alleen complete boven-CENTRAL-evidence met zo'n fysiek voordeel maakt een `DailyMainPVSurplusTrigger`. Daarna volgen uitsluitend de bestaande discovery, Candidate/outcomes, Evaluation en Plan Builder. De kandidaat moet minder resterende eigen netlaadenergie vragen en alle andere doelen respecteren. Geen nieuwe financiële maat, marge, procentgrens, forecastopschaling of tweede planner.
- De Store controleert opnieuw de actuele opdracht-/revisie-/snapshot-/actieve-planidentiteit, oorspronkelijke PV-referentie, niet eerder verwerkte evidence en het werkelijke resterende netlaadbudget van het opgeslagen plan. Ontbrekend expliciet laadvermogen en een kandidaat zonder vermindering worden geweigerd. Meer SOC zonder nieuw geldig PV-bewijs geeft geen PV-revisie. Een zelfstandige doeltekorttrigger behoudt voorrang en blijft onafhankelijk van ontbrekende vergelijkingsgegevens.
- Onleesbare optionele PV-referentie blokkeert de bestaande haalbare hoofdroute niet. Ook een mislukte optionele beoordeling of opslag laat die route behouden; bij een schrijffout wordt evidence niet ten onrechte als verwerkt aangemerkt. Ontbrekende noodzakelijke planningsgegevens en onhaalbare doelcorrecties behouden de bestaande bewaakte NOM-terugval.
- Verse verificatie: **152 passed in 86,23 s** voor de nieuwe vergelijking- en PV-routeketentests plus dagelijkse tekortcorrectie, twee leveringsdagen, actieve pipeline, vensterontdekking, planherstel, live-inputherstel, levenscyclus, canonieke MEP-pipeline en uitvoeringsruntime. Daarna één aanvullende live-signatuurtest voor gecorrigeerde ACTUAL-bronnen en gewijzigde LOWER bij gelijkblijvende CENTRAL: geslaagd. Ruff, mypy op acht gewijzigde productiemodules en `git diff --check`: geslaagd. Tests gebruiken synthetische opeenvolgende snapshots en echte lokale opslag, geen actieve batterij.
- Concrete geteste gevallen: minder netladen met behoud van hoofdidentiteit; herstart zonder herbeoordeling of prijszoektocht; meetgat en later aanvullen; boven CENTRAL zonder verwijderbaar laadinterval; hoger SOC na reeds verwerkte evidence; corrupte optionele referentie; mislukte beoordelingsopslag; behoud van eerste referentie na PV-tekortcorrectie; exacte grenswaarden, late eerste binding en 23-/25-uurs dagen.
- CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets. De bestaande HA-meetintegratie gebruikt constante toestand tussen waarnemingen; deze stap verzint geen nieuwe staleness-timeout en bewijst niet dat elke bronstoring in HA-historie zichtbaar is. Aanvoer van volledige ACTUAL-intervallen en broncorrecties via de bestaande historie/cache vereist nog HA-replay/live-bewijs. Ook eerdere grenzen van 100%-voltooiingsbewijs bij onveranderde/vertraagde SOC-metingen blijven open.
- Vervolg: reserve-/overbruggingsoptimalisatie na een voltooid dagdoel, eventuele gezamenlijke correctie van meerdere onhaalbare hoofddoelen, en de genoemde HA-ketenvalidatie. Op/onder LOWER wordt de vergelijking vastgelegd; zonder zelfstandig doeltekort is in deze stap geen aanvullende laadroute ingevoerd. Geen claim dat de hele nieuwe MEP of live-vrijgave gereed is.

### 2026-09-08 — overbrugging onderzocht; voorstel ADR-037.9

- De gebruiker bevestigde verder werken aan reserve-/overbruggingslogica na voltooid dagdoel. Basis dev.243, branch `implement/first-daily-charge-cycle`, lokale HEAD `187f68f`; vorige publicatie `42307ee22ae95a7f91b121edce17ad0ac7129d6f`, tree `e4d3fdabb1da1a450e38035cedfbdde500182be4`.
- Relevante geaccepteerde contracten gelezen: ADR-037, ADR-037.1, .3/.4/.5 en .7. ADR-037.1 benoemt tijdelijk ontbreken van een volgende geplande sessie als expliciet te specificeren vóór implementatie. ADR-037.7 lost publicatieherstel op, maar geeft hiervoor geen fictief laadtijdstip. Geen eigen horizondeadline of preventieve laadregel in productie ingevoerd.
- Code-inspectie: `IndependentDailyIntentSimulator._simulate_timeline` begrenst beschikbare batterijuitvoer op energie boven minimumreserve en maximaal ontlaadvermogen; resterende huisvraag wordt `grid_to_household_wh`. Alleen SOC < minimum testen zou geen tekort ontdekken. Alle netimport als energietekort behandelen zou vermogensbeperking, bewuste netvoeding en energiegebrek verwarren.
- ADR-037.9 is als **PROPOSED** uitgewerkt. De wezenlijke nog te bevestigen keuze: zolang een volgende hoofdlaadsessie ontbreekt, geldige bestaande uitvoering behouden en onzekerheid tonen; geen verzonnen laadmoment en geen preventief laden voor zo'n fictief eindpunt. Noodzakelijk huisverbruik mag uit het net komen. Bij ontbrekende noodzakelijke gegevens/einde geldig plan blijft de bewaakte NOM-terugval gelden. Dit kan vooraf onbekende economische kansen missen en wordt niet als bewezen optimum voorgesteld.
- Het voorstel concretiseert daarnaast aansluiting op een werkelijk opgeslagen volgende hoofdroute, energie- versus vermogensgebrek, volledige financiële vergelijking van voorladen en directe netvoeding, behoud van aanvullingen over polls/restart en uitsluiting van voltooiing van een hoofdopdracht door overbrugging. Geen EUR/kWh-opgeslagen gebruiken voor directe netvoeding met nul opgeslagen energie.
- Alleen voorstel en log gewijzigd. Productiecode ongewijzigd; geen nieuwe tests of live-claims voor documentatie. `git diff --check` uitgevoerd vóór commit. Geen versie-bump, merge, deployment of vendorcommando. De code-work-skill vereist stoppen voordat een verborgen gedragskeuze een bindend open ADR-punt vervangt. Daarom eerst dit concrete voorstel ter bevestiging, daarna implementeren; het eerdere akkoord op verder werken geldt niet als een reeds gekozen antwoord op deze nog open grens.


### 2026-09-08 — ADR-037.9 geaccepteerd en bevroren

- De gebruiker bevestigde het voorgelegde voorstel expliciet. ADR-037.9 is nu **ACCEPTED en bevroren**. Status, besluitkop en acceptatietoelichting aangepast; de voorgelegde gedragsregels zijn inhoudelijk behouden.
- Zonder bekende volgende hoofdlaadsessie blijft de geldige uitvoering behouden, wordt geen fictief eindpunt of preventieve laadopdracht daarvoor gemaakt en kan noodzakelijk huisverbruik uit het net komen. Zodra de volgende hoofdroute bekend is, beoordeelt MEP de overbrugging naar die route. Ontbrekende noodzakelijke gegevens of een verlopen uitvoeringsplan houden de bestaande bewaakte NOM-terugval.
- Deze open grens uit ADR-037.1 is hiermee besloten; implementatie conform ADR-037.9 vereist geen herhaalde bevestiging. Aanvullingen blijven gescheiden van de bevoegdheid om een hoofdopdracht te voltooien.
- Basispublicatie `1b3eccc72daef4a6e0382c9e695a6dfbe7e20806`, tree `0911fb284b5c6b71998211ffa69dfb3cde74e3a1`, branch `implement/first-daily-charge-cycle`, basis dev.243. Alleen documentatie gewijzigd en `git diff --check` uitgevoerd. Geen nieuwe tests nodig voor deze statuswijziging; geen productie-, CI- of live-verificatie geclaimd.
- Eerstvolgende implementatiestap: tekortbewijs dat energiegebrek van vermogensbegrenzing onderscheidt, daarna aanvullende kandidaten en directe netvoeding via dezelfde Evaluation/Plan Builder vergelijken en duurzaam behouden zonder hoofdopdrachten te heropenen.

### 2026-09-08 — reservebewaking en aanvullende overbrugging geïmplementeerd

- Gebruikersopdracht: volgende implementatiestap na de expliciete acceptatie van ADR-037.9. Basis dev.243, branch `implement/first-daily-charge-cycle`, lokale basis `38884f0`; vorige publicatie `90bd09feb70cd4abc577fd7ec6305f5c681a2588`, tree `9b78130024ee3ac818f17b071399e5f1b6f2c13d`. Status **IMPLEMENTED**, lokaal geverifieerd. Geen versie-bump, merge, deployment of echt vendorcommando.
- De bestaande adapter beoordeelt na een bewezen voltooid dagdoel de energie tot de eerste toekomstige open hoofdlaadsessie die werkelijk in het actieve plan staat. Een lopende open hoofdlaadsessie blijft onder de bestaande doelhaalbaarheidscontrole vallen. De laatst voltooide dagopdracht per scope blijft bij herstel als bewijs beschikbaar, ook over middernacht. Er wordt geen actieve route uit die datum afgeleid; de expliciete actieve verwijzing blijft leidend.
- `DailyBridgeAssessment`/`DailyBridgeTrigger` bevatten toestand, volgende hoofdreferentie, eindpunt, intervaltekorten en actuele route-/snapshot-/revisie-identiteit. `energy_deficits` gebruikt de bestaande fysieke midpointprojectie. SOC wordt niet onder de reserve gesimuleerd: het tekort is het deel van de huisvraag binnen de ontlaadvermogensgrens dat de beschikbare batterijenergie niet kan leveren. Alleen vermogensbegrensde netimport, exact 10% met voldoende PV en bewuste netvoeding tijdens laden/standby zijn geen onbehandeld energiegebrek.
- Zonder volgende hoofdlaadsessie blijft de geldige uitvoering behouden. De bekende resterende energieprojectie is zichtbaar met status `next_session_unknown`, zonder fictief volgend laadmoment of extra laadopdracht daarvoor. Bij ontbrekende noodzakelijke data of geen geldig uitvoeringsplan blijft de bewaakte NOM-terugval gelden.
- Pas bij een nieuw energietekort genereert de bestaande adapter aanvullende routes: behouden uitvoering, PV-opvang in de vrije overbruggingsperiode, individuele netlaad-/standby-intervallen, directe netvoeding gedurende aaneengesloten gelijke gepubliceerde prijzen of de vrije periode, en minimale voldoende aaneengesloten laadreeksen vanaf uitvoerbare starts. Fysieke simulatie behoudt alle andere hoofdsegmenten en toetst alle open 100%-doelen. Dit is een begrensde set betekenisvolle routes, geen bewijs van een globaal optimum over iedere combinatie van schakelmomenten. Geen nieuwe procent-/prijsgrens, nieuw willekeurig reservepercentage of aparte planner.
- `DailyMainChargeWindowSet.purpose` maakt de vergelijking expliciet: hoofdlaadvensters behouden EUR/kWh-opgeslagen; overbrugging vergelijkt volledige huishoudelijke cash-uitkomsten in EUR over dezelfde resterende horizon, met de bestaande gebruikersstrategie, verliezen, PV-gebruik en exportconsequenties. Direct netverbruik wordt niet gedeeld door nul opgeslagen laadenergie. De bestaande Candidate/outcomes, EvaluationEngine en ExecutionPlanBuilder blijven de enige selectie- en conversieketen.
- De aanvulling wordt een uitvoeringsversie onder de behouden volgende hoofdopdracht met reden RESERVE. De Store vereist exact dezelfde oorspronkelijke hoofdsegmenttijden, primitives, vermogen, SOC-grenzen en bronbeleid. Andere hoofdopdrachten houden hun gevalideerde oorsprongsreferenties. Aanvullende segmenten dragen een eigen bron-/uitvoeringsidentiteit en doel `bridge:<opdracht>` maar geen `main_assignment_id`; zij kunnen dus geen dagdoel afvinken. Eerder bewezen voltooiing blijft ongewijzigd.
- De gekozen resterende netondersteuning wordt als `DailyBridgeState` in dezelfde bestaande atomaire Store-operatie vastgelegd als planversie, actieve verwijzing, opdrachtrevisie en historie. Volgende polls vergelijken de resterende intervaltekorten met die vastgelegde dekking. Geaccepteerde directe netvoeding veroorzaakt geen nieuwe prijszoektocht door dezelfde voorspelling, voortschrijdende tijd of restart. Aantoonbaar extra energiebehoefte kan opnieuw selecteren. Corrupte opgeslagen dekking blokkeert herstel expliciet; een schrijffout activeert geen halve route en wist het vorige plan niet.
- Live inputsignatuur bevat de herstelde overbrugging en de inhoudelijke huisverbruiksverwachting. Gewijzigde vraag of verdwenen noodzakelijke forecast wordt ook bij gelijkblijvende SOC herkend. De bestaande Evaluation-kaart projecteert passief status, volgend eindpunt, trigger en intervaltekorten; geen extra dashboard/plannerpad of beslissing in de projectie.
- Verse lokale verificatie: **175 passed in 136,37 s** voor overbrugging, dagelijkse PV-evidence/optimalisatie, hoofdselectie, tekortcorrectie, twee dagen, actieve pipeline, vensterontdekking, herstel, live-input, opdrachtlevenscyclus en bestaande canonieke planning/uitvoering. Daarna de definitieve overbruggingsset inclusief aanvullende directe-netvensters, strengere opslagcontrole, klokdispatch en verliesvergelijking: **13 passed in 25,53 s**. Passieve Evaluation-kaart met hersteltest afzonderlijk **1 passed in 6,09 s**. Extra live-signatuurtest plus bestaande dagelijkse inputtests: **16 passed in 2,21 s**. Deze sets overlappen; aantallen niet optellen. Ruff op alle gewijzigde productie-/testmodules, mypy op alle negen gewijzigde productiemodules en `git diff --check`: geslaagd.
- Geteste gedragsgrenzen: direct netverbruik wint bij dure voorlading; nieuwe goedkope uren maken aanvullende lading mogelijk zonder hoofdvenster te verplaatsen; 0,49 EUR/kWh voorladen met 0,9 laad- en ontlaadefficiëntie verliest van 0,50 EUR/kWh directe voeding; genoeg SOC zoekt geen nieuwe prijsvensters; PV dekt huis bij 10%; vermogenspiek is niet automatisch energiegebrek; extra huisvraag maakt nieuw tekortbewijs; onbekende vervolgsessie heeft geen fictieve deadline; restart bewaart gekozen directe netvoeding; corrupte opslag en schrijfuitval; brug-100% vinkt geen hoofdopdracht af; bestaande klokdispatch behoudt exact plan-ID, segment-ID en 2400 W.
- Testhulpmiddelen waren in deze runtime niet aanwezig en zijn via de bestaande `.[dev]`-afhankelijkheden geïnstalleerd; geen projectafhankelijkheden of lockfiles aangepast. Tests gebruiken opeenvolgende synthetische snapshots, echte lokale opslag en een testdispatcher. CI_VERIFIED: niet vastgesteld. LIVE_VERIFIED: niets.
- Nog open: verificatie via werkelijke HA-historie, meetvertragingen en modusbevestiging; de eerder vastgelegde grenzen van 100%-bewijs blijven bestaan. Ook gezamenlijke correctie van meerdere onhaalbare hoofdopdrachten en de afzonderlijke marktroute zijn niet door deze stap voltooid. Deze wijziging is geen live-vrijgave van de volledige nieuwe MEP.

### 2026-09-08 — HA-keten gecontroleerd; twee herstelpunten vóór live-vrijgave

- Gebruiker bevestigde de aangekondigde HA-ketenvalidatie. Getoetst: lokale `f63d78e`, publicatie `c1cb768d646e3fd6571d1d1341f1e1ed00702aac`, tree `aae826f42b26e266098866876cb4c3cb6ff5caac`; ontwikkelbranch `implement/first-daily-charge-cycle`, basis dev.243.
- Uitkomst vastgelegd in `HA_CHAIN_VERIFICATION_2026-09-08.md`: **geen live-vrijgave**. Specificatieverificatie vindt een probleem met vol-bij-hoofdstart; bronherstelverificatie vindt een cacheprobleem. Historische HA-reconstructie blijft gedeeltelijk wegens ontbrekende originele input-/capabilitysnapshots en nieuwe opdrachtregistraties. Geen historische uitvoering van de nieuwe planner verzonnen.
- Hoog: 100% op hoofdstart wordt niet afgevinkt als de eerste modusbevestiging één seconde later komt en HA de meettijd niet wijzigt. Beide lokale klokruntime-aanroepen leveren `already_active`, bij +1 en +60 seconden, maar geen voltooiing. Het aangeleverde archief toont 18 dev.243-polls op 100% met slechts twee unieke SOC-meettijden; maximale leeftijd binnen die subset ruim twee uur. Dat patroon is dus werkelijk aanwezig, zonder daarmee te beweren dat de huidige code toen draaide.
- Middel: de bestaande PV-historiecache bewaart ook een tijdelijke onbeschikbaarheid. Dezelfde periode na bronherstel doet geen nieuwe aanvraag en houdt nul ACTUAL-intervallen; met een nieuwe cache ontstaat wel één ACTUAL-interval. Een veranderend tijdvak kan later verversen. Geen bewijs dat deze fout de specifieke historische avond veroorzaakte; wel een reproduceerbare tekortkoming voor het nieuwe herstelcontract.
- Verse bestaande tests: **23 passed in 19,15 s** voor live-PV-koppeling, PV-integratie en dagelijkse actieve pipeline. De bestaande tests dekken deze twee reproducties niet: SOC-test maakt de meettijd nieuw, cachetest toetst hergebruik van geldige historie. Groen is hier onvoldoende voor een live-oordeel.
- Alleen verificatierapport en log gewijzigd; geen productie- of testcode aangepast onder deze verificatiestap. Geen HA-toegang of echte batterijcommando's gebruikt. Rapport en log worden conform de bestaande sessieafspraak vastgelegd op de ontwikkelbranch; `git diff --check` uitgevoerd. Geen versie-bump, merge of deployment.
- Eerstvolgend werk: de twee concrete bewijsovergangen herstellen binnen ADR-037.5/.8, zonder verse meettijd te faken of plannerregels te wijzigen, en opnieuw gericht toetsen. Daarna pas een nieuwe beoordeling van live-gereedheid. CI_VERIFIED en LIVE_VERIFIED zijn niet vastgesteld.

### 2026-09-08 — HA-voltooiingsbewijs en tijdelijk ontbrekende PV-historie hersteld

- De gebruiker gaf expliciet akkoord op herstel van de twee bevindingen uit `HA_CHAIN_VERIFICATION_2026-09-08.md`. Basis dev.243, ontwikkelbranch `implement/first-daily-charge-cycle`; lokale basis `4ae093d`, vorige publicatie `3f1614f8314a9bec099940db519ea0b25272cc0f`, tree `74d60d6c94db35ebd7a7b321334118cb07e2021d`. Status **IMPLEMENTED**, lokaal geverifieerd. Geen versie-bump, merge, deployment of batterijcommando.
- Oorzaak voltooiing: de eerste modusbevestiging ligt vaak na de tijd die HA bij een onveranderde SOC bewaart. Een vergelijking met alleen `measured_at >= confirmed_since` sluit daardoor geldige 100%-toestand bij hoofdstart uit.
- De succesvolle HA-SOC-reader legt nu apart `state_read_at` vast. `last_updated` blijft de oorspronkelijke meet-/updatetijd; `last_changed` wordt `state_valid_since`. Alleen beschikbare geldige SOC-invoer met beide bewijsvelden krijgt die uitbreiding. De huidige opslagtoestand valideert volgorde en tijdzone. Oudere snapshots zonder velden blijven bruikbaar, maar krijgen geen fictief actueel leesbewijs.
- Runtime en bestaande Store erkennen dit bewijs uitsluitend bij 100%, actuele bevestigde toegestane uitvoering in een echt hoofdsegment, leestijd binnen het segment en een HA-toestand die al vanaf uiterlijk de oorspronkelijke hoofdstart gold. Ook bij behouden uitvoeringsreferenties wordt de oorspronkelijke eigenaar/start gebruikt, niet een later afgeknipt segment. Normale verse telemetrie houdt de bestaande afhandeling. Brugsegmenten, handmatige/technische blokkades, toekomstige leestijden, een alleen oude meting, lezen vóór hoofdstart en een toestand die pas na hoofdstart veranderde geven geen nieuwe voltooiingsbevoegdheid.
- `DailyChargeAssignment.observe_completion` registreert bij dit aanvullende bewijs de huidige leestijd als voltooiingsgebeurtenis. De oorspronkelijke `measured_at` wordt niet herschreven of doorgegeven als een gefingeerde nieuwe meting. De opgeslagen voltooiingsevidence bevat oorspronkelijke meettijd, leestijd en geldigheidsbegin. De incidenthistorie projecteert de nieuwe leestijd wanneer aanwezig; oudere records zonder bewijs behouden hun vorm.
- Oorzaak PV-herstel: ook een mislukte of onvolledige historieaanvraag werd onder dezelfde entiteit-/periode-sleutel gecachet. De live-PV-koppeling cachet nu alleen een beschikbaar foutloos resultaat met alle gevraagde intervallen. Een tijdelijke fout of ontbrekende anker-/intervalhistorie wordt bij de volgende gewone poll opnieuw opgehaald. Na geslaagd herstel werkt de bestaande cache weer. Geen nieuwe timer, extra pollingpad, nulinvulling, forecastcorrectie of plannerregel.
- Verse verificatie: **134 passed in 69,83 s** voor nieuwe voltooiingsreproducties, live-PV-koppeling/-integratie, dagelijkse actieve keten, herstel, twee dagen, levenscyclus, live-input, overbrugging en canonieke uitvoering, modusinput en snapshots. Na uitbreiding met exact-op-hoofdstart en diagnostiek: **31 passed in 22,65 s** voor `test_daily_ha_completion_recovery.py`, `test_v2_planning_incident_history.py`, `test_v2_live_pv_actual_coupling.py`. Bestaande storage/PV-input en snapshotassemblage: **4 passed in 0,17 s**. Laatste gerichte readercontrole na beperking tot SOC-bronnen: **1 passed in 0,63 s**. Sets overlappen; aantallen niet optellen. Ruff en mypy op zeven gewijzigde productiemodules geslaagd; `git diff --check` geslaagd.
- Tests tonen: exact 100% op of vóór hoofdstart met ongewijzigde meettijd; herstart; onveranderd gemeten tijdstip en opgeslagen leestijd; ontbreken van bewijs; lezen vóór start; lezen in de toekomst; 100% pas ontstaan na start; handmatige blokkade; tijdelijk onbeschikbare of lege historie; herstel zonder cache-reset; hergebruik na herstel. Bestaande tests bewaken tevens brug-100%, behoud van hoofdopdrachten en uitvoeringsguards.
- Het historische verificatierapport is aangevuld met deze herstelstatus. Nog geen CI_VERIFIED of LIVE_VERIFIED: er is geen nieuwe ontwikkelversie naar HA uitgerold. Reeds volledig geldige maar later gecorrigeerde historie wordt niet door deze beperkte fout-herstelwijziging onmiddellijk herlezen; bestaande tijdvakvernieuwing blijft daarvoor relevant. Een tijdens offline/onbevestigde uitvoering pas ná hoofdstart ontstane 100%-toestand is evenmin stilzwijgend tot vol-bij-start-bewijs verklaard. De eerder benoemde grenzen van volledige HA-reconstructie blijven expliciet.

### 2026-09-08 — herbeoordeling wijst gezamenlijke tekortcorrectie aan als volgende stap

- Gebruiker vroeg de volgende stap. Uitgevoerd: de eerder aangekondigde herbeoordeling van live-gereedheid na de twee HA-herstelpunten. Basis dev.243, branch `implement/first-daily-charge-cycle`, lokaal `fdf854d`, gepubliceerd `7f0bde0adc2c245541120db4be9ba59f942f9fba`, tree `7fcfd1c20e8fd7e97b51f286534113824b62ac9f`.
- Verse gerichte regressie: **39 passed in 38,88 s**, exit 0, voor HA-voltooiing, PV-historieherstel, hoofdtekortoptimalisatie en tweedaags behoud.
- Tijdelijke reproductie via bestaande tweedaagse fixture en echte lokale Store: beide hoofdopdrachten gebonden, tweede plan actief; volgende snapshot SOC 10%, PV nul. Twee tekorttriggers; afzonderlijke vensterontdekking voor beide dagen geeft nul vensters met `retained_main_goal_requires_explicit_optimisation`. Geen bewijs dat een gezamenlijke oplossing in deze specifieke fixture fysiek haalbaar is; wel directe bevestiging dat de huidige afzonderlijke herstelroute geen voortgang maakt.
- Huidige positie: hoofdcyclus, enkelvoudige tekortcorrectie, PV-bewijs, overbrugging en HA-herstel zijn IMPLEMENTED; gezamenlijke revisie van meerdere getroffen hoofdopdrachten ontbreekt. Pipeline kiest één tekorttrigger en verlangt haalbaarheid van de andere ongewijzigde hoofdopdrachten. Het rapport `HA_CHAIN_VERIFICATION_2026-09-08.md` bevat mechanisme, bewijskracht en beperkingen.
- Exacte volgende actie: gezamenlijke tekortcorrectie ontwerpen en implementeren binnen bestaande Candidate/Evaluation/Plan Builder en atomaire Store, met behoud van alle dagidentiteiten, onaangetaste segmenten en bewezen voltooiingen. Eerst een betekenisvol tweedaags scenario dat gezamenlijk fysiek haalbaar is maar via afzonderlijke revisie blokkeert. Geen nieuwe planner of impliciete routewijzigingen.
- Alleen rapport en log gewijzigd. ADR001–037 en geaccepteerde gekoppelde sessie-ADR's blijven bevroren. Geen productie-/testcodewijziging, versie-bump, merge, deployment of batterijcommando. Geen CI_VERIFIED of LIVE_VERIFIED. Lokale groene tests zijn geen bewijs van een geslaagde HA-dag.

### 2026-09-08 — toets expliciete laadopdrachtafspraken; eerdere vervolgrichting ingetrokken

- Gebruiker vroeg expliciet toetsing na verduidelijking: dagelijkse 100%-hoofdopdracht binnen leveringsdag; aparte aanvullende laadopdracht met eigen doel (eventueel 100%) en eigen afvinken; aanvullende voltooiing telt nooit voor het dagdoel. Handel blijft afzonderlijke belasting.
- Basis dev.243; branch `implement/first-daily-charge-cycle`, lokaal `2264479`, gepubliceerd `123929f32921a6768914ef63f8433b6e3ad233de`, tree `113eace98dbcf509d76a358cfc338f556f690eb5`. Toetsrapport: `CHARGE_AGREEMENT_AUDIT_2026-09-08.md`.
- Niet volledig conform: aanvullende lading heeft wel uitvoeringssegmenten en opgeslagen tekortdekking, maar geen zelfstandig behouden opdracht-ID, bindend eigen laaddoel of eigen bewezen voltooiingsregistratie. ADR-037.9 werkt dit eveneens niet expliciet uit. De controle dat overbrugging nooit het hoofd-doel voltooit is aanwezig, maar is geen vervanging voor eigen voltooiing.
- De interdag-haalbaarheidspoort blijft te streng: één tekorttrigger wordt geselecteerd terwijl andere open hoofdsegmenten ongewijzigd 100% moeten halen. De eerder gereproduceerde blokkade is geen bewijs dat de marktroute dit veroorzaakt.
- **De vorige aanbeveling om beide dagopdrachten gezamenlijk te wijzigen vervalt.** De gebruiker heeft die richting expliciet gecorrigeerd. De oorspronkelijke dagelijkse opdrachten en aanvullende opdrachten moeten zelfstandig hun afgesproken doel behouden; complete SOC-projectie blijft nodig. Geen nieuwe gezamenlijke planneropdracht ontwerpen.
- Verse checks: 54 passed in 54,07 s (overbrugging, tekortoptimalisatie, HA-voltooiing, daglevenscyclus); 27 passed in 20,10 s (vensterdiscovery en financiële selectie). Beide exit 0. Eigen aanvullende voltooiing ontbreekt ondanks groene tests. De specifieke overgang na het verstrijken van het goedkoopste venster is niet afzonderlijk dynamisch opnieuw bewezen.
- Huidige positie: dagelijkse hoofdcyclus IMPLEMENTED met genoemde beperkingen; aparte aanvullende levenscyclus ontbreekt; nieuwe marktroute-user-rule niet geïmplementeerd. Exacte volgende scope: afspraken volledig documenteren via gekoppelde precisering; aanvullende opdrachtidentiteit/doel/voltooiing in bestaande keten; vervolgens interdag-blokkade gericht corrigeren met fysiek haalbare regressie. Geen gezamenlijke wijziging als vooraf gekozen oplossing.
- Alleen toetsrapport en log gewijzigd en vastgelegd. Geen productie-/testcode, bevroren ADR-tekst, versie of configuratie gewijzigd. Geen CI_VERIFIED, LIVE_VERIFIED, merge, deployment of batterijcommando.

### 2026-09-08 — nieuwe aanvullende commitmentregel geaccepteerd; toetsduiding gecorrigeerd

- Gebruiker verduidelijkte dat eigen voltooiing van aanvullende laadopdrachten nieuw bedacht is en accepteerde vervolgens het voorstel voor blijvende identiteit, eigen doel/venster, tijdige dekking en afzonderlijk afvinken. Vastgelegd als ACCEPTED, bevroren ADR-037.10; implementatiestatus DECIDED.
- Correctie op voorgaande toets: ontbrekende aanvullende doel-/voltooiingsregistratie is nieuwe scope, geen eerder gemiste implementatieafspraak. Rapport voorzien van expliciete correctie met behoud van historische bevindingen. De interdag-blokkade blijft afzonderlijk bestaan. Gezamenlijke wijziging van dagopdrachten blijft ingetrokken als vervolgrichting.
- Branch `implement/first-daily-charge-cycle`, basis dev.243, voorgaande publicatie `bfc7dc45abbb0b813435316eae6bf11eaa886b46`. Geen productie-/testcode of bevroren eerdere ADR gewijzigd. Alleen nieuw ADR, index, rapportcorrectie en log; `git diff --check` uitgevoerd. Geen nieuwe gedragstests nodig voor deze documentatiestap; eerdere testresultaten zijn geen bewijs voor ADR-037.10.
- Exacte volgende actie: eigen aanvullende opdrachtlevenscyclus volgens ADR-037.10 implementeren via de bestaande keten, met expliciete doelrepresentatie en werkelijk voltooiingsbewijs; behoud na herstart en geen uitstel voorbij het verwachte tekort toetsen. Rechtstreekse netvoeding niet als fictieve SOC-laadopdracht behandelen. Interdag-blokkade blijft apart vervolgwerk.
- Geen CI_VERIFIED of LIVE_VERIFIED, versie-bump, merge, deployment of batterijcommando.

### 2026-09-08 — ADR-037.10 aanvullende laadopdracht door bestaande keten geïmplementeerd

- Expliciete opdracht: "akkoord implementeer" voor ADR-037.10. Basis dev.243; branch `implement/first-daily-charge-cycle`; vorige publicatie `19c7335bf4755f3d5ed38f7acdb23f3f851d18bc`, tree `3d160a5ecbfd113594e44cd8e95889f3520ab970`. Status IMPLEMENTED en lokaal geverifieerd; geen versie-bump, merge, deployment of batterijcommando.
- Nieuwe canonieke `SupplementalChargeAssignment` bevat eigen identiteit, verwijzing naar volgende hoofdopdracht, scope, expliciet SOC-doel, uitvoeringsvenster, tijdstip waarop de energie uiterlijk nodig is, uitvoeringsplan/segmentreferenties en apart voltooiingsbewijs. Dit is nieuwe scope uit ADR-037.10, geen correctie van een eerder vergeten afspraak.
- Candidate-verantwoordelijkheid: geselecteerde aanvullende lading krijgt als doel de geprojecteerde opgeslagen batterijenergie aan het einde van de lading gedeeld door capaciteit. Aaneengesloten laadintervallen met stijgende energie kunnen zowel PV/NOM als netladen bevatten. Rechtstreekse netvoeding, standby en trajecten zonder energietoename krijgen geen fictief laaddoel. De uiterste benodigde tijd komt uit het eerste verwachte tekort na de lading, of de bekende volgende hoofdstart als eerder tekort ontbreekt. Geen nieuwe vaste kloktijd, SOC-marge of prijsdrempel.
- Iedere nieuwe kandidaat behoudt nog open aanvullende doelen met hun identiteit, target en uiterste benodigde tijd. Het uitvoeringsvenster mag veranderen, maar de fysieke projectie moet het bestaande doel tijdig halen. De window-contractvalidatie controleert dat bewijs; hoofd- en aanvullende segmenten mogen niet dezelfde doelhouder krijgen. Niet haalbare aanvullende doelen geven geen geldige kandidaat en kunnen niet stilzwijgend worden weggelaten. Dit introduceert geen gezamenlijke wijziging van dagopdrachten.
- Eigen doelreferenties lopen via bestaande PathSegment-purpose → ongewijzigde Plan Builder → bestaande Store. Store controleert volledige afzonderlijke laadsegmentdekking, bewaart revisiehistorie en schrijft opdracht, bestaande dagrevisie, plan en actieve verwijzing in dezelfde atomaire operatie. Een schrijffout laat de eerdere route en opdrachtregistratie intact. Herladen valideert de oorspronkelijke uitvoeringsplan-/segmentreferenties, ook via bestaande planhistorie; corrupte binding blokkeert herstel expliciet.
- De bestaande overbruggingsmonitor toetst nu ook of het vastgelegde aanvullende target nog in zijn lopende route haalbaar is. Dat mag selectie starten, ook wanneer de fysieke simulator huisverbruik al door netimport opvangt. Zo kan bewust toegestane netvoeding het nog open laaddoel niet verbergen. De Store vereist daarbij de actuele open aanvullende eigenaar. Nieuwe prijzen alleen veroorzaken geen selectie; targets worden bij herselectie niet verlaagd of doorgeschoven voorbij de benodigde tijd.
- Dezelfde bewaakte runtime die modusfeedback en SOC aan het dagdoel koppelt registreert nu afzonderlijke aanvullende voltooiing. Bevestigde toegestane uitvoering, werkelijk target-SOC of hoger, de juiste actieve plan-/segmentreferentie en passende meettijd zijn vereist. Het bestaande aparte HA-leesbewijs kan een al bij aanvullende start geldige toestand aantonen; de oorspronkelijke meettijd wordt niet vervalst. Alleen dispatch, een oude meting zonder bewijs, verkeerde segmenten, forecast of handmatige blokkade vinken niet af. Ook aanvullende 100% vinkt nooit zelfstandig het dagdoel af; latere ontlading heropent de voltooide aanvullende opdracht niet.
- Dagelijkse input herstelt de aanvullende opdrachten en neemt hun inhoud op in de inputsignatuur. De bestaande Evaluation-kaart toont passief doel, venster, benodigde tijd, uitvoering en voltooiingsbewijs uit die herstelde context. Nieuwe Store-uitkomsten zijn bij volgende input zichtbaar. Na verstreken benodigde tijd blijft een onbewezen opdracht als zodanig zichtbaar en opgeslagen; geen automatische voltooiing of fictieve uitvoering in het verleden. Ze blokkeert niet onbeperkt nieuwe leveringsdagen. Oude opslag zonder aanvullende registraties blijft leesbaar; er wordt geen historisch doel verzonnen voor oudere bridge-segmenten.
- Regressiebewijs: eerst faalde de nieuwe ketentest op ontbrekende aanvullende Store-interface. Na implementatie slaagde zij met echte lokale opslag en restart. De uitgebreide nieuwe set toetst eigen doel/identiteit, target onder 100% en waarneming op 100%, afzonderlijke voltooiing, geen heropening, verkeerd/oud bewijs, directe netvoeding, nieuwe prijzen zonder discovery, bestaande klokruntime en handmatige blokkade, corrupte binding, herziene kandidaten én volledige nieuwe planbinding met hetzelfde doel, plus schrijfuitval.
- Verse bredere controles: **63 passed in 87,22 s** voor nieuwe aanvullende tests, overbrugging, hoofdtekortoptimalisatie, twee dagen, actieve keten, PV-optimalisatie en dagelijkse input; **37 passed in 25,04 s** voor hoofdvensters, selectie en HA-voltooiing. Tijdens die verificatie bleek een compatibiliteitsregressie bij losse historische snapshots zonder dagelijkse context; opgelost door daar geen nieuwe aanvullende context te veronderstellen. Daarna genoemde 37 tests groen. Nieuwe gerichte set met volledige revisie: **11 passed in 35,72 s**. Sets overlappen, niet optellen. Typecontrole op alle elf gewijzigde productiemodules en Ruff geslaagd. Definitieve aanvullende/bridge-set na behoud van één hybride laadgroep wordt hieronder apart geregistreerd.
- DO NOT CHANGE: ADR001–037 en alle geaccepteerde gekoppelde ADR-teksten blijven bevroren. Eén Candidate/Evaluation/Plan Builder/Store/uitvoeringsketen. Geen aparte planner, timer, vendor-aansturing of tweede opslagbestand. Netaanvulling binnen een hoofdroute blijft van de hoofdopdracht; eigen aanvullende voltooiing heeft daar geen invloed op.
- Grenzen: geen CI_VERIFIED of LIVE_VERIFIED. Tests gebruiken synthetische opeenvolgende snapshots en een testdispatcher, geen werkelijke HA-uitvoering. De reeds bekende grenzen bij laat ontvangen eindmetingen na segmentovergang en onbevestigde/offline uitvoering zijn niet als opgelost geclaimd. Geen bewijs van een globaal optimum over iedere schakelcombinatie. De bekende interdag-haalbaarheidsblokkade en de afzonderlijke user-rule-marktroute zijn niet in deze wijziging aangepakt.
- Exacte volgende actie: de interdag-haalbaarheidsblokkade gericht corrigeren aan de hand van een fysiek haalbare tweedaagse regressie, met behoud van zelfstandige dagelijkse en aanvullende doelen. Geen gezamenlijke herdefinitie van dagopdrachten als oplossing. Daarna de volledige HA-keten opnieuw beoordelen vóór live-vrijgave.

- Definitieve controle op de uiteindelijke aanvullende/overbruggingsimplementatie: `python -m pytest tests/test_supplemental_charge_commitment.py tests/test_daily_bridge_pipeline.py -q`: **22 passed in 53,28 s**, exit 0. Inclusief 11 nieuwe aanvullende gevallen; aantallen overlappen met de voorgaande sets. `git diff --check` geslaagd.

### 2026-09-08 — interdag-blokkade opgelost met afzonderlijke chronologische revisies

- Gebruiker vroeg expliciet: "los de blokkade op". Basis dev.243; branch `implement/first-daily-charge-cycle`; vorige publicatie `32e0bed0cbe620f9a1af14995195c32891d7a1c5`, lokale basis `65dfeb5`, tree `2be98c4c35501ef6005812807f43aacb79bc91db`. Status IMPLEMENTED en lokaal geverifieerd; geen versie-bump, merge, deployment of batterijcommando.
- Faalbewijs vóór wijziging: nieuwe tests gebruiken de bestaande tweedaagse numerieke dev.243-fixture met expliciete testcapabilities, echte Store en beide gebonden hoofdopdrachten. Volgende snapshot: 10% SOC en geen voorspelde PV. Twee tekorttriggers; vensterontdekking voor vandaag gaf nul vensters en de actieve pipeline NOM-fallback met `retained_main_goal_requires_explicit_optimisation`. Beide nieuwe tests faalden om deze concrete reden (2 failed in 4,49 s).
- Oorzaak: correctie van vandaag vereiste dat de andere hoofdopdracht in haar ongewijzigde segmenten ook direct 100% kon halen. Daardoor kon de volgende zelfstandige optimalisatiestap nooit worden bereikt.
- De adapter laat bij een expliciete hoofdtekortrevisie nu uitsluitend de 100%-toets van een latere, reeds aantoonbaar onhaalbare hoofdroute voor deze ene selectie buiten beschouwing. Haar identiteit, doel, segmenten en complete fysieke SOC-/energie-effect blijven behouden en meegesimuleerd. Het is geen voltooiing, annulering of verborgen nieuwe route voor morgen. Een eerder doel en iedere andere reeds haalbare hoofdroute moeten nog steeds haalbaar blijven; alleen beschikbare uitvoerbare vensters voor de geselecteerde dag mogen winnen.
- Bewijs dat de latere route al tekortkomt wordt uit de bestaande `main_route_shortfalls`-monitor gehaald. Die simuleert het volledige actieve plan. Niet de kandidaatbaseline gebruiken waarin de te wijzigen eigen hoofdacties tijdelijk zijn vrijgemaakt; dat zou ten onrechte een gezonde volgende dag als al bedreigd kunnen classificeren. Herbeoordeling gebruikt dezelfde bestaande simulator en gebeurt eenmaal per relevante selectiebatch, zonder extra prijszoektocht of pollinglus.
- Zowel canonieke tekortvolgorde als selectie gebruiken expliciet leveringsdatum en scope, niet toevallige opdracht-ID-volgorde. Eén gewone pipeline-run herziet één oorspronkelijke eigenaar. De volgende normale poll herstelt de nieuwe actieve route en beoordeelt de dan resterende tekorten opnieuw. Aanvullende doelen uit ADR-037.10 behouden hun bestaande eigen toelatings-/voltooiingsregels.
- Evaluation legt de bij binnenkomst aangetroffen tekortbewijzen vast (`daily_main_input_shortfalls`). De bestaande Evaluation-kaart toont deze passief met snapshotreferentie, geprojecteerde piek, target en welke opdracht voor deze run is geselecteerd. Dit zijn inputbewijzen, geen onbewezen claim dat alle doelen na selectie al haalbaar of voltooid zijn.
- Direct positief ketenbewijs: eerste run kiest een fysiek volledige route voor vandaag en herziet alleen vandaag; morgen blijft exact gelijk. Na echte Store-herstart is alleen morgen nog ontoereikend. Tweede run herziet alleen morgen en laat de eerste revisie exact staan. Daarna geeft volledige routemonitoring geen hoofdtekort meer; beide dagdoelen blijven werkelijk onafgevinkt. Deze proef bewijst dus ook fysieke haalbaarheid van dit tweedaagse geval, wat de eerdere losse afwijzingsproef nog niet bewees. Opzettelijk omgekeerde triggeruitvoer verandert de chronologische selectie niet. Een volgende identieke poll behoudt het plan zonder vensterzoektocht en zonder Store-wijziging.
- Verse controles op de uiteindelijke productiecode: `python -m pytest tests/test_daily_independent_shortfalls.py tests/test_daily_main_horizon_retention.py tests/test_daily_main_route_optimisation.py tests/test_daily_main_active_pipeline.py tests/test_supplemental_charge_commitment.py -q`: **35 passed in 57,25 s**, exit 0. Na aanvullende assertions op passieve diagnose en stabiele vervolgpoll: nieuwe tweedaagse set **2 passed in 7,68 s**, exit 0. Sets overlappen. Ruff en mypy op vier gewijzigde productiemodules geslaagd; `git diff --check` geslaagd.
- Behoud getoetst door bestaande regressies: een nieuwe dag mag een eerder onhaalbaar doel niet verbergen; fysiek onhaalbare eigen revisie blijft expliciet onhaalbaar; plan-/oorsprongsreferenties, opgeslagen voltooiingen, schrijfuitval, aanvullende doelen en uitvoering blijven beschermd. De Store en Plan Builder zijn voor deze correctie niet gewijzigd.
- DO NOT CHANGE: ADR001–037 en geaccepteerde aanvullingen blijven bevroren. Geen gezamenlijke herdefinitie van dagopdrachten, geen nieuwe deadlines of prijs-/SOC-drempels, geen tweede planner of selectie-/uitvoeringspad. Deze regel verruimt geen fysieke of veiligheidsgrenzen.
- Geen CI_VERIFIED of LIVE_VERIFIED. Tests zijn lokale opeenvolgende snapshots, geen volledige historische HA-replay of echte batterijaansturing. Werkelijk onhaalbare actuele doelen kunnen nog steeds NOM-fallback geven; dit herstel claimt niet dat iedere fysieke situatie uitvoerbaar wordt. Marktroute-user-rule is afzonderlijk vervolgwerk.
- Exacte volgende actie: de bijgewerkte dagelijkse keten opnieuw op live-gereedheid beoordelen, inclusief HA-meettijden, uitvoeringsovergangen en actuele diagnoseweergave. Geen nieuwe plannerregels toevoegen op basis van de groene lokale tests.

### 2026-09-08 — volgende live-gereedheidstoets: afsluitend uitvoeringsbewijs ontbreekt

- Gebruiker vroeg "oke volgende stap". Uitgevoerd volgens vorige vervolgactie: gerichte read-only toets van uitvoerings-/voltooiingsovergang na aanvullende lading. Basis dev.243, branch `implement/first-daily-charge-cycle`; lokaal `737da21`, gepubliceerd `bf4a9d86175f3595c7fa58b335d93d21fb6c9320`, tree `8e354360d16b6eaef2a8357cbf1ac9ac6e5b237d`.
- Verse bestaande controles: **23 passed in 52,62 s**, exit 0, voor aanvullende commitments, HA-voltooiingsbewijs en zelfstandige tweedaagse tekortcorrectie. Geen nieuwe tests of code geschreven.
- Afzonderlijke tijdelijke reproductie met dezelfde runtime en echte lokale Store: één seconde vóór einde aanvullende lading is modus bevestigd en doel nog niet bereikt; één seconde na einde is volgende NOM-modus bevestigd, SOC-meettijd ligt exact op vorige eindgrens en SOC haalt het target, maar de aanvullende opdracht blijft open. Beide definitieve runtime-uitkomsten `already_active`, zonder technisch blokkerende reden. Eerste probe met ontbrekende mapping van volgende primitive werd geblokkeerd; vervangen door juiste mapping per actuele primitive voordat de bevinding werd getrokken.
- Oorzaak: runtime biedt voltooiingsbewijs alleen aan het huidige segment aan; aanvullende Store-ingang accepteert geen uitleestijd voorbij de oude segmentgrens. Daarmee is het eerder gedocumenteerde open punt van laat ontvangen eindmetingen nu concreet voor aanvullende lading bevestigd. Geen nieuwe laad-/prijsregel nodig. Reproductie bewijst niet dat begrensde synthetische moduswaarnemingen voldoende historische uitvoeringszekerheid geven om elke late meting automatisch af te vinken.
- Rapport `HA_CHAIN_VERIFICATION_2026-09-08.md` aangevuld met exacte waarnemingen, mechanisme, ernst en bewijslimieten. Nog geen volledige live-vrijgave, CI_VERIFIED of LIVE_VERIFIED. Geen werkelijke HA-aansturing of volledige historische replay.
- Exacte volgende actie: verwerking van afsluitend bewijs voor het vorige uitvoeringssegment uitwerken en gericht implementeren via dezelfde runtime en Store. Originele meettijd en identiteit behouden, guards handhaven, hoofd-/aanvullende voltooiing scheiden. Geen willekeurige wachttijd of tijdstempelverversing als oplossing; bij onvoldoende uitvoeringsbewijs expliciet onbewezen laten.
- Alleen rapport en log gewijzigd en vastgelegd; productie-/testcode, bevroren ADR's en versie blijven gelijk. Geen merge of deployment.

### 2026-09-08 — afsluitend meetbewijs bij laadsegmentovergang

- Opdracht: akkoord op het herstellen van de aangetoonde eindmetingsgrens. Basis lokaal `34dbd47`, remote `f2e67500ef7936d1ee76eed0948a430eef893711`, tree `8414e40a188eefcccc3aff28eb5e4e7186e19d1f`; branch `implement/first-daily-charge-cycle`.
- Bestaande uitvoeringsruntime bewaart de laatste bevestigde uitvoering tijdelijk en beoordeelt een later ontvangen eindmeting vóór de volgende segmentafhandeling. Hoofd- en aanvullende opdrachten houden hun eigen doelhouder. Meetmoment, actieve plan-/segmentbinding, scope, guards en werkelijk target-SOC blijven bepalend; ontvangsttijd wordt niet als SOC-meettijd gebruikt.
- HA-modusbewijs neemt de werkelijke optionele `last_changed` over. Nog dezelfde modus vereist passend continuïteitsbewijs; bij gewisselde modus zijn tevens passende wisseltijd en plannerprovenance vereist. Ontbrekend bewijs, handmatige blokkade, een meting na het oude einde of een herstart zonder eerdere bevestiging leveren geen fictieve voltooiing op. Geen willekeurige tolerantieperiode of nieuwe historische reconstructie.
- Store accepteert late voltooiing alleen met expliciet afsluitend bevestigingsinterval. Schrijffouten blokkeren verdere overgang met een concrete reden; dezelfde waarneming kan na herstel opnieuw worden verwerkt. Geen nieuw opslagbestand of schema.
- Als de klokruntime voltooiing vastlegt, gebruikt de bestaande livepoll een opnieuw ingelezen en voorbereide immutable input voordat de planningsketen verdergaat. Geen tweede planner of extra timer; voorkomt plannen met de zojuist achterhaalde open-doelcontext.
- Faalbewijs: nieuwe overgangstest faalde vóór implementatie op ontbrekende voltooiing. Verse bredere regressie: **58 passed in 62,05 s** voor segmentafsluiting, HA-voltooiing, actieve dagketen, aanvullende opdrachten, livepoll en moduscapabilities. Daarna toegevoegde schrijfuitvalafhandeling: definitieve gerichte set **12 passed in 26,26 s**. Sets overlappen, niet optellen. Ruff, typecontrole op vier productiemodules en `git diff --check` geslaagd.
- Grenzen: synthetische snapshots, echte lokale Store en testdispatcher; geen volledige HA-historie, CI_VERIFIED of LIVE_VERIFIED. Eerdere planbinding moet nog actief zijn; geen reconstructie van onbevestigde uitvoering na restart. Geen versie-bump, merge, deployment of batterijcommando. ADR001–037 en gekoppelde geaccepteerde ADRs ongewijzigd.
- Volgende stap: de gewijzigde uitvoeringsgrens in de volledige HA-integratie toetsen, inclusief beschikbare moduswisseltijden en provenance, voordat live-vrijgave wordt overwogen. De afzonderlijke marktroute blijft vervolgwerk.

### 2026-09-08 — vertraagde HA-modusfeedback onderscheiden van handmatige overname

- Opdracht: akkoord op de gereproduceerde uitvoeringskoppeling. Basis lokaal `7a12c5a`, remote `a744ea9dfafb85342e0f7756f7be8d0691668cc1`, tree `699b0bf226bd5defe5878b7cc3b0f0f998aaf83a`; branch `implement/first-daily-charge-cycle`, basis dev.243. Status IMPLEMENTED, lokaal getoetst.
- Faalbewijs vooraf: aanvraag NOM gevolgd door nog eenmaal de oude laadmodus werd `manual_override`; de volgende NOM-terugmelding hief dat niet op. De toenmalige 40 controles slaagden maar dekten die vertraagde terugmelding niet. Nieuwe regressies faalden eerst omdat de provenance-ingang nog geen HA-wisseltijd kon ontvangen.
- De bestaande live input geeft nu de reeds ingelezen optionele `state_changed_at` door aan provenance. Alleen bij een nog onbevestigde planner-aanvraag, dezelfde eerder waargenomen modus en een wisseltijd op of vóór de vorige waarneming blijft de aanvraag wachten. De bestaande zichtbare reden wordt `planner_application_awaiting_mode_feedback`; het bereiken van de gewenste modus bevestigt de aanvraag. Dit is geen uitvoerings- of SOC-voltooiingsbewijs.
- Een afwijkende modus, aantoonbaar nieuwe wisseltijd, wijziging na bevestiging of ontbrekend continuïteitsbewijs behoudt de conservatieve handmatige blokkade. Een bestaande override wordt nooit automatisch opgeheven. Geen fictieve meettijd, vaste wachttijd of nieuwe retryregel; bestaande runtime `awaiting_mode_feedback` blijft leidend. Zonder uiteindelijke feedback wordt geen succesvolle uitvoering verzonnen.
- De bestaande provenance-opslag bewaart de wachtreden en aanvraagidentiteit ook over herstart; geen nieuwe schema/status/opslag. Aanpassing hoort uitsluitend bij uitvoeringsfeedback en adaptergrens (ADR-016/035), niet bij Candidate, Evaluation of Plan Builder. Bevroren ADR001–037 en gekoppelde ADRs ongewijzigd.
- Nieuwe checks: herhaalde oude feedback met/zonder restart, uiteindelijke bevestiging, handmatige wijziging na bevestiging, derde modus, nieuwe wisseltijd, ontbrekend bewijs en raw HA-metadata via de echte input-attachment. Eerste brede run: 51 geslaagd, één nieuwe test had onjuiste capability-capture-lineage in de fixture. Alleen die fixture gecorrigeerd; gerichte definitieve set 6 passed in 0,40 s. Ruff geslaagd. Mypy 2.3.1 crashte intern met de gedeelde cache; met een aparte verse cache slaagde de controle op beide gewijzigde productiemodules.
- Geen CI_VERIFIED of LIVE_VERIFIED, merge, versie-bump, deployment of apparaatcommando. Volgende stap: volledige uitvoeringsvolgorde met dispatch, vertraagde terugmelding en afsluitende SOC-registratie samen toetsen; werkelijke HA-uitvoering blijft nog onbewezen.

Definitieve geïntegreerde regressie: `python -m pytest tests/test_pending_mode_feedback.py tests/test_v2_storage_mode_provenance_integration.py tests/test_v2_live_storage_mode_provenance.py tests/test_charge_segment_closure.py tests/test_v2_zendure_mode_capabilities.py tests/test_v2_live_replan_poll_cycle.py -q`: **52 passed in 28,37 s**, exit 0. `git diff --check` geslaagd.

### 2026-09-08 — gecombineerde dispatch-/feedback-/SOC-keten getoetst

- Opdracht: "akkoord voer uit" voor de gecombineerde uitvoeringscontrole. Basis lokaal `365fbff`, remote `1ebc4e2b46fd191a0f4b26836c0ec83261b8c548`, tree `505d7fe09af8f4d0d5ac1a907b4fed60c1a0a294`; branch `implement/first-daily-charge-cycle`, basis dev.243.
- Nieuwe integratietest gebruikt een door de bestaande pipeline gemaakt hoofd- of aanvullend plan, echte lokale commitment- en provenance-opslag, dezelfde CanonicalExecutionRuntime en de gewone `_poll_live_cycle`. Raw HA-modusmetadata loopt via de bestaande derivatie en attachment. Alleen de externe dispatcher is een testdouble; modusmapping is expliciete testconfiguratie. Planning na de overgang wordt aan de execute-ingang geobserveerd, niet als nieuwe kandidaatselectie uitgevoerd.
- Opeenvolging: één seconde voor het einde bevestigde oude modus met SOC onder doel; één seconde na einde oude feedback en één dispatch; volgende poll nog ongewijzigde oude modus → awaiting_mode_feedback; daarna nieuwe modus en vertraagde doelmeting met meettijd exact op het oude einde. Beide opdrachtsoorten vinken hun eigen doel af op die oorspronkelijke meettijd. Voltooiing veroorzaakt precies één extra inputcapture vóór execute. Aanvullende voltooiing verandert geen enkele hoofdopdracht.
- Negatieve gevallen: tussentijdse handmatige moduswijziging en SOC-meettijd één microseconde na het oude einde blijven onbewezen. Geen tweede dispatch. Geen productiewijziging nodig voor deze getoetste volgorde.
- Gerichte eerste run: **4 passed in 12,04 s**. Ruff en `git diff --check` geslaagd. Dit is lokale integratieverificatie, geen CI_VERIFIED of LIVE_VERIFIED. Geen merge, versie-bump, deployment of echte HA-/batterijcommando's.
- Volgende stap: releasegereedheid van de ontwikkelbranch bepalen op basis van resterende afspraken en integratiedekking; daarna pas een expliciet gekozen HA-proef. De afzonderlijke user-rule-marktroute is nog vervolgwerk. Geen plannerregels of bevroren ADRs gewijzigd.

Definitieve gecombineerde regressie: `python -m pytest tests/test_ha_charge_transition_chain.py tests/test_pending_mode_feedback.py tests/test_charge_segment_closure.py -q`: **22 passed in 34,22 s**, exit 0. Dit omvat de vier nieuwe combinatiegevallen; aantallen niet optellen.

### 2026-09-08 — ADR-019.3 en exacte handelsprijsvensters

- Opdracht: gebruiker bevestigde de vier voorgestelde open uitvoeringskeuzes en wil laadcyclus en marktroute samen live testen. Basis lokaal `930b984`, remote `fd9e545a780d52b9ac9d8a30715d72be153180ce`, tree `106824e6a00ad355980200eadf0baa4f9f5df8cd`; branch `implement/first-daily-charge-cycle`, basis dev.243.
- ADR-019.3 legt geaccepteerd vast: vóór start onvoldoende SOC → overslaan zonder stil verkleinen; tijdens uitvoering stoppen bij ondergrens en werkelijk volume registreren; vastgelegd venster behouden bij kleine prognosewijzigingen; herstelbasis mean LOWER/CENTRAL. Geen bestaande ADR gewijzigd.
- Eerste implementatieslice: immutable MarketUserRule en herleidbaar prijsbewijs, plus ongerangschikte constante-vermogensvensters uit volledige gepubliceerde leveringsdagtarieven. Percentage betreft bruikbare capaciteit. Batterijenergie, netexport en fictieve netinkoop worden met expliciete directionele efficiënties onderscheiden. Beide vensterduren volgen uit geconfigureerd vermogen. Gebruikte fracties van prijsintervallen tellen energiegewogen; verkoop gebruikt expliciete cross-interval exportprijs indien beschikbaar.
- Extrema van de glijdende prijsintegraal worden onderzocht bij begin- én eindpunten op tariefgrenzen, plus de vroegste toegestane exportstart. Goedkoopste fictieve referentie mag eerder op de leveringsdag liggen; export niet vóór earliest_export. Gelijke fictieve referentieprijzen krijgen voor traceerbaarheid de vroegste referentie, zonder laadbesluit. Exportalternatieven worden niet hier financieel geselecteerd. Dezelfde gegevens ontbreken → geen verzonnen prijs of verkleind volume.
- Geen koppeling met het actieve dagpad, Store, gebruikersdashboard of uitvoering in deze slice. De helper bewijst geen beschikbare SOC, werkelijk herstel of nettowinst. De hele marktroute is dus nog NIET GEÏMPLEMENTEERD of klaar voor de gezamenlijke liveproef. Bestaande laadplanning en uitvoering zijn niet aangepast.
- Verse gerichte tests: **12 passed in 0,19 s**. Gedekt: 2,04 kWh batterijenergie, afzonderlijke conversieverliezen en minuten, gedeeltelijk kwartier, prijs over volledige exportduur, oude fictieve referentie, geen export in verleden, 23/24/25 uur, ontbrekende prijzen, te weinig resterende tijd, ingestelde spread en ongeldige vermogens. Ruff, typecontrole op beide nieuwe productiemodules en `git diff --check` geslaagd.
- Exact vervolg: aansluiten op bestaande user-rule-configuratie; handelsopdracht met eigen identiteit in hetzelfde actieve uitvoeringsplan verwerken; beschikbare SOC en optionele complete-plan-herstelwinst toetsen; oorspronkelijke hoofd-/aanvullende opdrachtbindingen behouden; monitoren en werkelijk exportvolume registreren; gezamenlijk via bestaande Candidate/Evaluation/Plan Builder/Store/runtime testen. Geen tweede planner/uitvoeringsroute. De huidige actieve Store-pointer verwijst naar een dagopdracht; marktwijzigingen mogen daarom niet worden vermomd als een nieuw 100%-laaddoel.
- Geen CI_VERIFIED of LIVE_VERIFIED, merge, versie-bump, deployment of batterijcommando. De overeengekomen gezamenlijke liveproef blijft het einddoel.

Nog te bevestigen bij opdrachtbinding: geldt het ingestelde handelsvolume eenmaal per gepubliceerde leveringsdag, of opnieuw per kwalificerend venster? ADR-019.1–019.3 leggen het volume en prijsreferentiedag vast, maar niet de herhalingsfrequentie. Niet stilzwijgend meerdere opdrachten genereren na uitvoering/overslaan; deze keuze bepaalt deduplicatie en restartgedrag.

### 2026-09-08 — dagelijkse handelsidentiteit en duurzame volumebegrenzing

- Opdracht: gebruiker bevestigde maximaal één handelsopdracht per user rule per gepubliceerde leveringsdag; het ingestelde SOC-aandeel is het dagelijkse maximum. Vastgelegd in nieuwe ADR-019.4. Basis lokaal `37a4d9c`, remote `cbf77efe674a3857d0fe8711cb91ada9ecb43602`, tree `9765afe0203aef26c55b8a921a32f6086580a884`; branch `implement/first-daily-charge-cycle`, basis dev.243.
- `MarketDailyAssignment` geeft de handelsopdracht een eigen identiteit uit stabiele rule-ID, batterijscope en lokale leveringsdatum. Regelrevisie, prijswaarneming en procesherstart zijn geen nieuwe identiteit. De geregistreerde hoeveelheid en regelversie blijven behouden bij herhaalde registratie. Een andere timezone onder dezelfde identiteit wordt geweigerd; geen ongemerkt nieuw dagbudget door timezone-wijziging.
- De bestaande ActivePlanCommitmentStore bewaart deze registraties in hetzelfde document met dezelfde atomaire schrijfroute. Bestaande documenten zonder deze sectie blijven leesbaar. Er komt geen aparte opslag of commandoroute. Registreren reserveert alleen een dagopdracht en activeert geen uitvoering of nieuw laadplan.
- Afsluiten ondersteunt completed/skipped/stopped met expliciete uitkomsttijd en bewijsreferentie. Voor uitgevoerd volume is een gemeten exporthoeveelheid vereist; overslaan verzint geen nulmeting. Herhaling van exact hetzelfde uitkomstbewijs is idempotent; een andere uitkomst of heropening wordt geweigerd. De runtime moet dit bewijs later aanleveren: deze opslaginterface bewijst zelf geen SOC, mode, exportmeting, volledige uitvoering of herstelbaarheid.
- Verse gerichte marktset (dagidentiteit en prijsvensters): **23 passed in 0,82 s**. Brede opslagregressie met aanvullende opdrachten en actieve hoofdlaadketen: **28 passed in 34,17 s**. Sets overlappen. Ruff, mypy op beide gewijzigde/nieuwe productiemodules en `git diff --check` geslaagd. Gedekt: herstart, revisie, afgesloten/overgeslagen/gestopt, afzonderlijke dagen/regelingen, 23/25 uur, schrijfuitval, corrupte identiteit, timezone-wijziging en behoud van laadopslag.
- Status: dagelijkse identiteit/opslag IMPLEMENTED en lokaal geverifieerd. De volledige marktroute is nog niet gekoppeld aan user-rule-dashboard, kandidaatplaatsing, herstelwinst, actieve planbinding en uitvoeringsmeting. Deze wijziging activeert dus GEEN handel. Geen CI_VERIFIED of LIVE_VERIFIED, versie-bump, merge, deployment of batterijcommando.
- Exact vervolg blijft de geautoriseerde gezamenlijke marktroute: nieuwe dagelijkse handelsidentiteit via bestaande user-rule-invoer opnemen in Candidate/Evaluation; beschikbaar SOC en optionele hersteltoets beoordelen; dezelfde laadopdracht en handelsopdracht via één actief uitvoeringsplan behouden; daadwerkelijke export en stop/overslaan registreren. Geen nieuwe inhoudelijke bevestiging nodig voor de nu vastgelegde frequentie.

### 2026-09-08 — fysieke marktroutetoets en gedeeld exportvermogen

- Opdracht: voortbouwen aan koppeling van handelsopdracht, SOC-/hersteltoets en gezamenlijke uitvoering. Basis lokaal `05a748f`, remote `7de2113cabf98a442a1a7fa30a1092b92a83684c`, tree `fc9e107e706413e24cdffa0108b861e38003ef30`; branch `implement/first-daily-charge-cycle`, basis dev.243.
- Nieuwe `assess_market_route` consumeert twee volledige projecties uit dezelfde bestaande fysieke simulator. Snapshot, PV-basis, huisvraag, horizon, aanvankelijke batterijenergie, vastgelegde regelversie, volume en spreadgrens moeten overeenkomen. Export moet de volledige gevraagde hoeveelheid halen; beperkt volume door SOC of gedeeld vermogen wordt niet stilzwijgend toegelaten. Andere exportacties mogen niet worden vervangen. Minimum-SOC en gesloten dagopdrachten worden getoetst.
- Herstel uit: geen herstelprijs, 100%-herstelbewijs of nettowinstpoort toegevoegd. Dit is uitsluitend toelating volgens de handelsregel, geen vrijstelling van de bestaande laadverplichtingen. De caller blijft verantwoordelijk voor ongewijzigde overige opdrachten en hun harde grenzen.
- Herstel aan: expliciet toekomstig laadsegment met doel gelijk aan bruikbare capaciteit moet in de projectie werkelijk 100% bereiken. Zonder dat bewijs of werkelijke waarderingstarieven is de uitkomst onvoldoende bewijs. Nettowinst komt uit bestaande volledige huishoudelijke cash-settlement mét versus zonder actie, minus ingestelde slijtage per export-kWh. Verliezen en verdrongen huisdekking zijn al in de fysieke paden verwerkt; gemiste PV-export zit in de cashvergelijking. De fictieve referentieprijs wordt niet als herstelkosten geboekt. De herstelreferentie moet door de latere pipelinekoppeling aan de oorspronkelijke Store-eigenaar worden gevalideerd; de nieuwe toets activeert zelf geen plan.
- Aansluitpunt gevonden: bestaande exportduurprojectie deelde export-Wh door het hele maximale ontlaadvermogen, terwijl de simulator eerst huisvraag bedient. De dagelijkse padprojectie geeft nu haar fysieke projectie mee; exportduur gebruikt resterend vermogen na geprojecteerde batterijdekking van huisvraag. Voor 1,2 kWh export, 2400 W maximum en 600 W huisvraag is dat 40 minuten, niet 30. Bestaande legacy-aanroepen zonder deze projectie zijn niet stilzwijgend omgezet.
- Exportintervallen behouden bij deze berekening hun afzonderlijke fysieke huisvraag. Overige intenties blijven zoals voorheen samengevoegd. Een eerste regressierun gaf 16 fouten doordat die samenvoeging aanvankelijk ook bij gewone laadsegmenten verviel; oorzaak gericht gecorrigeerd, geen verwachting aangepast. Definitieve bestaande hoofd-/aanvullende keten plus nieuwe markttoets: **26 passed in 35,73 s**. Nieuwe toets bevat 9 gevallen; eerste acht zonder de exportduurcase: **8 passed in 0,17 s**. Sets overlappen. Ruff, mypy op beide productiemodules en `git diff --check` geslaagd.
- Implementatiestatus: de toelatingstoets en de gedeelde fysieke exportduur zijn lokaal geïmplementeerd/getest. De volledige marktroute is nog NIET aangesloten: user-rule-dashboard, selectie van fysiek passende alternatieven, aanroep van de nieuwe toelatingstoets vanuit de dagelijkse Candidate-keten, gezamenlijke actieve Store-binding en werkelijke exportregistratie blijven open. Geen handel actief gemaakt, geen live-versie, merge, versie-bump, deployment of apparaatcommando.
- Exact vervolg: fysiek passende exportvensters maken met dezelfde huishoudelijke projectie (prijsbewijs alleen is niet voldoende); deze via de bestaande Candidate/Evaluation-keten selecteren; dagelijkse handelsidentiteit en behouden laadidentiteiten atomair aan één actief uitvoeringsplan binden. Werkelijke uitvoering en gezamenlijke liveproef volgen pas op deze ontbrekende koppeling. ADR001–037 en gekoppelde geaccepteerde ADRs ongewijzigd.


### 2026-09-08 — Gezamenlijke actieve planbinding met afzonderlijke handelsidentiteit

- Opdracht: gebruiker akkoord met de gezamenlijke planbinding als volgende stap, met behoud van oorspronkelijke hoofd- en aanvullende laadopdrachten, herstart en mislukte opslag. Basis lokaal cca9479; remote 1ca9655b60818896465e99a7904c3a4fccbd57f3, tree 7efc14495ed5a422e535590d31450f23c5a38217. Branch implement/first-daily-charge-cycle. ADR001–037 en geaccepteerde gekoppelde ADRs niet gewijzigd.
- Binnen dezelfde ActivePlanCommitmentStore bestaat nu één expliciete actieve uitvoeringsplanverwijzing per scope. Oude bestanden zonder deze verwijzing blijven via hun bestaande dagelijkse pointer leesbaar. Een handelspublicatie schrijft het gedeelde immutable plan, de oorspronkelijke planreferentie, eigen MarketPlanBinding en actieve verwijzing in één bestaande fsync/replace-transactie. Geen tweede uitvoerder, opslagbestand of planner toegevoegd.
- bind_market_plan accepteert alleen een bestaande open dagelijkse handelsidentiteit met passend positief toelatingsresultaat, expliciete segmenten en exportenergie. De huidige actieve planidentiteit moet overeenkomen; een tweede toewijzing aan dezelfde regel/dag wordt geweigerd. De handelsbinding is eigendom en verwachte energie, geen gemeten voltooiingsbewijs.
- Deze markt-publicatiestap houdt de bestaande horizon en alle laadinstructies intact. Hoofdopdrachten blijven naar hun oorspronkelijke laadplan en segment verwijzen; het gedeelde uitvoeringssegment bewaart expliciet die oorsprong. Aanvullende opdrachten houden identiteit, doel-SOC, eindtijd, required_by en voltooiingsbewijs; alleen hun uitvoeringsreferentie wordt atomair overgezet. Een toekomstige laadoptimalisatie kan een nog open handelsvenster niet stil verwijderen of verplaatsen.
- Herstel van Planning Input erkent de eigen markteigenaar naast de oorspronkelijke laadeigenaren. Opslagvalidatie volgt de oorspronkelijke laadplanreferentie terug en weigert gewijzigde hoofdacties. De bestaande SOC-monitor neemt de vastgelegde export-Wh per segment mee in dezelfde fysieke simulator. De tijdsindeling wordt waar nodig op de grenzen van het gedeelde plan gesplitst, met behoud van huishoudelijke en PV-energie. Handelsbindingen staan in de inputsignatuur en diagnostiek.
- Nieuwe tests gebruiken een door de echte dagelijkse pipeline gemaakt laadplan. De handelsactie/toelating in deze tests is expliciet een fixture voor de opslaggrens, GEEN bewijs van financiële marktselectie of HA-uitvoering. Getoetst: hoofdvoltooiing via oorspronkelijke oorsprong; aanvullende voltooiing zonder het dagdoel te wijzigen; herstart; idempotentie/daglimiet; afwijzen van gewijzigde laadactie, ontbrekende oorsprong en oude planreferentie; corrupte gedeelde opslag; oude opslag zonder nieuwe pointer; fysieke SOC-monitor inclusief 100 Wh export.
- Verificatie: python -m pytest -q tests/test_market_plan_binding.py tests/test_market_daily_assignment.py tests/test_daily_main_active_pipeline.py tests/test_supplemental_charge_commitment.py tests/test_ha_charge_transition_chain.py: 43 passed in 57.47 s, exit 0. De foutinjectie is daarna aangescherpt van een _write-stub naar een fout in os.replace, na het daadwerkelijk schrijven van het tijdelijke bestand; afzonderlijk opnieuw getest: 1 passed in 1.44 s. Dit is dezelfde test, niet optellen als extra dekking. Ruff geslaagd; mypy op vijf gewijzigde productiemodules: geen fouten. git diff --check geslaagd. Tijdens ontwikkeling gecorrigeerde testfixtures: observerweergave versus canoniek opgeslagen plan, te lang handelsvenster over de leveringsdaggrens, juiste veldnaam voor fysieke netexport. Een verkeerd ingevoegde deserialisatieregel is vóór de definitieve regressie gecorrigeerd.
- Grens van deze stap: de nieuwe publieke opslagbinding en herstelde SOC-monitor zijn geïmplementeerd; de automatische dagelijkse Candidate-keten roept bind_market_plan nog niet aan. Fysiek passende marktvensters, selectie via bestaande Evaluation/PlanBuilder, behoud van markteigendom bij volledige laadheroptimalisatie, user-rule-velden en werkelijke export-/stopregistratie moeten nog worden aangesloten en gezamenlijk getoetst. Er is GEEN volledige marktroute live gezet, geen merge, versie-bump, deployment of apparaatcommando. Offline ketentests blijven uitdrukkelijk geen HA-livebewijs.


### 2026-09-08 — automatische user-rule-marktselectie en uitvoeringsbewaking aangesloten

- Opdracht: akkoord op automatische marktselectie en uitvoeringsbewaking, met laadcyclus en marktroute samen in de eerste HA-proef. Basis lokaal ef9d58e, remote fb5d3b58d7da6af61e41fb23a0b72760e6233f5c, tree 0455ce89875c0b306b45e3f6dd7f4d7f82e54145; branch implement/first-daily-charge-cycle. Geen wijziging van bevroren ADR001–037 of de geaccepteerde gekoppelde ADRs.
- Bestaande user-rule-opslag en strategiepagina uitgebreid met absolute minimumspread EUR/kWh, optioneel herstel (standaard uit) en netto minimum EUR/export-kWh (standaard 0,05). SOC blijft vrij instelbaar als aandeel van bruikbare capaciteit. Een lege spread schakelt nieuwe handel uit; een oud procentueel prijsveld wordt niet verzonnen omgerekend naar EUR/kWh. Bestaande profielen blijven leesbaar. Dagidentiteit/volume/regelfixatie blijven bij herhaalde publicatie, poll en restart behouden.
- De bestaande dagelijkse Candidate-keten genereert fysieke handelsalternatieven met de resterende ontlaadcapaciteit na huisverbruik. Het exportvenster bevat exact het ingestelde netexportvolume na conversie; begin- en eindgrenzen en gedeeltelijke prijsintervallen tellen mee. De fictieve goedkoopste inkoopreferentie gebruikt de volledige gepubliceerde lokale leveringsdag, inclusief al verstreken tarieven, zonder de werkelijke capturetijd te vervalsen of een echte laadopdracht te creëren. Evaluation en PlanBuilder blijven selecteren/publiceren; er is geen tweede uitvoeringspipeline.
- Ontladen wordt in dezelfde huishoudsimulatie verwerkt. Maakt de extra belasting een bestaand hoofdlaaddoel ontoereikend, dan ontdekt de bestaande laadvensterzoeker passende PV/hybride/netaanpassingen met behoud van doelidentiteit. Andere hoofd-/aanvullende vensters en handel zijn beschermd. Alle behouden doelen moeten in de voorgestelde projectie haalbaar blijven, ook vóór selectie van de goedkoopste laadrevisie. Gedeelde markt- en laadbinding worden in één atomaire opslagwijziging gepubliceerd. Een schrijffout publiceert geen halve combinatie. De zoekstap reviseert één getroffen hoofdopdracht per alternatief en valideert daarna alle doelen; dit bewijst niet dat elke denkbare combinatie van meerdere tegelijk te reviseren doelen wordt gevonden.
- Herstel uit voegt geen toekomstige herstelprijs-/winst-/herkomsttoets toe. Herstel aan gebruikt de volledige gecombineerde route tegenover dezelfde no-trade-baseline en de bestaande marginale netto-resultaatberekening; Evaluation rangschikt dan nettowinst. Bij herstel uit kunnen strikt lagere exportprijzen na een toegelaten betere kandidaat aantoonbaar worden uitgesloten; rekenkundige gelijken blijven ter selectie beschikbaar. Deze uitsluiting wordt niet ten onrechte op nettowinst toegepast. De uitgebreide zoekruimte bij herstel aan kost merkbaar meer rekentijd; responstijd op de HA-host is nog niet vastgesteld en moet vóór de gezamenlijke liveproef worden gemeten.
- Lopende marktvensters blijven bij SOC-gestuurde laadheroptimalisatie behouden. Alleen het verstreken prefix wordt uit het actuele uitvoeringspad geknipt; oorspronkelijke uitvoeringsreferenties, eindtijd en volledig dagbudget blijven opgeslagen. Verstreken geplande Wh worden nadrukkelijk geen gemeten export. De wintertest bewijst een langere benodigde laadroute rond het goedkoopste bekende venster, onder dezelfde oorspronkelijke dagopdracht.
- Start-/stopbewaking loopt door de bestaande CanonicalExecutionRuntime en HA-modusadapter: vóór start onvoldoende SOC voor de volledige voorspelde batterijafname betekent overslaan; tijdens uitvoering ondergrens, venstereinde, bereikt gemeten budget of ontbrekende exportmeting betekent NOM aanvragen. Een stopaanvraag is geen stopbevestiging. Modusterugmelding en vertraagde feedback blijven leidend, zonder dubbele dispatch. Handmatige overname blijft buiten planneractuatie. Duurzame voortgang veroorzaakt via de bestaande completion_generation een nieuwe inputcapture bij fasewijziging.
- Gemeten batterijexport wordt afgeleid uit gelijktijdige batterijontlading en netexport, volgens dezelfde PV-eerst-huis-toerekening: de kleinste ogenblikkelijke richtingstroom, geïntegreerd over HA state-hold meetintervallen. Geen SOC-delta, prognosevolume, looptijd maal nominaal vermogen of los huishoudverbruik als exportbewijs. De bestaande HA-history-reader kan voor deze lezing onbekende waarden expliciet bewaren; andere bestaande lezingen houden hun gedrag. Ontbrekende/eindigende historie sluit niet met een oude deelmeting. Een aantoonbaar beëindigde uitvoering met een blijvend gat in volledig teruggeleverde historie sluit als stopped met onbekend volume, nooit als fictieve nul of completed. Dit verfijnt de eerdere opslagnotitie die voor iedere uitgevoerde sluiting een hoeveelheid verlangde; completed vereist nog steeds positief gemeten volume.
- Verse brede regressie: python -m pytest -q tests/test_market_rule_selection.py tests/test_market_execution_guard.py tests/test_v2_power_history.py tests/test_user_rules.py tests/test_market_price_windows.py tests/test_market_route_admission.py tests/test_market_daily_assignment.py tests/test_market_plan_binding.py tests/test_daily_main_active_pipeline.py tests/test_supplemental_charge_commitment.py tests/test_daily_main_plan_recovery.py tests/test_ha_charge_transition_chain.py tests/test_pending_mode_feedback.py tests/test_charge_segment_closure.py tests/test_v2_power_history_integration.py tests/test_v2_web_ui.py tests/test_v2_web_ui_http.py tests/test_independent_daily_tariff_adapter.py: 182 passed in 176.80 s. Daarna één extra budget-/stop-/restartcontrole toegevoegd; definitieve volledige guard-set: 6 passed in 5.87 s. Sets overlappen, aantallen niet optellen. Ruff op alle productiemodules en gewijzigde tests geslaagd; mypy src/picot met aparte cache: geen fouten in 204 productiemodules; git diff --check geslaagd.
- Tijdens ontwikkeling gecorrigeerd: fixtures met onvolledige gepubliceerde dagtarieven/huishoudhorizon, de verkeerde veldnaam van de nieuwe hersteltest, typevernauwing na immutable replace, ontbrekende meetgatmarkeringen en het bewaren van het originele handelsvenster bij lopende reoptimalisatie. De laatste brede run bevat de meetgat- en hersteloptietests. Dit zijn lokale integratie- en regressiecontroles, geen CI_VERIFIED of LIVE_VERIFIED.
- Geïmplementeerd op de werkbranch: configuratie, automatische marktselectie, gezamenlijke laadoptimalisatie/publicatie, vensterbehoud en uitvoerings-/volumebewaking. Nog vóór HA-proef: releasecontrole inclusief responstijd en beschikbare modus-/vermogensmetingen op de echte installatie. Instelbare spread moet expliciet worden ingevuld voor nieuwe handel. Geen merge, versie-bump, deployment of echte HA-/batterijcommando's uitgevoerd.


### 2026-09-09 — herstelberekening versneld en bestaande uitvoering tussentijds bediend

- Opdracht: akkoord op oplossen van rekentijd en het ophouden van stopbewaking binnen de bestaande pipeline. Basis lokaal 3caf46b11e72857a8fb61e0a88a42175d4b22d3a, remote 77dd3c72bc68afdba6e00b0019da60ec1022fea0, tree 7cd9be13d27f51370aa41de159811f0af7ffeff7. Branch implement/first-daily-charge-cycle. De voorafgaande read-only controle vond 66,96 s voor de hersteltest, 6,06 s voor de vergelijkbare wintertest zonder herstel, en dezelfde synchrone lus voor planning en uitvoering. Zeven selectietests en achttien meet-/guardtests slaagden; dat hief het timingrisico niet op.
- Profiel van de wintercombinatie: 2.646 planning-basis-simulaties, waarvan 2.632 vanuit de laadvensterzoeker. Voor zuiver netladen bevat de volledige netlaadproef per start al de eerste doeloverschrijding. De zoeker gebruikt die projectie, knipt uitsluitend latere laadopdrachten weg en simuleert het complete resterende pad opnieuw voor financiële/andere doelen. Binaire eindtijdproeven voor dit geval vervallen; alle startmogelijkheden en prijsselectie blijven behouden.
- Een eerste te brede toepassing van deze verkorting is NIET behouden: de onafhankelijke vergelijking liet bij hybride laden zien dat eerder stoppen met netladen en later afronden via PV een andere minimale netduur oplevert. Voor PV/hybride blijft de oorspronkelijke zoekmethode daarom intact. Definitieve vergelijking met de oude module: 24 exact gelijke uitkomsten (vensters, volgorde, IDs, segmenten en volledige energieprojecties), uitsluitend simulation_count buiten vergelijking. Gevarieerd: SOC 10/50/99,5/100%, geen/beperkte/voldoende PV, met/zonder beschermd interval. Nieuwe deterministische check begrenst het aantal simulaties voor de pure netzoekruimte.
- Een optionele checkpoint-hook loopt door dezelfde canonieke samenstelling naar de marktalternatieven en vóór publicatie. De live coördinatie bedient hier de reeds bestaande committed boundary op de bestaande pollcadans of een eerder segmentgrensmoment. Geen extra thread, concurrerende Store-schrijver, tweede Candidate/Evaluation, nieuwe prijsgrens of alternatieve apparaatsturing. Domeinsimulatie en selectie kiezen geen uitvoering; de callback laat uitsluitend de bestaande uitvoeringscoördinatie aan bod komen tussen alternatieven.
- Wijzigt een geobserveerde start/stop/doelvoltooiing de duurzame uitvoeringsfase, dan wordt de in-flight berekening expliciet afgebroken vóór publicatie. De bestaande live cyclus krijgt False terug en plant later met nieuwe immutable input. Oude doelen/actieve route blijven behouden. Ongewijzigde uitvoering kan worden bediend terwijl de berekening verdergaat. Dit is coöperatief tussen alternatieven, niet een harde realtime-interrupt midden in één simulatie of HA-read.
- Na planning wordt de live dagelijkse uitvoering opnieuw beoordeeld met apart ingelezen actuele input via dezelfde advance_committed_boundary. Huidige tijd, SOC, provenance, modus en marktvolume bepalen het werkelijk toe te passen opgeslagen segment. De oorspronkelijke planningssnapshot blijft ongewijzigd. Een inmiddels lage SOC leidt in de integratietest tot NOM terwijl de oude planningssnapshot een hogere SOC bevat. Uitvoeringsreferentie, werkelijk aanvraagmoment en de aparte SOC-observatie worden herleidbaar vastgelegd; de oude adaptervertaling wordt niet als nieuwe vertaalevidence hergebruikt. Historische/offline callers zonder refresh-hook behouden hun bestaande API-gedrag.
- Nieuwe checks: bestaande poll versus eerdere segmentgrens; geen dubbele checkpoint-read vóór dat moment; fasewijziging breekt marktpublicatie af; behoud van hoofdopdrachten; verse SOC gebruikt voor dispatch zonder planning-input te herschrijven; live samenstelling vangt annulering af zonder dispatch. De bestaande live wiring-test bevestigt dat beide hooks worden doorgegeven. Tijdens testbouw gecorrigeerd: capture-lineage van een verplaatste testwaarneming, ongeschikte oude opslagfixture voor echte marktselectie, ontbrekende constructorargumenten van PriceOpportunityConfig en de expliciete signatuur van de bestaande capture-stub. Geen productieregels aangepast om die fixtures groen te krijgen.
- Open omgevingsgrens: rekentijden zijn lokaal gemeten. De werking en vertraging van echte HA-history-reads en modusfeedback moeten nog op de installatie worden waargenomen. De dev.243-diagnose van 7 september bevat de Shelly-netmeting en Zendure naar-huis-meting in W; dit is geen bewijs van hun actuele volledige recorderhistorie. Geen merge, versie-bump, deployment of apparaatcommando's. Bevroren ADR001–037 en gekoppelde ADRs ongewijzigd.

- Definitieve geïntegreerde regressie: python -m pytest -q tests/test_planning_execution_service.py tests/test_daily_main_charge_windows.py tests/test_market_rule_selection.py tests/test_market_execution_guard.py tests/test_daily_main_active_pipeline.py tests/test_daily_main_route_optimisation.py tests/test_ha_charge_transition_chain.py tests/test_pending_mode_feedback.py tests/test_charge_segment_closure.py tests/test_v2_live_replan_poll_cycle.py tests/test_v2_live_web_view_publish.py tests/test_v2_live_pv_actual_coupling.py --durations=10: 99 passed in 91.01 s. Hersteltest 29,38 s tegenover vooraf 66,96 s; wintercombinatie zonder herstel 2,60 s tegenover 6,06 s. Dit betreft dezelfde lokale testgevallen, geen HA-hostmeting.
- Na de brede run is de uitvoeringsweergave aangescherpt zodat ook mappingstatus, bronentiteit en mappingmethode uit de verse uitvoeringswaarneming komen. Definitieve volledige nieuwe service-set: 5 passed in 5.92 s (overlap met de 99, niet optellen). Ruff op alle productiemodules en gewijzigde tests: geslaagd. Mypy src/picot met aparte cache: geen fouten in 205 modules. git diff --check geslaagd. Geen CI_VERIFIED of LIVE_VERIFIED geclaimd.


### 2026-09-09 — release dev.244 voorbereiden

- Expliciete opdracht: "akkoord maak release" voor de gezamenlijke laad- en marktrouteproef. Main staat op 39e5fd50bba47367f3934ef7bc93fb9e302b2985/dev.243; de sessiebranch b5d5eb96cb25a0ab9daa9e139004b7639f7e21e8 is 62 commits vooruit en nul achter. Dit is de overeengekomen cumulatieve sessierelease.
- Runtimeversie, HA-manifest en versiecontrole naar 2.0.0-dev.244; add-on-changelog toegevoegd met werking en instelvereisten. De bestaande Dockerfile bouwt uit main; publicatie vereist daarom samenvoegen van de release-PR na CI. Geen wijziging aan plannerbeleid of installatie-instellingen. De gebruiker installeert de HA-update; in deze stap worden geen batterijcommando's gegeven.

- Versie- en verpakkingscontroles lokaal uitgevoerd; de volledige releasecontrole loopt daarnaast op de PR. Nog geen HA-livebewijs.

- Eerste release-CI: Core geslaagd; v2 623 geslaagd en één verouderde exacte veldlijst gefaald. De SOC-read-evidence uit de eerdere sessiestap voegde state_read_at/state_valid_since toe, geen capabilitylimieten. Alleen de contracttest bijgewerkt met die twee optionele meetbewijsvelden, hun lege defaults en expliciet ontbreken van laad-/ontlaadvermogenslimieten. Geen productieregel gewijzigd; PR-controles worden opnieuw uitgevoerd.
