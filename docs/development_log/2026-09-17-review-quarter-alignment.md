# Passive quarter measurement alignment — dev.263 release requested

Alex authorized separate measurement processing after diagnosing skipped household
observations. Canonical input computes PV + signed grid - signed battery power,
rejecting negative balances. All eight September 17 household gaps overlap negative
balances; seven have no unavailable directional power source states. This indicates
incompatible update timing/data, not proof that all sensors were absent. At 11:30:34
PV was 987 W (last update 11:27:41), grid -45.909 W, charge 1154 W: -212.909 W.

The export has power histories, not energy-counter histories. The passive observer
now integrates each source separately over identical UTC clock quarters (including
exact partial edges), then derives household Wh. The result is explicitly derived,
not independently measured: within-quarter timing/flow ambiguity is unresolved.
There are no new HA requests or configuration assumptions about counter entities.

Negative interval balances, missing anchors and unavailable source spans stay
invalid. No clipping, gap-filling, shifted timestamps or relaxed strict replay.
Raw measurements remain untouched. MEP, learning, commitments and control receive
none of this output. The strict review remains authoritative for its own criteria;
aligned estimates cannot promote it to available or certify a savings claim.

Full interval results join today's/yesterday's raw gzip archives. Day summaries
and invalid intervals are shown in the review UI. Long-term review state stores
only summaries (at most twenty invalid spans plus explicit omitted count), not
full interval tables.

September 17 19:43 export: 79 intervals, 74 derived and five invalid; negative
quarters 09:15–09:30 and 11:00–11:15 Amsterdam time; missing sources 04:00–04:15,
09:30–09:45 and 17:00–17:15. Total household energy deliberately remains null.
Alignment took ~0.15 seconds locally, excluding archive loading; not a NUC benchmark.
This improves usable retrospective estimates but does not repair source outages
or justify a full-day optimality conclusion. Energy-counter inputs remain a future
option requiring actual entity mappings and unit/reset validation.

Validation: five new numerical/coverage regressions; observer integration verifies
archive detail, summary separation and evidence flags. 73 focused tests pass.
Mypy passes for 77 v2 modules; Ruff and dashboard JavaScript syntax checked.
