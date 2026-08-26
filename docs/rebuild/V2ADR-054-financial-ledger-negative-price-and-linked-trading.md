# V2ADR-054 — Financial Ledger, Negative-price Use and Linked Trading

Status: **Accepted**

Date: 2026-08-26

## Controlling decisions

PicoT records the financial result of the complete household energy system and
may plan grid acquisition and storage export only as complete, physically
linked daily routes. The validated independent daily-planner behaviour recorded
on 2026-08-25 remains frozen. This ADR adds financial accounting and downstream
execution authority; it does not add planner hysteresis or rewrite the daily
physical simulator, charge-window discovery, scenario admission or ranking.

The PV investment is already recovered and is excluded from investment
breakeven accounting. PV generation and its realised economic value remain part
of the system result. The battery investment basis is EUR 2,407.40.

## Separate financial views

The durable financial ledger exposes, without double counting:

- direct PV self-consumption value;
- PV export revenue or cost;
- storage/NOM value relative to the no-storage interval flow;
- necessary grid-charge optimisation value;
- incremental dynamic-trading result relative to the best non-trading daily
  route;
- import cost, conversion loss and battery throughput;
- theoretical battery wear at EUR 0.04917 per delivered kWh;
- total realised system cash result;
- battery-attributable realised cash result.

The PV investment never appears as an amount still to recover. Direct PV value
may contribute to the complete-system result but may not make the battery appear
to recover faster. Only battery-attributable cash value is compared with the
EUR 2,407.40 battery investment.

## Two breakeven contracts

### Investment breakeven

Battery investment breakeven occurs when cumulative battery-attributable
realised cash value reaches EUR 2,407.40. Before that point PicoT exposes the
remaining amount. After that point it exposes cumulative battery lifetime
profit. The planner does not become less strict after investment breakeven;
future replacement value and marginal wear still exist.

The investment graph does not subtract theoretical battery wear from realised
cash value because the complete acquisition price already represents that same
capital outlay. Wear is shown separately as a replacement reserve and remains a
planning cost.

### Action breakeven

Every optional acquisition or trading route exposes the exact price/value at
which its incremental result equals zero after import, export opportunity cost,
conversion loss, future replacement and incremental wear. A route at or below
action breakeven is not profitable merely because an individual market price is
negative or an evening export price is high.

Dynamic trading is admitted only when its complete incremental result relative
to the non-trading baseline is both:

- at least EUR 0.05 per delivered/exported kWh; and
- at least EUR 0.25 for the complete linked cycle.

Necessary grid charging for a proven household/storage energy deficit is not a
trading route and is not subject to these profit minima. It still selects the
least-cost complete feasible acquisition route.

## Negative-price semantics

Negative prices remain signed monetary values throughout ingestion, settlement,
planning, diagnostics and display. They are never clamped to zero.

PicoT distinguishes the signed all-in import tariff from the signed export
tariff. A negative wholesale price does not prove that all-in import is
negative. Grid consumption is financially rewarded only when the applicable
all-in import tariff is below zero.

The GoodWe inverter is currently shut down automatically by external Homey
control during negative-price periods. PicoT treats the resulting expected or
measured absence of PV as a physical input, not as a PicoT command. Future PicoT
PV-curtailment authority requires a separate capability and execution contract.

Known flexible loads may consume energy in a negative-price interval only when
their own capability, requirement and schedule are present. Washing, drying and
EV charging are not invented as demand before their integrations exist.

## Capacity preparation before a negative-price window

PicoT may deliberately create storage room before a negative all-in import
window. A capacity-preparation route is one complete linked route containing:

1. bounded storage discharge to household demand and/or grid export before the
   negative interval;
2. a proven future negative-price acquisition interval;
3. reacquisition of no more energy than the future interval can physically
   accept at the supported charge power, remaining capacity and RTE;
4. protection of every hardware minimum, planner reserve and future household
   requirement throughout the route;
