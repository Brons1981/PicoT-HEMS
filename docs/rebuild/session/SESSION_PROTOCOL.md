# PicoT v2 Development Session Protocol

Status: **MANDATORY**

## Purpose

Prevent development drift across ChatGPT sessions. GitHub, not chat history, is the source of truth for the active PicoT v2 development state.

## Session start protocol

A new session must **not** begin with a full GitHub sync or repository-wide code review.

Read, in this exact order:

1. `docs/rebuild/session/ARCHITECTURE_BASELINE.md`
2. `docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md`
3. `docs/rebuild/session/DEVELOPMENT_LOG.md`
4. this file

Then state back:

- active PicoT version;
- active branch;
- last verified commit;
- current phase;
- exact current pipeline position;
- first next approved action;
- any explicit DO NOT CHANGE constraints.

Only then may specific repository files be fetched for the next step.

## During-session protocol

Every code change must satisfy all of the following before implementation:

- relevant ADR-001..039 contracts have been checked;
- the change belongs to exactly one accepted responsibility;
- no parallel path is introduced;
- canonical input/output ownership is explicit;
- diagnostic projection is passive and does not calculate planner decisions;
- CPU/runtime impact of diagnostics is measurable and bounded;
- the change can be observed through the existing nine-card pipeline dashboard, never via a side-channel test pipeline.

Implementation status must be classified explicitly as one of:

- `DECIDED`
- `IMPLEMENTED`
- `CI_VERIFIED`
- `LIVE_VERIFIED`

Never treat a lower state as a higher state.

## Temporary code rule

Temporary bridge/workaround code is prohibited unless it is unavoidable and explicitly approved.

If approved, it must contain in-code markers and a matching Development Log entry with:

- exact file/section;
- reason;
- scope;
- architectural owner it temporarily bridges;
- removal condition;
- target removal phase/version.

Unmarked temporary behaviour is a defect.

## Diagnostic projection rule

Diagnostic projection is passive only:

- consumes existing immutable canonical outputs;
- performs no duplicate physical/planner calculation;
- performs no polling per layer;
- cannot influence candidate generation, evaluation or execution;
- batches/buffers persistence where useful;
- exposes its own runtime cost.

At minimum track:

- planner cycle duration;
- diagnostic projection duration;
- serialization duration;
- persistence duration;
- events per run;
- buffer depth where applicable.

## Session end protocol

A session is **not complete** until `DEVELOPMENT_LOG.md` is updated and committed.

The log must state:

- date/session;
- PicoT version;
- branch;
- last verified commit;
- completed work;
- decisions made;
- CI verified items;
- live verified items;
- not verified items;
- known issues;
- DO NOT CHANGE / critical context;
- exact current position;
- exact first next action.

If work is only implemented but not live tested, the log must say so explicitly.

## New-session trigger phrase

A user may start a future session simply with:

`PicoT v2 start`

The required assistant action is to read the bootstrap files above and continue from the recorded exact position. The user should not need to reconstruct prior session context manually.
