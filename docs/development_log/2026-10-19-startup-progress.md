# Startup progress in the existing status bar

User-approved scope: show real startup milestones in the existing execution-mode
bar, distinguish waiting for the first run from a connection failure, and record
phase durations. No planner, execution authority, energy calculation, or release
version changes.

Live evidence on dev.309: first logged loop took 306779 ms; the reported
pipeline_total_ms was 91479 ms (includes input assembly). The old logs did not
fully attribute the remaining time. The dashboard recovered without a restart.
The updates endpoint returned expected waiting_for_first_run HTTP 503 before a
first view; the browser previously reported every non-OK response as a broken
connection.

StartupProgress is a locked, observer-only in-memory tracker. Runtime milestones
cover setup, input capture, preparation, material observations, energy history,
planning, execution checking, projection, financial overview and publication.
Nested fresh-input checkpoints restore the enclosing phase. Percentages represent
milestones, not elapsed-time estimates; time alone never advances the bar.
Phase transitions log duration_ms and elapsed_ms as picot_v2_startup_phase.
Tracking ends after the first complete dashboard publication.

GET /api/startup is lightweight and independent of the full dashboard snapshot.
The browser polls it every two seconds until the first view actually renders,
caps progress at 99 before rendering, and restores the existing execution label
and styling afterwards. Late progress responses cannot overwrite live status.
Only the exact waiting_for_first_run 503 is neutral; actual failures remain errors.

Validation: focused tracker tests, HTTP/JavaScript startup tests, existing live
publication/startup/household-recording/poll and dashboard tests. Windows tests
use PYTHONUTF8=1 and a workspace basetemp; default temporary-directory permissions
and cp1252 encoding initially prevented unrelated test setup/syntax checks.
Ruff and Linux-targeted mypy pass. No HA installation or release performed.
