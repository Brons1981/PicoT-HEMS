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

## Display amendment — 2026-10-15

User-approved dashboard redesign replaces the purple measurement line with green
quarter-hour SOC bars below the price plot. This supersedes only the measurement
colour and geometry above. Empty outlines cover the same today/tomorrow calendar
window as prices; no future measurement is invented. Each fill represents the
observed SOC at the quarter end (now for the current quarter), bounded by the
history end and explicit unavailable observations. Missing measurements remain
empty; an observed zero remains a valid value. The yellow expectation retains its
existing historical strokes, provenance and break markers. Neither the dashboard
nor the bars simulate, aggregate energy, write history, or alter canonical plans.
