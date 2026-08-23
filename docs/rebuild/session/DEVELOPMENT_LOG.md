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

Status: `LOCAL_VERIFIED`; not yet `CI_VERIFIED` or `LIVE_VERIFIED`.

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
