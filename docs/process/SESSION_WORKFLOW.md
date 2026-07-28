# PicoT HEMS Session Workflow

## PicoT Start-of-Session (Full Sync)

Before new design or implementation work begins:

1. Inspect the current GitHub repository state.
2. Identify the active branch, recent commits, changed source files, and changed documentation.
3. Read the relevant accepted architecture documents and ADRs.
4. Review stored PicoT ideas and side tracks, clearly separating accepted decisions from future ideas.
5. Perform a consistency check against the planned topic.
6. Summarize what is fixed, what remains open, and the scope of the current session.
7. Only then begin designing or implementing.

GitHub is authoritative. Architecture documents and ADRs take precedence over chat memory.

## PicoT End-of-Session

At the end of every work session:

1. Update source code and relevant architecture documents.
2. Add or update ADRs when accepted decisions changed.
3. Write a short session report.
4. Record open points and the roadmap for the next session.
5. Confirm the branch and commits that contain the session output.

## Session report template

```markdown
# Session YYYY-MM-DD

## Goal

## Discussed

## Decisions

## Open points

## Next session
```

## Scope discipline

During each session, distinguish between:

- an architectural decision that must be fixed now;
- implementation required for the current version;
- future functionality that belongs on the roadmap.

Guiding principle:

> Architecture future-proof, implementation minimal.
