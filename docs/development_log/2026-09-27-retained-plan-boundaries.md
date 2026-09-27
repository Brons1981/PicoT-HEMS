# Retained plan boundaries after market removal

## Authorized scope

Alex approved the isolated repair on 27 September at 16:02 Europe/Amsterdam.
Baseline: dev.274, `21e7fd2f85f4b30849c63bb309feb608bf45c2b5`.
No release or live mutation is included. Operational fallback remains dev.268.

The frozen canonical contract, ADR-031/032 and ADR-019.5 require complete
remaining-horizon paths and faithful simulation of admitted execution intents.
The owning boundary is the independent daily reference adapter's physical
interval construction. Always include active plan segment boundaries, regardless
of whether a market binding remains. Do not fill real gaps or change modes,
financial scoring, market replacement policy, goals, persistence or dispatch.

## Incident and reproduction

Snapshot `snapshot-9004143813122512`, 2026-09-27 15:30:26 local, rejected the
continuous active plan `plan-7184a670745c110a` with
`retained_main_plan_has_a_schedule_gap`. The preceding revision removed the last
market binding. `_inputs` consequently omitted non-quarter plan boundaries.
The resulting intervals straddled the actual 15:42:35.565007 transition and two
later non-quarter transitions. The stored plan itself contained no gaps.

The preceding 15:27 revision followed material SOC change with an active extra
household load guard. Measured SOC fell from 98% to 94%; the dryer was reported
by Alex, not identified independently from appliance measurements.

## Verification

- Regression through `main_route_shortfalls`: continuous non-quarter transition
  fails before the repair with the exact incident exception; a real one-second
  gap is rejected before and after. Mode boundaries remain NOM then discharge.
- 55 tests passed: market failed goals/comparison/projection, independent daily
  adapter and retained pipeline evidence.
- 61 tests passed: architecture ownership, single planner architecture, active
  daily pipeline, bridge pipeline, load protection, horizon and plan recovery.
- Exact incident snapshot replay through CanonicalPipeline in a temporary store:
  `winner_selected`, `tie_break:grid_charge_duration`; previous schedule-gap
  fallback disappears. Restart reads the same plan; completed goals preserved.
- Ruff and diff whitespace checks passed. Mypy initially had an internal error
  with the existing cache; a separate fresh cache passed for the changed module.

Local evidence only; no installation or live verification. The next work items
remain financial measurement alignment, plain-language plan explanations and
investigation of NOM as the replacement for removed export. None is changed here.


Release dev.275: Alex heeft op 27 september 2026 om 16:13 Europe/Amsterdam
akkoord gegeven op publicatie van de geïsoleerde planovergangenreparatie via PR
en CI. Zie `docs/development_log/2026-09-27-retained-plan-boundaries.md`.
Financiële meetverwerking, planuitleg en NOM-vervanging blijven vervolgstappen.
Installatie en livecontrole volgen na publicatie.
