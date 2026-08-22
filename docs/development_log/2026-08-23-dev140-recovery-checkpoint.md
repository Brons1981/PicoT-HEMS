# Development Log — 2026-08-23 — dev.140 recovery checkpoint

## Purpose

This checkpoint records what happened during the 2026-08-22/23 evening session and defines the only safe starting point for the next session.

It exists because the conversation crossed chat boundaries and the implementation direction drifted away from the agreed planner redesign. The log is deliberately factual and non-normative. It does not approve a new architecture and it does not make any of the reverted code authoritative.

## User decision that controls the next session

The intended redesign is **not** a set of grid/reference observer layers added to the existing PicoT pipeline.

The intended sequence remains:

1. Build one complete reference simulation for a full day containing:
   - current battery state;
   - household consumption per interval;
   - lower/central/upper PV;
   - physical NOM behaviour;
   - cumulative battery energy;
   - first moment at which 100% is reached;
   - consumption and reserve until the next charging opportunity;
   - average price and opportunity cost.
2. Let the Candidate Engine create candidates exclusively from that one simulation.
3. Let Evaluation rank only proven complete candidates.
4. Apply Commitment only after Evaluation.
5. Use this week's incident replays as a permanent acceptance set.

This redesigned route must initially run fully parallel to the original PicoT pipeline. It must make the original result and the new hypothetical result directly comparable and must not change the original winner, plan, commitment, adapter translation or dispatch.

## What was built before the rollback

A sequence of financial, physical and grid-related capabilities was implemented and published. The work included, among other things:

- canonical energy-ledger and settlement concepts;
- baseline, PV-only and grid-requirement financial comparison;
- explicit physical meaning for delegated storage modes;
- hard grid-requirement admission conditions;
- combined observer decisions;
- grid shadow Evaluation;
- projected grid execution-feasibility checks;
- Zendure grid-charge capability semantics;
- promotion of proven grid candidates into Evaluation;
- an embargoed grid Execution Plan;
- grid primitive-readiness monitoring;
- dashboard/projection and incident-history additions;
- dev.139 resilience around Home Assistant publication after an HTTP 502.

These changes were technically tested in their individual slices, but the combined direction was rejected because it modified and extended the existing pipeline instead of establishing the agreed independent full-day reference-simulation route.

No conclusion from those tests establishes that the intended new planner architecture was completed.

## Important clarified Zendure semantics

The following user-supplied meanings must be retained for future design review:

- **Alleen slim opladen** is NOM with charging ability from sources such as PV surplus; it does not prove or permit grid charging.
- Grid charging may use **Snel opladen** in a chosen winter/low-PV time window.
- **Handmatig** can be an option when PicoT would want lower charging power or charging spread in combination with PV, although this is expected to be uncommon.
- The @gielz integration is responsible for operational charging behaviour such as:
  1. prioritising available PV;
  2. filling only the remaining energy deficit from grid;
  3. limiting total addition by target energy, maximum SoC and battery capacity;
  4. stopping at target energy, deadline or end time.
- PicoT must reason about feasibility and intent at its proper boundary; it must not duplicate @gielz's internal real-time charging control.

These semantics require fresh architectural validation before any reverted code is reused.

## Why the rollback was ordered

The user concluded that the recent work was changing the existing planner pipeline, while the agreed objective was to escape the existing planner bug loop by designing a different planner route around one authoritative full-day simulation.

Selective repair was explicitly rejected. The instruction was to remove all post-dev.138 pipeline changes and restore exactly the dev.138 code.

## Rollback performed

The complete repository tree was restored to release commit:

- dev.138 commit: `da0196acf9362a78bf7723b9fb77d7522e5af312`
- dev.138 tree: `04cb63075710b02ec363e57f9d33d33b263770b1`

Only the three required version references were changed from `2.0.0-dev.138` to `2.0.0-dev.140`, so Home Assistant can offer the recovery build as an update:

- `picot_hems/config.yaml`
- `src/picot/v2/__init__.py`
- `tests/test_v2_version_alignment.py`

Rollback publication:

