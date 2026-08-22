# V2ADR-054 — Canonical Energy Ledger and Market Actions

Status: **Accepted for PicoT v2 rebuild**

## Context

ADR-015 already defines vendor-independent explicit charge and discharge
primitives. ADR-030 and ADR-031 require complete household Energy Paths, while
ADR-032 requires comparable Candidate Outcomes. ADR-037 permits grid-supported
storage charging when it is required by the household path or economically
shifts otherwise unavoidable import. V2ADR-050 extends Candidate construction
to timed delegated and explicit-power storage control.

These decisions do not yet define the complete interval ledger needed to
simulate grid charging, storage discharge or discretionary market trading. The
current projected balance has one aggregated `planned_grid_energy_wh` value.
It cannot prove whether grid energy served household demand or charged storage,
whether storage served the household or was exported, or whether conversion
losses and financial settlement were counted exactly once.

The generic Evaluation Engine can compare a financial objective supplied by an
outcome producer, but no accepted contract currently derives that outcome. A
dynamic-trading objective name is not permission to trade and is not a trading
policy.

PicoT therefore needs one canonical energy-accounting and settlement contract
before grid charge, grid discharge or market-trading Candidates are added. The
contract must extend the accepted pipeline rather than create a price planner,
battery planner or second simulation route.

## Decision

PicoT v2 represents every simulated household Candidate with one immutable,
interval-aligned `HouseholdEnergyLedger`. The same ledger is used for PV-first,
reserve-first, grid-supported and discretionary market Candidates.

Candidate simulation owns physical energy allocation and ledger production.
Financial settlement consumes the completed physical ledger and immutable
tariff evidence. Candidate Evaluation compares the resulting immutable
outcomes according to the active Planner Strategy. No later stage may
reallocate energy, recalculate economics or reinterpret a source policy.

## Canonical interval grid

The ledger uses the canonical planning intervals from ADR-017, initially 15
minutes, over the complete rolling horizon. Every interval is timezone-aware,
non-overlapping and contiguous where canonical input evidence is available.

Energy values are non-negative watt-hours. Direction is expressed by the field
name, never by a hidden sign convention. Power may be retained as evidence or
an execution request, but physical and financial accounting uses interval
energy.

## HouseholdEnergyLedgerInterval

Each interval exposes at least these physical flows:

- `pv_to_household_wh`;
- `pv_to_storage_input_wh`;
- `pv_to_grid_wh`;
- `grid_to_household_wh`;
- `grid_to_storage_input_wh`;
- `storage_to_household_output_wh`;
- `storage_to_grid_output_wh`;
- `storage_charge_loss_wh`;
- `storage_discharge_loss_wh`;
- `unserved_household_energy_wh`;
- `curtailed_pv_wh`;
- `storage_energy_at_start_wh`;
- `storage_energy_at_end_wh`.

The interval also preserves:

- canonical household-load energy and known committed demand;
- canonical usable PV energy;
- applicable storage and grid capability references;
- charge-source and discharge-destination policies;
- confidence components and method versions;
- all physical evidence identifiers;
- the Candidate and Energy Path lineage.

Unavailable evidence remains unavailable. It is not represented as zero.

## Conservation invariants

Every simulated interval must satisfy these equations within one explicit,
versioned numerical tolerance used only for floating-point validation:

```text
usable_pv_wh
= pv_to_household_wh
+ pv_to_storage_input_wh
+ pv_to_grid_wh
+ curtailed_pv_wh

grid_import_wh
= grid_to_household_wh
+ grid_to_storage_input_wh

storage_charge_input_wh
= pv_to_storage_input_wh
+ grid_to_storage_input_wh

storage_energy_added_wh
= storage_charge_input_wh
- storage_charge_loss_wh

storage_energy_removed_wh
= storage_to_household_output_wh
+ storage_to_grid_output_wh
+ storage_discharge_loss_wh

storage_energy_at_end_wh
= storage_energy_at_start_wh
+ storage_energy_added_wh
- storage_energy_removed_wh

household_demand_wh
= pv_to_household_wh
+ grid_to_household_wh
+ storage_to_household_output_wh
+ unserved_household_energy_wh

grid_export_wh
= pv_to_grid_wh
+ storage_to_grid_output_wh
```

The implementation must define whether an adapter reports battery-side or
AC-side power and normalize it before ledger construction. Conversion losses
may never be inferred twice from both power evidence and an efficiency factor.

Negative energy, unexplained creation or disappearance of energy, simultaneous
contradictory flows prohibited by a capability, or storage outside its
effective limits makes the Candidate physically invalid.

