# Standby through the next protected boundary

Status: included in HEMS dev.336 release. Baseline: HEMS dev.335 / HC dev.32.

The 6 November 20:14 local snapshot selected standby until 09:30 next day.
Replaying snapshot-ed36697af3f5366d with the original code reproduces the exact
winner fe4be290f6e697ca and net cost EUR 4.023825932963345.
The generator offered shortest sufficient contiguous standby spans and the
whole bridge, but missed later starts held through the remaining free span.

Keep the already simulated longest feasible span for every eligible start in
addition to the shortest span. Existing PV/export/committed/reserve boundaries,
main goals, financial thresholds and canonical selection remain authoritative.
One candidate per start is added at most; feasibility projections are reused.
This is bounded discovery, not exhaustive enumeration of all interval subsets.

The four ordinary/revision x PV/no-PV regressions fail before the repair on the
missing longer span and pass after it. They also exercise protected boundaries,
zero bridge deficits, unchanged main/export actions and bounded search effort.
The original incident replay now selects candidate 96e896708784a390: support
until 22:15 local, standby until 09:30, followed by exactly the same main charging
segments, power and SOC constraints. Net cost EUR 4.012497468915197. The 21:30
alternative also exists; the unchanged EUR 0.01 equivalence and subsequent
objectives determine the winner. No live state was changed by these replays.

Verification: 37 bridge regression tests pass; targeted Ruff and Linux Mypy pass.
26 additional market stability/revision/failed-goal tests pass (63 total).
Release CI and installed operation have not been tested for this patch.