- PR: [#467 — Restore PicoT dev.138 code as dev.140](https://github.com/Brons1981/PicoT-HEMS/pull/467)
- rollback head: `ea16da64661fdf700eb406504c4931c186efeaa3`
- merge commit on `main`: `9f929e88959b957f68d7d217106040995047fbac`
- status: merged

The rollback removed 42 changed files relative to dev.138, representing 7,501 additions and 104 deletions from the rejected post-dev.138 state.

The rollback also deliberately removed the dev.139 Home Assistant HTTP-502 publication resilience change. That behaviour must not be silently reintroduced; it requires a separate, explicit decision after the planner baseline is stable.

## Verification of dev.140

Fresh rollback verification completed before publication:

- 919 repository tests passed;
- Ruff passed;
- mypy passed for 150 source files;
- `git diff --check` passed;
- compared with dev.138, only the three version files differ.

Therefore `main` at merge commit `9f929e8` is the accepted recovery baseline.

## The reverted work is not lost

The rejected code is absent from current `main`, but remains recoverable from GitHub history.

Primary recovery references:

- pre-rollback dev.139 snapshot: `5d8ff9081b60ba6d6a4d9a47cd3b33f4a1d8e440`;
- PR #461 / commit `d98db333d960f2fb0aad22caac7a9e72277e99be`;
- PR #462 / commit `7ed8ed6`;
- PR #463 / commit `29f2d68`;
- PR #464 / commit `9c20095`;
- PR #465 / commit `f8239e9`;
- PR #466 / commit `5d8ff90`;
- earlier observer PRs #457 through #460 remain available through their PR pages and branch/commit history.

Important Git-history warning: commit `d98db33` has no parent and is a separate root commit. The recovery work must therefore **not** assume a normal linear diff/ancestry chain. Reuse must be based on explicit file-level comparison against dev.140 and the agreed architecture.

No reverted file may be restored wholesale merely because it previously passed tests.

## Honest status of the full-day reference simulation

A complete independent full-day reference simulation, as defined in the five-step intended sequence, has **not** been proven complete.

What exists in the reverted snapshot includes potentially reusable components and tests, notably canonical household-energy simulation, storage projection, energy contracts, settlement and observer comparisons. However:

- they were coupled to or built around the existing pipeline;
- the Candidate Engine was not proven to generate exclusively from one authoritative daily simulation;
- Evaluation was not proven to accept only complete candidates from that simulation;
- Commitment was not rebuilt after that Evaluation boundary;
- the week's incident replays were not established as a permanent acceptance suite;
- no simple original-versus-new dashboard comparison satisfying the user's transparency requirement was completed.

The correct status is therefore: **useful source material exists, but the intended alternative planner has not yet been built.**

## Required first task for the next session

The next session must be read-only until this inventory is accepted.

Use the smallest possible sequence:

1. Confirm `main` still points to the dev.140 recovery baseline.
2. Compare the dev.139 snapshot and relevant PRs file-by-file against dev.140.
3. Classify each reference-simulation-related component as:
   - reusable unchanged;
   - reusable after decoupling;
   - unsuitable for the new route.
4. Produce one compact architecture map containing:
   - the original live pipeline;
   - the independent full-day reference simulation;
   - Candidate Engine;
   - Evaluation;
   - Commitment;
   - the comparison-only dashboard boundary.
5. Identify the smallest first vertical slice of the independent simulation.
6. Stop and request explicit approval before changing production code.

## Hard constraints for tomorrow

Until a new explicit approval is given:

- no production-code changes;
- no restoration or cherry-pick of reverted files;
- no changes to the existing Candidate Engine, Evaluation or Commitment;
- no live plan, primitive, adapter or Zendure changes;
- no release;
- no attempt to solve grid charging as a separate path;
- no broad full-suite test runs during inventory;
- no repeated reconstruction from chat text when GitHub evidence exists.

The inventory should minimise Codex/Work use by reading commit metadata and only the files directly relevant to the reference simulation.

## Transparency acceptance target

Before implementation resumes, the proposed parallel route must be able to expose a concise side-by-side result:

- **Origineel:** the untouched current PicoT result.
- **Nieuwe variant:** the hypothetical result from the independent daily simulation, rendered in a distinct text colour.

The user must not need to inspect approximately 100 technical fields to understand the outcome. Detailed lineage remains available underneath, but the primary result must be immediately visible and explainable.

## Safe resumption sentence

At the next session, begin with:

> Start read-only from dev.140 merge commit `9f929e8`. Use this checkpoint. Inventory the preserved reference-simulation code against the agreed independent daily-simulation architecture. Do not change code until the inventory is accepted.
