# V2ADR-057 — Measured-PV charge admission and plan visibility

Status: Accepted

## Context

MEP can schedule an explicit grid-supported acquisition window while NOM later
proves able to reach the storage target from measured PV progress. Conversely,
when actual PV trails the selected forecast, suppressing that acquisition would
put the target at risk. The Zendure capability evidence also contains both the
manual signed-power mode and the integration-configured maximum mode for the
same generic power primitives, so an unqualified translation is ambiguous.

## Decision

MEP remains the sole planner and its selected path remains unchanged. At the
execution-primitive admission boundary, an explicit charge request is withheld
only when all of these facts hold:

- the device is currently in `Nul op de meter`;
- measured-PV feedback has promoted every remaining interval in the acquisition
  window to the central forecast lane;
- lower-lane PV surplus after expected household load and conservative storage
  efficiency reaches the configured maximum SoC target.

Missing evidence, a lagging actual-PV lane, or insufficient projected energy
leaves the approved grid-supported charge request executable. The boundary
records `measured_pv_progress_covers_grid_charge` when it withholds the request.

For `charge_at_power` and `discharge_at_power`, the adapter selects the unique
mapping with `integration_configured_maximum`: `Snel opladen` or
`Snel ontladen`. PicoT does not send an explicit power value to Zendure.

The price timeline shows every plan primitive and overlays the projected SoC.
NOM is green, grid import is red, export/trade is grey, and household-support
discharge uses a dark-green dashed SoC segment. The current measured SoC is the
anchor point; future points are explicitly projections from the chosen plan and
the canonical PV/load lanes.

## Consequences

The execution boundary can preserve NOM without creating a second planner or
rewriting MEP's economic decision. Diagnostics expose why a due grid command
was withheld. Underperforming PV remains a negative test: it must not activate
the gate. The dashboard makes both the chosen operating layer and its expected
storage trajectory visible against prices.
