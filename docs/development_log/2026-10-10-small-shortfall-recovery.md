# Small predicted shortfall and retained bridge fix

Release candidate HEMS 2.0.0-dev.291; not installed or live-validated. Energy Devices, original @gielz,
HA configuration, correction formula and physical minimum SOC are unchanged.

## Incident and reproduction

HEMS dev.290, diagnostic export 2026-10-10T164707.681:
- Today's main completed at 13:15:42 UTC (15:15 Amsterdam).
- Bridge at 13:32:14 UTC predicted 236.94216542458375 Wh household scarcity
  at 06:15–07:00 UTC the next morning. A bridge charged/preserved full stock
  until 16:45 UTC (18:45 local).
- Main revision at 14:26 UTC predicted 92.762112748406 Wh shortage for tomorrow
  and retained that earlier bridge without its purpose identity.
- Execution blocked at SOC 100%, dispatched at 98% at 14:36 UTC.
- Reconstructed typed PlanningInputSnapshot with real adapter/simulator and
  sqrt(0.8164) directional conversion reproduces 236.94216542458375 Wh exactly.
  Removing only the measured 15-minute excess leaves 148.60298537651312 Wh.
  Rebuilding historical forecast without October 9 removes the bridge shortage;
  this is an influence check, not proof that all October 9 excess was EV.

## Implemented behavior

- Main and bridge forecast tolerance 3% capacity, only with fresh later recovery
  proof. Exact 100% completion and physical reserve remain unchanged.
- Bridge proof evaluates delayed direct household grid support after 15 minutes,
  preserving owned main segments and admitted exports, and proves pending main
  goals still reachable. Current/large/unknown/unrecoverable shortage is not deferred.
- Zero-acquisition unowned bridge charging becomes direct-support standby when
  there is independent household need. Pure trade gets no new standby permission.
- Bridge purpose and boundaries survive Candidate Generation/Plan Builder.
  Non-running bridge slots are reassessed with a main revision; running fast
  charging below full retains continuity.
- Identified measured EV history remains separate after current policy is disabled;
  RAW physical values remain stored. Oven stays ordinary demand. Old unlabelled
  history is not retrospectively guessed or deleted.

## Fresh verification

- Four new regression checks against isolated pre-fix source: four expected
  assertion failures (deferral, zero-acquisition command, retained refill, EV history).
- Broad affected suite: 369 passed in 185.66 seconds (39 test files).
- After final bridge-boundary refinement: 47 affected tests passed in 80.27 seconds,
  including physical simulation, Evaluation/Builder, restart and EV/oven ingestion.
- Ruff for changed Python source and tests: passed.
- Mypy for three changed production modules: passed.
- git diff --check: passed.
- Exact incident adapter replay: now deferred_with_recovery, no bridge trigger.

An intermediate extended test used a nonexistent window-set horizon_end field;
corrected to the schedule's horizon_end. Final checks above are fresh and green.

## Installation and limits

Future release requires existing repository release checks. After installation,
request one new canonical plan to clear anonymous bridge slots saved by the old
version. Enable energy_device_policy_enabled in HEMS to ingest the existing
Energy Devices policy snapshot; no direct EV sensor binding in HEMS. Existing
false options are not overridden. Live operation and long-running stability
remain to be checked after deployment.
