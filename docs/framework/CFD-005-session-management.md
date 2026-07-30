# CFD-005 — Session Management and GitHub Synchronization

## Status

Accepted

## Context

PicoT HEMS is designed and implemented across many sessions. Project knowledge must remain durable, reproducible and independent of chat history.

## Decision

GitHub is the Single Source of Truth for official PicoT HEMS project state.

Every development session starts and ends with a FULL SYNC.

## Session start

A session starts with:

```text
FULL SYNC
```

The assistant reads the current GitHub state, including the latest development log, active roadmap phase, relevant ADRs, CFDs and PEPs, recent commits, open issues and the previous next step.

## During the session

New information is classified as one of:

- VISION;
- PRINCIPLES;
- ADR;
- CFD;
- PEP;
- ROADMAP;
- Development Log.

Chats are the working space. GitHub is the official record.

## Session end

The assistant prepares an end-of-session report containing:

- subjects discussed;
- accepted decisions;
- documents changed;
- open actions;
- exact next step.

After user approval, the assistant automatically writes the approved changes to GitHub and reports the exact files and commits.

## Sync states

- `PREPARED` — report drafted;
- `APPROVED` — report accepted and GitHub write required;
- `COMPLETED` — all approved changes written and references reported;
- `FAILED` — one or more required writes failed;
- `PARTIAL` — only part of the approved scope was written.

Only `COMPLETED` means the project is synchronized.

## Development log

Every completed end-of-session sync creates or updates:

`docs/development_log/YYYY-MM-DD.md`

The log contains:

1. Summary
2. Subjects
3. Decisions
4. Documents updated
5. Open actions
6. Next session
7. GitHub sync result

## Core rule

> What is not recorded in GitHub is not an official PicoT HEMS project decision.

## Consequences

- No approved project knowledge remains dependent on chat memory.
- A future session can resume from GitHub after a day or after a year.
- Sync status must be reported truthfully.
- A conceptual summary may never be described as a completed GitHub sync.
