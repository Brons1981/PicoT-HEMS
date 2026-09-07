# V2ADR-065 — Single source-independent market-trade hourglass

Status: **Accepted**

Date: 2026-09-07

## Context

MEP accumulated separate route kinds for PV export, stored-energy export,
PV-plus-grid recovery and multi-day export chains. Those routes represented
the same economic choice repeatedly and coupled export admission to how stored
energy had been acquired or might later be restored. A correction in one route
could therefore suppress the canonical broad NOM window or create a new route
matrix and additional simulations.

The canonical daily planner already determines whether forecast PV can satisfy
the storage target and whether residual grid energy is needed. The market layer
does not need to reconstruct that decision.

## Decision

MEP has one optional positive-price market route: `grid_trade`. The name denotes
trade with the grid, not mandatory grid charging.

Candidate construction first receives one canonical native recovery path. That
path owns all NOM and grid-requirement intervals. The market route overlays one
bounded export hourglass on the best eligible export window and preserves every
native interval outside that export window unchanged.

Export energy is bounded once by:

1. projected stored energy at the export boundary;
2. the physical minimum SoC plus household and user reserves;
3. the configured maximum trading SoC fraction; and
4. storage discharge power and export-window duration.

Energy origin is not an admission dependency. A supplied storage inventory
remains observable for compatibility but cannot create a separate route or
change the export budget.

Recovery is one valuation, not a route family. On the conservative PV scenario,
MEP calculates one energy-weighted recovery price from the native path's actual
PV-to-storage and grid-to-storage input. PV contributes zero acquisition price;
grid input contributes its interval import tariff. This gives the same rule for
PV-only, mixed PV/grid and grid-only recovery without branching the route shape.

The effective export threshold is the weighted recovery price corrected for
round-trip efficiency, the configured trading margin and fixed wear. Candidate
Generation retains only the highest-value peak-anchored export hourglass that
meets that threshold and the minimum route result.

Every retained market route receives exactly one full scenario simulation.
Physical completeness and protected reserve remain mandatory. An optional
trade need not restore the native path's exact horizon-end SoC; that equality
would make energy source and recovery timing hidden route dependencies again.
Evaluation remains the sole authority that may select an admitted route.

Negative-price capacity preparation remains a separate `negative_capacity`
behavior because being paid to create storage room is a different market fact.

## Removed route kinds

The following overlapping route kinds and their parent-selection matrices are
removed:

- `pv_trade`;
- `pv_trade_grid_recovery`;
- `pv_surplus_export`;
- `stored_energy_export`; and
- `daily_export_chain`.

## Superseded clauses

For positive-price export, this decision supersedes V2ADR-058's separate
`stored_energy_export` candidate and V2ADR-059's linked grid-charge timing
matrix. Their commitment lifecycle, execution feedback, exact export-hourglass
boundary and peak anchoring remain valid. Negative-price capacity acquisition
also remains unchanged.

## Verification

Tests must prove that:

1. only `grid_trade` and `negative_capacity` market route kinds remain;
2. at most one positive-price trade is generated for the planning horizon;
3. a trade never contains its own charge window;
4. all non-export intervals equal the canonical native recovery schedule;
5. PV-only, mixed and grid-only input produce one weighted recovery price;
6. storage inventory origin cannot change the route;
7. every trade has exactly one assessment and respects protected reserve; and
8. no legacy route identifier remains in executable source or tests.

## Core principle

> MEP decides once whether available energy may be sold at a sufficient spread;
> the canonical planner owns how the battery is filled.
