# Active plan cash projection

The dashboard previously showed whole-route costs only when an admissible
incumbent/challenger comparison existed. A required SOC repair uses acquisition
cost per stored kWh for selection, so the active plan's cost was invisible.

Expose the already-settled full-horizon import cost and export revenue from the
main-charge portfolio as optional display evidence on its energy paths. Carry
these values and their exact horizon through the canonical v2 projection. The
plan narrative reports net cash cost only for the admitted path in this snapshot.
The existing identity-bound display cache preserves its original calculation
time on retained observations and restart; replacement plans cannot inherit it.

The Dutch dashboard shows total forecast electricity cost, import and export
components, and the precise forecast period. This is not an actual whole-day
bill, an EV-only estimate, a savings claim, or an acquisition rate. Fixed charges
are excluded. Missing evidence remains explicitly unavailable. No new simulation,
candidate scoring, tariff policy, comparison or device control is introduced.

Regression coverage includes producer cash on a mandatory SOC repair, pipeline
projection, Dutch rendering, elapsed periods, absent/nonfinite/stale evidence,
and cache continuity across observations, restart and plan identity changes.
