# V2ADR-071 - Market maximum, explicit export bonus and advanced settings

Status: Accepted scope by Alex on 15 November 2026; implementation verification recorded separately.

## Authority and rollback

Alex authorized the first implementation phase after offline research: correct the
trade maximum, account for the Zonneplan bonus, expose maximum and wear in advanced
settings, retain the current MEP basis. HEMS 2.0.0-dev.339 is the new rollback
baseline. Published repository baseline: `68503d888892a132febd1faa936809700e10466a`.
The complete 1179-file source snapshot was verified against Git blob identities
and archived before editing. Earlier frozen ADR text is not rewritten.

## Scope

The existing capacity percentage is a maximum of usable battery capacity per
delivery-day assignment, as ADR-019.4 already states. Candidate Generation may
construct smaller volumes up to the effective cap. Each volume has its own
energy-weighted fictitious import reference (ADR-019.2), physical simulation and
known comparable recovery (ADR-019.6). The existing Evaluation selects; neither
the UI nor Store chooses an economic winner. Representative volume enumeration
is deterministic and bounded, not a claim of a global continuous optimum.

Zero disables new trade, including legacy generation and waiting unbound
assignments. It does not silently cancel a committed/started route. A lower new
setting also bounds new candidates; a higher setting cannot expand an existing
assignment's frozen day budget. Revisions/restarts never create a second budget.
The one-assignment/day, post-main/before-midnight and recovery contracts remain.
Main charging, minimum SOC, genuine completion evidence, protected PV choice
(ADR-037.27), builder, command adapter and execution ownership remain unchanged.

## Tariff and evidence ownership

Zonneplan bonus is an explicit configurable policy: 10% of positive market price
plus the existing export addition, during sunrise-to-sunset, limited by 7500 kWh
annual export. Energy-tax credit is never part of the bonus basis. PV and battery
export use the same policy. Import/saldering meanings otherwise remain unchanged.
It is not a flat rate increase: the annual cap depends on the candidate's export.
Each scenario starts from the same immutable observed allowance. Counterfactual
scenario export never consumes the actual measured annual budget.

The canonical bonus input carries policy, installation location/timezone,
explicit user-provided annual export anchor and timestamp, remaining allowance,
raw measurement lineage, coverage and status. An absent annual anchor is unknown,
not zero. No user's temporary saldering balance or home location is hardcoded.
Only validated raw grid-export measurements may extend the anchor. Financial
observer estimates, filled gaps, dashboard totals and NOM counterfactuals are
not planner inputs (ADR-037.19/.26). Any allowance deduction for an unobserved tail
must be explicitly conservative, bounded by known physical export capability.

Input preparation owns those facts; the shared tariff/settlement implementation
owns bonus calculation; Candidate/Outcome Production calls it; Evaluation chooses.
The passive financial ledger uses the same policy for measured intervals.
Unavailable evidence leaves bonus unproven and visible without blocking the
ordinary base-tariff planner. Activation/configuration changes cannot invent
historical bonus receipts. The UI only projects settings and producer evidence.

## Settings and compatibility

The canonical UserRuleProfile owns the fractional maximum and wear coefficient.
Existing configured wear is migrated, not reset to a new default. Wear can be
zero; validation rejects negative/nonfinite/boolean values. Changes apply
prospectively, with their time recorded; old measured discharge keeps its rate.
Advanced settings share the existing validated API and persistence path. Setting
changes request existing recalculation; they do not reset commitments/day goals.
Additive optional persistence fields retain the existing schema where compatible
so dev.339 can read the stored records on rollback.

Bonus is inactive until explicitly configured. Location and annual export anchor
are required to substantiate daylight and remaining allowance; status explains
missing evidence. This avoids assuming an unused annual allowance on upgrade.

## Deferred

Five-position slider, trade-priority weighting, multiple trade opportunities,
morning admission, extra night purchase strategies, changed PV forecast basis,
and a separate planner are outside this phase. No release or live change is
authorized by this implementation request.

## Required evidence

Smaller profitable volume where full maximum fails; 37.5% and zero; lower/higher
setting with frozen assignment; closed assignment continuity; bounded resource
cost. Bonus tests cover sign, solar boundaries, tax exclusion, annual cap,
year transition, missing raw evidence, candidate-order independence and repeated
overlapping observation/restart. Settings persist/reload and preserve old fields;
prospective wear does not reprice history. Integrated financial/pipeline tests,
baseline replay, source diff and previous-loader compatibility complete the check.