5. complete settlement of the discharge value, future import value,
   conversion losses, foregone alternatives and incremental wear.

Storage may not be emptied merely because a negative price is forecast. The
maximum preparatory discharge is the minimum of:

- energy available above all protected requirements;
- storage room that the linked negative interval can refill;
- discharge energy physically executable before the interval;
- the volume for which the complete route passes the applicable financial
  admission rule.

The discharge interval itself need not have a high positive export price. It
may be less valuable or even mildly costly when the complete linked route still
exceeds action breakeven and the trading admission minima. All legs must retain
one cycle identity and energy lineage.

## Dutch tariff transition

Through 2026, import and export settlement use explicit contract evidence. PicoT
must not assume that grid-imported and re-exported energy receives net-metering
value unless that entitlement is proven.

From 2027:

- import remains the signed all-in tariff, including supplier addition,
  energy tax and VAT;
- export is the signed bare market price plus exactly EUR 0.02/kWh;
- import energy tax, VAT and supplier addition never create an export credit;
- PV stored for later household use is valued against avoided all-in import and
  its lost direct-export alternative;
- PV stored or shifted for export is compared with the export value at the
  original PV interval;
- only battery throughput additional to the non-trading route receives
  incremental trading wear.

## Execution boundary

The third planner is named **MEP — Markt Etmaal Planner**. The three temporary
comparison roles are explicit:

- the canonical planner is an observer-only historical reference;
- the frozen independent daily planner is the observer-only physical reference;
- MEP extends the frozen daily baseline with complete market, negative-price,
  grid-acquisition and storage-export routes and is the sole live planner;
- the add-on defaults `market_daily_execution_mode` to `live`, while both
  `canonical_execution_mode` and `live_pv_canary_mode` default to `observer`.

MEP may receive live authority only after the acceptance suite proves that the
frozen daily result remains semantically unchanged when no added market route
is decisive. A runtime guard must make simultaneous dispatch authority
impossible.

The three-planner comparison is temporary. It is retained through the planned
representative live household test, after which one explicit promotion decision
removes the unnecessary runtime planners. Frozen reference behaviour remains
available through regression tests and incident replays after runtime removal.

Selected intents map through the normal @gielz Zendure modes:

- `household_support_only` -> `Alleen slim ontladen`;
- `nom` -> `Nul op de meter`;
- `grid_requirement` -> `Snel opladen`;
- `storage_export` -> `Snel ontladen`;
- explicit safe idle -> `Standby`.

One started quarter-hour action is idempotent. The next interval is replanned
from measured state. Missing or stale telemetry, missing capability, incomplete
cycle lineage, user override, restart uncertainty or failed mode feedback blocks
new forced charge/discharge and falls closed.

## Dashboard

The separate **Financieel** tab shows realised facts independently from planner
forecasts. It includes cumulative and interval views for PV, battery and trading,
the EUR 2,407.40 battery investment line, investment breakeven, action
breakeven evidence, remaining battery investment, lifetime profit after
breakeven, theoretical wear/replacement reserve and explicit negative-price
benefit or cost.

Forecast financial outcomes are visibly labelled as forecasts and never added
to realised cumulative totals.

## Acceptance evidence

Before live release tests must prove:

1. the frozen daily planner regression results remain semantically unchanged;
2. negative import/export tariffs preserve their sign through settlement;
3. 2027 export equals bare market price plus EUR 0.02 and never contains import
   tax, VAT or supplier additions;
4. direct PV, PV export and battery-attributable value reconcile without double
   counting;
5. investment and action breakeven remain separate;
6. preparatory discharge cannot exceed linked refill capacity or protected
   energy;
7. incomplete and unprofitable linked cycles cannot dispatch;
8. exactly one planner owns dispatch authority;
9. `grid_requirement` and `storage_export` use only proven @gielz capabilities;
10. restart, stale evidence, missing feedback and user override fail closed;
11. realised financial state survives restart and remains bounded and
    diagnostically exportable.
