# PicoT v2 Development Log

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