## Storage conversion contract

The atomic storage Capability Snapshot must expose, where required:

- maximum charge input power;
- maximum discharge output power;
- minimum controllable power and power step per direction;
- charge efficiency or a versioned charge-loss model;
- discharge efficiency or a versioned discharge-loss model;
- minimum and maximum usable storage energy or SoC;
- whether simultaneous charge and discharge is prohibited;
- delegated-mode power semantics and enforceable source/destination behaviour;
- freshness, confidence and evidence references.

Charge and discharge limits are directional and may not be replaced by one
assumed symmetric maximum. Missing required capability or loss evidence
excludes the affected explicit-power or market Candidate. PicoT does not invent
a default efficiency, power or usable capacity.

## Grid-interface and contract capability

The atomic grid Capability Snapshot and energy-contract input expose, where
applicable:

- maximum permitted import power;
- maximum permitted export power;
- whether battery-origin export is permitted;
- whether simultaneous import and export is prohibited;
- phase or connection limits governed by ADR-029;
- market interval and settlement timezone;
- immutable tariff schedule reference and contract version;
- freshness, availability and confidence.

A detected price is not proof that grid import, export or battery trading is
contractually permitted.

## Source and destination policies

Execution intent and energy-source permission remain separate.

Charging supports explicit policies with these semantics:

- `PV_ONLY`: no grid energy may be attributed to storage;
- `PV_PREFERRED_GRID_ALLOWED`: PV surplus is allocated first and only the
  justified remainder may come from grid;
- `GRID_ALLOWED_FOR_REQUIREMENT`: grid energy may satisfy a named storage
  requirement under ADR-037, while available PV remains accounted for in the
  complete household path;
- `GRID_ALLOWED_FOR_MARKET_ACTION`: grid energy may charge storage only as part
  of a complete valid discretionary market cycle.

Discharging has a separate destination policy:

- `HOUSEHOLD_ONLY`: storage may reduce household import but may not be exported;
- `HOUSEHOLD_PREFERRED_GRID_ALLOWED`: household demand is served first and
  remaining explicitly allocated energy may be exported;
- `GRID_ALLOWED_FOR_MARKET_ACTION`: export is permitted only as part of a
  complete valid discretionary market cycle.

These are Core semantics. Enum names may vary during implementation, but no
policy may combine requirement charging and discretionary trading into an
ambiguous generic `grid_allowed` value.

A primitive never grants source or destination permission by itself.
`CHARGE_AT_POWER` does not imply grid charging and `DISCHARGE_AT_POWER` does not
imply grid export.

## Energy-contract and tariff schedule

PicoT introduces an immutable, versioned `EnergyContractSnapshot` as Planning
Input. For every settlement interval it exposes the independently applicable
components of:

- commodity import price;
- commodity export price or remuneration;
- variable supplier surcharge or discount;
- energy tax and other per-kWh import charges;
- per-kWh export charges or deductions;
- applicable VAT treatment;
- fixed fees only when a Candidate can actually change them;
- imbalance, transaction or trading fees where applicable;
- settlement or netting rule identifier;
- validity interval, source timestamp, confidence and evidence.

Values are stored in their native contract components and combined by one
versioned settlement producer. Prices described as tax-inclusive may not have
tax added again. Fixed unavoidable subscription costs are excluded from
Candidate comparison because all Candidates incur them equally.

PicoT does not infer future legal or settlement rules from a calendar date.
Current and future tariff regimes, including changes to netting or export
compensation, require explicit versioned contract evidence.

## Financial settlement outcome

For each completed physical ledger, one settlement producer derives at least:

- total grid-import energy and cost;
- total grid-export energy and revenue or cost;
- net energy settlement result;
- storage conversion-loss cost;
- variable transaction and supplier charges;
- battery-use cost where a configured, accepted wear model exists;
- gross and net market-cycle result;
- settlement confidence and complete tariff evidence.

The financial objective uses one declared direction and unit across all
Candidates, normally net household financial result in EUR with
`HIGHER_IS_BETTER`. A cost representation with `LOWER_IS_BETTER` is also valid
only when used consistently for the complete Candidate set.

Evaluation does not calculate or repair these values. The dashboard displays
the immutable outcome and may not recompute profit from rounded prices.

## Necessary grid charging

Grid-supported acquisition for a `StorageEnergyRequirement` is a household
reliability and cost-shifting action, not market trading.

Candidate Generation may create it only when:

- the named requirement and deadline are explicit;
- PV-only feasibility and recoverability have been evaluated;
- grid use is justified under ADR-037;
- the source policy explicitly permits the required grid contribution;
- the complete ledger respects target, reserve, connection and capability
  limits;
