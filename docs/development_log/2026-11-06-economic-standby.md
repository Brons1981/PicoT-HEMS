# Economic standby and normal minimum SOC

## Requirement

Offer one connected deliberate standby block on cheaper quarters. Normal household support may reach the configured minimum SOC, after which existing reserve protection stops discharge. Compare grid supply against support followed by replenishment, including conversion losses; do not force standby simply to avoid reaching the floor. Explain the difference on the dashboard.

## Incident and cause

The dev336 diagnostic snapshot `snapshot-cbb0f0ae84127658` chose immediate standby until the next main window. Its cheaper support-first alternative differed by less than the existing one-cent financial equivalence margin. The switch count excluded the immediate transition from the observed discharge mode, incorrectly giving immediate standby one fewer switch. Earlier standby candidates were also driven by covering the entire bridge deficit.

## Repair

- Keep a normal-support reference that permits reaching the physical SOC floor.
- Generate connected low-price blocks by raising a price threshold; protected intervals break connectivity. This is a bounded candidate family, not an exhaustive search of all possible interval pairs.
- Admit at most one deliberate standby block before the next main window. For ordinary bridge repair, require a positive full-route cash benefit over support with equal final inventory. Existing market-revision recovery proof remains in force.
- Count the initial transition when current mode evidence is available and captured with the snapshot.
- Preserve protected main charging and trading actions and the existing minimum-SOC execution guard.
- Show support-until, projected/actual minimum SOC and next charging. Only report a standby saving when the full routes have equal horizon and final inventory and the action difference isolates one standby block. Otherwise state that the saving cannot be established.
- Preserve fresh operation status when restoring cached projection evidence.

A long standby block is still possible if justified economically; this change does not impose an arbitrary duration limit. A normal stop at the SOC floor is not an additional deliberate economic standby block.

## Diagnostic replay

The repaired planner selects `main-charge-candidate-0d4281ef5c9c1146` for the incident: support until 22:30 Europe/Amsterdam, followed by one standby block until 09:30. These times follow from that snapshot, not a fixed setting. No live installation was modified and no release was published for this repair.

The replay dashboard proves a full-route cost difference of EUR 0.0604948366 (about 6.05 cents): support then refill EUR 3.8003579723 versus the selected standby route EUR 3.7398631358, with equal final inventory. This is a forecast for the incident, not a guaranteed realized saving.

## Verification

- Integrated regression run: 123 passed; one newly added test had an incorrect EnergyPath attribute in its assertion. Corrected that test mapping and reran its complete four-test file: 4 passed. All 124 selected cases are covered by passing results.
- Dashboard-focused run: 71 passed; after the adjacent-support display adjustment, 10 focused tests passed.
- Ruff: all `src/picot` and changed tests passed.
- Mypy (Linux target): all 278 `src/picot` source files passed.
- Final diagnostic replay and narrative/financial evidence inspection passed.
- A broader check over legacy top-level `src` discovery utilities also exposed existing lint/type/dependency issues outside `src/picot`; these unrelated utilities were not changed.
