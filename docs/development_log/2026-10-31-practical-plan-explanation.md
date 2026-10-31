# Practical active-plan explanation

User requested a description of the active plan: solar charging kWh, solar energy
remaining for household/export, grid charging windows and kWh, expected 100% time,
and an evidenced standby-versus-battery-support cost difference.

The read-only dashboard now presents that description above the existing decision
details. Optional physical-flow evidence travels with projected energy states from
the existing simulator; no planner ranking, execution, or control policy changes.
Input energy is labelled before charging losses. Local-day totals include their
actual forecast period; 100% comes from a projected SOC checkpoint, not a deadline.

Only published energy-path identities can supply the narrative. Observation-only
ticks retain identity-bound, dated energy evidence through the existing display
cache while refreshing action windows. Missing, overlapping or incomplete flow
evidence is not reported as zero. Fallback does not describe a candidate as active.

Standby savings require comparable total EUR costs, equal terminal storage, and
routes differing only by one contiguous standby-versus-support interval. General
route savings and acquisition rates are not attributed to standby.

Implementation is based on published HEMS dev.323, PR #733. No version bump,
release, installation or plan reset is included in this follow-up dashboard task.

Validation: final integrated run passed 162 tests across narrative, DOM rendering,
cache/restart, existing dashboard, SOC projection and daily-main/PV/total-cost
pipeline cases. Changed-file Ruff passed; targeted Mypy passed for all six changed
source modules. Windows required PYTHONUTF8=1 for the existing Node syntax test;
the final run passed that check. No live installation or browser screenshot check.

Release follow-up: Alex authorized publication as HEMS dev.324. Base is dev.323
commit 79c442b523ec39750918b0b7e91a85c7a5a2c8d5. PR CI must pass before merge.
Home Climate remains dev.24; live installation remains separate.
