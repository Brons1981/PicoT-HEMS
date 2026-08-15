# PicoT v2 Development Log


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
