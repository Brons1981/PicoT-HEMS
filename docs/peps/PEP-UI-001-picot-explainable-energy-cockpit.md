# PEP-UI-001 — PicoT Explainable Energy Cockpit

- **Status:** Accepted
- **Type:** User-interface and data-architecture vision
- **Implementation:** Phased

## 1. Purpose

The PicoT Explainable Energy Cockpit is the primary long-term user interface for PicoT HEMS. It presents the home, its energy flows, external influences, forecasts, active assets and PicoT decisions as one coherent Energy Scene.

A user should be able to understand within seconds:

- what is happening now;
- what influences PicoT;
- which decision PicoT made;
- why PicoT made that decision;
- what effect the decision has;
- what PicoT is expected to do next.

## 2. Energy Scene

The cockpit is not primarily a collection of unrelated cards. The home is the visual centre. Around it are the grid, PV, battery, EV, major loads, weather and external services.

The long-term scene uses the PicoT **T** as a structural and explanatory element:

- the horizontal axis connects physical energy flows;
- the vertical axis connects external information, planning and controlled assets;
- their intersection represents PicoT's deterministic decision point.

## 3. Information layers

The cockpit shall support these layers, even when an early implementation only shows placeholders:

1. **External world** — internet, price source, weather services, Solcast and API health.
2. **Environment** — sun, clouds, rain, snow, day/night and seasons.
3. **PicoT** — planner, Runtime Monitor, Safety Layer, User Rules, active strategy and explainability.
4. **Home** — household load and internal energy flows.
5. **Assets** — battery, EV, heat pump, boiler and other flexible loads.
6. **Grid** — import, export and connection state.
7. **Planning** — current plan, selected windows, next evaluation and expected actions.

## 4. Sun and weather

The sun is not merely decorative. Its visual position should be derived from location, date and time. The sun arc therefore changes during the day and across seasons.

Weather may be shown as current conditions and forecast. Current facts and forecasts must remain visibly distinguishable.

## 5. Visual style and animation

The cockpit may be modern, lively and visually rich. Atmosphere and animation are intentional parts of the experience. The final cockpit may resemble a high-quality animated energy scene with a recognisable home, sun arc, weather, grid mast, battery, EV and flowing energy paths.

Animations may be informative or gently decorative. They are acceptable when they:

- strengthen the visual coherence of the Energy Scene;
- remain calm enough for continuous daily use;
- do not hide warnings or important values;
- never imply a physical flow or system state that does not exist;
- keep facts, forecasts and decoration distinguishable.

The governing principle is:

> Modern and visually rich, with truth and explainability as hard boundaries.

## 6. Explainability

Every relevant PicoT decision must be traceable to visible causes. The cockpit should be able to show cause-and-effect chains such as:

```text
More cloud forecast
→ lower expected PV
→ planner reserves battery capacity
→ less expected grid import this evening
```

or:

```text
EV connected
→ departure deadline known
→ cheapest valid hours selected
→ EV charging plan changed
```

## 7. Data architecture

The cockpit consumes structured semantic states rather than presentation-specific entity names. The target model includes, among others:

- `ExternalServicesState`
- `WeatherState`
- `GridState`
- `SolarState`
- `HouseState`
- `BatteryState`
- `EvState`
- `PlannerState`
- `PicoTDecisionState`
- `RuntimeHealthState`

Every relevant value should be able to carry:

- value and unit;
- source;
- source status;
- measurement or forecast timestamp;
- fact/forecast distinction;
- confidence where applicable.

The dashboard should consume PicoT-published semantic entities wherever possible. Direct reads from external integrations are temporary compatibility fallbacks only and must not become the long-term source of truth.

## 8. Technical-view chart pairing

The Phase 1 Technical View uses two aligned charts with the same day span and time axis:

1. **Energiestromen** — technical component behaviour over time, including grid power, PV power, battery power and, during validation, derived house power.
2. **Energiebalans** — the resulting split between self-consumption/self-supply, grid import and grid export.

This pairing is intentional: the upper chart shows cause, the lower chart shows result. Matching time ranges make it possible to correlate component behaviour with the resulting household energy balance without mental reconstruction.

The derived house-power line may remain available during validation and can be disabled or removed later when it no longer adds diagnostic value.

## 9. PicoT semantic colour language

The following colours are fixed semantic meanings across PicoT dashboards, reports and future applications:

- **Red** — energy imported from the grid.
- **Green** — self-consumption / self-supplied household energy.
- **Purple** — energy exported to the grid.

These colours describe energy origin or direction, not whether a decision is good or bad. For example, grid charging at a low price is still shown as red because the energy comes from the grid.

Additional stable meanings used in the Technical View:

- **Yellow** — actual PV production.
- **Orange** — PV forecast or planning/forecast context.
- **Grey** — neutral reference values and technical net overlays.
- **Blue** — derived or informational technical values where no stronger semantic energy-flow meaning applies.

A semantic colour must not change meaning between charts.

## 10. Explainable planner windows in the price chart

The price chart remains a factual quarter-hour price graph. PicoT may overlay selected planner windows to explain how the price data is used.

Only planner-selected quarter-hours are highlighted. The highlight colour shows the expected primary charging source, not the price level:

- **Yellow window** — battery charging is expected to be supplied primarily by PV surplus.
- **Red window** — battery charging is expected to be supplied primarily by grid import.
- **Mixed-source window** — a separate, explicitly defined mixed-source presentation may be added later.

Example: when sufficient PV is expected throughout the day, PicoT may select the cheapest contiguous window for charging from PV surplus, while higher-priced PV outside that window can be exported. Those selected quarter-hours are shown in yellow. In winter, the same type of selected charging window may be shown in red when grid energy is the expected source.

The final implementation may place small flow symbols below the selected window, such as:

```text
PV → battery
Grid → battery
```

A hover or detail view should show:

- quarter-hour start and end;
- price;
- planned action;
- expected primary energy source;
- deterministic planner reason.

## 11. Development phases

### Phase 1 — Technical View

A less visual dashboard that already follows the final information architecture. Its purpose is commissioning, live validation and learning which information deserves prominence.

The current Technical View includes:

- Energiestromen;
- Energiebalans;
- Solcast forecast versus actual GoodWe production;
- quarter-hour price history and forecast;
- current planner decision and source health.

### Phase 2 — Explainable Energy Cockpit

The complete visual Energy Scene with the home as centre, real sun arc, weather, animated energy flows, assets, external-service status and visual decision explanations.

## 12. Design statement

> The PicoT Explainable Energy Cockpit does not merely show the state of a home. It tells the complete energy story of that home—from sun, weather and market information to planning, physical energy flows and deterministic decisions—so the user can see what PicoT sees, understand why PicoT acts and anticipate what PicoT will do next.
