# V2ADR-066 — SOC display expectation and history

Status: Accepted (user agreement, 2026-09-15)

The purple SOC line contains measurements only. The yellow line preserves the
forecast geometry already elapsed and shows one current expectation after the
observation time. Each refreshed future starts at observed SOC. A break separates
it from the previous forecast; no invented connecting slope hides deviations.

The daily simulation owner projects the retained committed schedule with fresh
Planning Input, including on polls that do not replan. This is read-only display
evidence with plan, snapshot, schedule, PV basis and measurement provenance. It
never changes the winning EnergyPath, monitoring baseline, assignments, evaluation
or execution. No window search or UI energy simulation is permitted.

Unavailable simulation input clears the current expected future explicitly.
Bounded persisted display history retains prior forecast strokes across restarts;
the original winning path remains the original planning evidence. Display clipping
is graphical interpolation, not a new physical prediction.
