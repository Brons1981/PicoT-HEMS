# V2ADR-072 - Four active strategy positions on the existing MEP basis

Status: Accepted scope by Alex, 15 November 2026. Local implementation only.

## User decision

After V2ADR-071, Alex chose to implement the settings control first: four active
positions, with the fifth pure-trading position visible but not selectable until
the separate expanded trading strategy is implemented. Dev.339 remains the
rollback baseline. Existing frozen ADR text is not changed.

## Explicit mapping

The separate advanced ceiling C is between 0 and 100 percent of usable capacity.
The server-side mapping layer translates the position into one effective user
rule boundary. It does not calculate financial outcomes, change objective weights
or select a route. This is the explicit hard-boundary part of the user choice,
consistent with ADR-018's priority of user rules over soft preferences.

| Position | Label | Effective trading maximum | Example C=37.5% |
|---|---|---|---|
| 0 | Zelfverbruik | 0 | 0% |
| 1 | Meer zelfverbruik | C/3 | 12.5% |
| 2 | Gebalanceerd | 2C/3 | 25% |
| 3 | Meer handel | C | 37.5% |
| 4 | Handel | Unavailable in this increment | Not selectable |

Changing the slider does not change Solcast selection, forecast adjustment,
wear, profit thresholds, saldering, bonus policy, reserve, house-load forecasts
or the existing daily charge algorithm. Self-consumption disables new market
routes while retaining existing economic PV-charge timing and standby behavior.
It does not promise a different plan when no trade is profitable.

The canonical user profile owns position, ceiling and revision. Its public
projection includes the mapping version, factor and effective maximum. The UI
does not own the arithmetic. Planning input records the exact profile revision
and immutable setting even when the market rule is absent at zero capacity.

## Persistence and migration

The old maximum_trading_soc_percent field retains its meaning as the effective
maximum. This allows dev.339 to read the records without treating the ceiling as
the active maximum. Additive position/ceiling fields preserve schema 2.

Existing maxima up to 66 2/3% migrate to Gebalanceerd with a ceiling of 1.5 times
the maximum, preserving the active value (25% becomes 25% with a 37.5% ceiling).
Higher legacy maxima migrate to Meer handel with the same ceiling; inventing a
ceiling above 100% or silently reducing the old maximum is not allowed. An old
client's changed effective maximum is migrated by the same rule; an unchanged
legacy value preserves the current position and ceiling. Conflicting legacy and
new strategy parameters in one request are rejected.

## Replanning and lifecycle

The slider sends a position-only update immediately; it cannot accidentally save
unsubmitted advanced edits. Rapid movements serialize requests and retain the
latest queued choice. Failure restores the last confirmed visible preference.

Runtime serializes profile/policy updates against an active calculation with the
existing planning barrier, then wakes the existing replanning path. A settings
response confirms the accepted revision and requested recalculation, not that a
replacement plan has already completed. A long calculation can delay acceptance.
Fresh planning input carries the new revision. The regular dashboard continues
to show planning results and commitments.

There is no deletion or reset of commitments, main-charge goals or day budgets.
ADR-019 and ADR-037 route admission, execution, recovery and protected PV-choice
contracts remain effective. Moving to zero prevents new trade; already bound
routes retain their existing lifecycle. Increasing a slider value cannot enlarge
an already frozen daily assignment. Evaluation, Builder, Store and adapters keep
their existing responsibilities.

## Deferred

Pure trading, multiple market opportunities, morning trade admission, new
night-purchase strategies and slider-dependent financial weighting remain outside
this increment. No publication or installation is included.