- the Candidate remains complete through the planning horizon.

The planned grid energy is limited to the requirement shortfall after canonical
PV, household demand, losses and existing commitments are accounted for. Free
battery capacity alone is never a reason to grid-charge.

## Discretionary market action

Dynamic trading is an optional user objective. A non-zero objective weight or
enabled setting permits Candidate construction but never commands a trade.

A market Candidate contains a complete linked cycle:

1. an explicitly sourced acquisition interval;
2. storage retention over time with applicable standing losses when modelled;
3. an explicitly destined household-support or grid-export interval;
4. preservation or restoration of every protected household reserve and active
   commitment;
5. the complete physical ledger and financial settlement through the horizon.

An isolated cheap charging segment or high-price discharge segment is not a
valid market Candidate.

The complete cycle is eligible only when:

- every hard household requirement remains satisfied;
- the user-configured trading permission and maximum trading SoC/capacity are
  respected;
- import, export and battery-origin-export permissions are proven;
- charge and discharge power, energy, efficiency and storage limits are known;
- a complete recovery path exists after discretionary discharge;
- net expected benefit exceeds all variable import cost, lost export value,
  conversion loss, transaction charges, configured battery-use cost and the
  explicit user minimum-profit margin;
- confidence meets the explicit trading eligibility policy;
- no hidden tolerance turns an unprofitable or equal result into a trade.

The minimum-profit margin is a visible user or system policy input. It is not
implemented as a price-window widening margin and does not alter forecast
prices.

Where discharge only avoids later household import, the benefit is the avoided
applicable import cost. Where discharge exports energy, the benefit is the
applicable export settlement. The same stored watt-hour may not receive both
benefits.

## Candidate families and bounded construction

Candidate Generation constructs a small deterministic set of meaningful
complete alternatives, including where applicable:

- baseline/reserve-first;
- PV-only acquisition;
- grid-supported requirement acquisition;
- household-import avoidance by stored-energy discharge;
- complete discretionary charge/discharge market cycles.

It does not enumerate arbitrary combinations of every interval. Opportunity
windows provide evidence for representative Candidate construction under
ADR-024, ADR-031 and ADR-036. Evaluation alone selects among the constructed
complete paths.

Necessary grid charging and discretionary trading must remain distinguishable
in Candidate family, purpose, source/destination policy and explainability.

## Priority and reserve boundary

Physical validity and hard household requirements are evaluated before
optimisation objectives. Energy reserved for household demand, configured
minimum SoC, known commitments or recovery obligations is unavailable for
discretionary trading.

Trading may use only the explicitly calculated discretionary storage envelope.
The user-configured trading SoC limit constrains that envelope; it does not
replace the household reserve calculation.

An active necessary acquisition commitment may be replaced only through the
material replanning rules of V2ADR-052. A discretionary market action never
silently interrupts a necessary household commitment.

## Confidence

Physical-flow confidence follows V2ADR-053 and preserves interval-local source
components. Settlement confidence additionally includes tariff and contract
confidence. Market-cycle confidence is derived from all intervals and
capabilities required by both sides of the cycle; it is not copied from one
price point or artificially increased to make a trade eligible.

Forecast uncertainty affects eligibility and outcome confidence, not physical
energy quantities through an undocumented multiplier. Any conservative bound
used for trading must be explicit, versioned and shown in the outcome.

## Explainability

Every Candidate and selected plan exposes at least:

- whether the action serves a household requirement or discretionary trade;
- start and end of every linked charge, hold and discharge segment;
- energy source and discharge destination;
- expected storage energy before and after each action;
- household reserve before and after the complete path;
- import energy/cost and export energy/revenue;
- charge loss, discharge loss and configured battery-use cost;
- gross benefit, total variable cost, minimum required margin and net result;
- price, tariff, PV, household, storage and capability evidence;
- confidence components and limiting component;
- decisive Evaluation step and complete lineage.

For a long charging window, PicoT also exposes the cumulative required energy,
available source energy and remaining acquisition after every interval. The
window duration must therefore be explainable from energy need and physical
availability rather than a fixed duration.

## Runtime and adapter boundary

The Winning Energy Path converts unchanged under ADR-033. The Execution Engine
validates the due segment and current capability but does not reconsider market
economics.

Live execution of grid charging or grid export is prohibited until the Device
Adapter proves:

- the relevant generic primitive and directional power semantics;
- enforceable charge-source or discharge-destination behaviour;
- idempotent command dispatch and acknowledgement;
- observed-power and completion semantics;
- manual override, fallback, reset and recovery behaviour;
- safe compliance with current connection and storage limits.

