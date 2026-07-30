# PicoT HEMS Session Workflow

## Status

Accepted

## Purpose

This document defines the mandatory workflow for PicoT HEMS development sessions. GitHub is the Single Source of Truth for official project state, decisions, documentation, and next actions.

## Core rule

What is not recorded in GitHub is not an official PicoT HEMS project decision.

Chats are the working space. GitHub is the official record.

## Session start

Every development session starts with:

`FULL SYNC`

The sync must read the current GitHub state before further design or implementation work begins. At minimum it checks:

- latest development log;
- active roadmap item or implementation phase;
- open ADRs, CFDs and PEPs relevant to the session;
- recent commits and open issues or pull requests when applicable;
- the documented next step from the previous session.

The result is a concise session start summary stating where the project currently stands and what the next agreed step is.

## During the session

New information is classified and recorded in the appropriate project form:

- ADR — architecture decision;
- CFD — Core Framework decision;
- PEP — enhancement or future functionality;
- Roadmap — planning or phase placement;
- Vision or Principles — project identity and design philosophy;
- Development Log — concise session record.

Adapters, planner logic, diagnostics, device packs and other implementation details must remain consistent with the accepted architecture and dependency boundaries.

## Session end

When the user says `FULL SYNC` at the end of a session, the assistant prepares an end-of-session report containing:

- subjects discussed;
- accepted decisions;
- documents changed;
- open actions;
- exact next step for the following session.

After the user approves that report, the assistant must automatically perform the GitHub synchronization. A sync is only complete after the approved changes are actually written to GitHub.

The assistant must then explicitly report:

- whether the GitHub sync succeeded;
- which files, issues, pull requests or commits were changed;
- the resulting commit SHA or relevant GitHub references;
- any part that could not be synchronized.

The assistant must never describe a conceptual or chat-only summary as a completed GitHub sync.

## Development log

Each completed end-of-session sync adds or updates a dated development log in:

`docs/development_log/YYYY-MM-DD.md`

The log must be concise and include:

1. Summary
2. Subjects
3. Decisions
4. Documents updated
5. Open actions
6. Next session
7. GitHub sync result

## Approval boundary

No project decision is written as accepted before the user approves it. Once the user approves the end-of-session report, the GitHub write is automatic and does not require a second confirmation.

## Full sync states

A FULL SYNC has three explicit states:

- `PREPARED` — report drafted but not yet approved;
- `APPROVED` — user accepted the report and GitHub synchronization must run;
- `COMPLETED` — GitHub has been updated and the resulting references have been reported.

Only `COMPLETED` means the project is synchronized.

## Failure handling

If a GitHub write fails, the sync status is `FAILED`, not `COMPLETED`.

The assistant reports the failure truthfully, lists what did and did not change, and does not claim that GitHub is current until the failed part has been retried successfully.