Observer-only simulation and outcome comparison may precede live authority.
Vendor-provided dynamic-trading modes remain excluded because they would move
planning and settlement decisions outside PicoT Core.

## Failure behaviour

PicoT fails closed for the affected action when required energy, capability,
tariff, permission or settlement evidence is missing, stale or contradictory.
It may still construct unaffected baseline, PV-only or necessary household
Candidates.

Failure to construct a market Candidate never prevents ordinary household
planning. A settlement or trading-data failure cannot authorize speculative
grid charge or export.

## Verification

Tests must independently prove at least:

- interval and horizon energy conservation;
- no grid-to-storage flow under `PV_ONLY`;
- no storage-to-grid flow under `HOUSEHOLD_ONLY`;
- directional limits and efficiencies are applied exactly once;
- necessary grid energy never exceeds the requirement shortfall;
- reserved household energy is unavailable to trading;
- a charge-only or discharge-only fragment is rejected as an incomplete trade;
- a complete profitable cycle is eligible only after every cost and minimum
  margin;
- equal or negative net benefit does not trade;
- import avoidance and export revenue are never both credited to one watt-hour;
- tariff-inclusive components are not counted twice;
- identical immutable inputs produce identical ledgers and outcomes;
- generic Evaluation selects only from supplied complete outcomes;
- dashboard explanations reproduce stored values without recalculation;
- observer-only market planning cannot dispatch a live command.

Golden reference scenarios cover sunny, cloudy, no-PV, negative-price,
high-export-price, low-confidence, insufficient-reserve, connection-limited and
restart-during-cycle cases.

## Non-goals

This V2ADR does not:

- authorize live grid charging, discharge or export;
- define a Zendure-specific trading strategy;
- delegate planning to a vendor dynamic mode;
- create a second battery, price or market pipeline;
- guarantee profit from forecast prices;
- define a universal battery wear price;
- assume future legal or tariff changes;
- make historical ADR-040 through ADR-047 architectural authority.

## Relationship to the reliable architecture baseline

- ADR-015 remains authoritative for generic Execution Primitives.
- ADR-017 remains authoritative for the rolling horizon and complete path.
- ADR-023, ADR-024 and ADR-031 remain authoritative for Opportunities as
  evidence and bounded Candidate construction.
- ADR-025, ADR-026 and ADR-032 remain authoritative for transparent objective
  comparison and winner selection.
- ADR-027, ADR-029 and V2ADR-052 remain authoritative for commitments,
  switching, material replanning and connection limits.
- ADR-030 remains authoritative for atomic Capability Snapshots and Energy
  Paths.
- ADR-033 remains authoritative for unchanged conversion into Execution Plans.
- ADR-035 remains authoritative for the accepted adapter boundary.
- ADR-036 remains authoritative for canonical price Opportunities.
- ADR-037 remains authoritative for household energy requirements, PV-first
  feasibility and necessary grid-supported charging.
- ADR-038 and ADR-039 remain authoritative for storage and PV evidence.
- V2ADR-048 and V2ADR-049 remain authoritative for PV uncertainty and
  attenuation.
- V2ADR-050 remains authoritative for delegated versus explicit timed storage
  control.
- V2ADR-053 remains authoritative for traceable confidence propagation.
- Historical ADR-040 through ADR-047 are not incorporated as authority.

## Implementation order

1. Introduce immutable ledger, directional policy, energy-contract and
   settlement records with conservation validation and contract tests.
2. Replace the specialised PV-only projection with one observer-only canonical
   simulator for baseline, PV and necessary grid-supported Candidates.
3. Produce complete physical and financial Candidate Outcomes and route all
   winner selection through the generic ADR-032 Evaluation Engine.
4. Add necessary grid-charge Candidates without live dispatch and validate
   their outcome against golden reference scenarios.
5. Add complete discretionary market-cycle Candidates in observer-only mode.
6. Compare observer projections with actual household, storage and grid flows;
   record forecast and settlement deviations without rewriting original
   evidence.
7. Extend and prove adapter capabilities in separate test-backed slices before
   granting live grid-charge or discharge authority.
8. Remove the specialised delegated-storage evaluation route only after the
   canonical route proves equivalent PV behaviour and the new grid scenarios.

## Core principle

> PicoT selects one complete household Energy Path from one conserved physical
> ledger and one traceable settlement; necessary grid use serves household
> requirements first, while discretionary trading is allowed only as a complete
> profitable and recoverable cycle inside explicit user and capability limits.
