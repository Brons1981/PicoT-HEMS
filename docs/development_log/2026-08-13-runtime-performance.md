# Runtime Performance Investigation — 2026-08-13

## Context

During ADR execution-path recovery, live Home Assistant observation showed PicoT add-on CPU usage around 24.9% while RAM remained around 3.1%. Because PicoT was still observer-only/dry-run, this was treated as an open runtime-quality finding rather than deferred optimisation work.

## Measurement first

Add-on 0.1.55 introduced observer-only stage timing. It did not change planner, ADR, execution or control behaviour. A dedicated `sensor.picot_runtime_performance` measured:

- `base_evidence_ms`: 0.026
- `flow_observer_ms`: 0.018
- `canonical_pv_deviation_ms`: 0.010
- `snapshot_build_ms`: 41.050
- `actual_pv_integration_ms`: 2851.666
- `price_fetch_ms`: 5.700
- `adr037_planner_ms`: 2.153
- `tab001_mode_control_ms`: 0.007
- `total_composed_cycle_ms`: 2900.815

Actual-PV integration therefore consumed about 98.3% of the measured composed-cycle time. The planner itself was not the CPU bottleneck.

## Root cause

ADR-039 actual-PV integration requests only a short recent time range from `HistoryStore.iter_range()`, typically the current quarter plus a small boundary tolerance. The existing `HistoryStore.iter_range()` implementation nevertheless opened and parsed the complete durable `/data/picot_history.jsonl` file from the beginning for every range call.

With a five-second telemetry cadence this caused repeated full-history JSON decoding and timestamp parsing even though only recent GoodWe samples were needed. Runtime cost therefore grew with the total history file instead of with the requested range.

## Correct responsibility boundary

The issue belongs to the HistoryStore query layer, not to ADR-039, the Planner or a local actual-PV cache.

The optimisation must preserve these invariants:

- JSONL remains the durable source of truth;
- ADR-039 sample-and-hold and evidence semantics remain unchanged;
- `HistoryStore.iter_range(start, end)` continues to return the same logical range results;
- older history/export ranges remain available from durable persistence;
- restart behaviour remains deterministic;
- no planner, execution or vendor-control shortcut is introduced.

## Implementation — PR #121 / add-on 0.1.56

`HistoryStore` receives a bounded two-hour in-memory recent index.

- At process startup the recent index is rebuilt deterministically from persisted JSONL.
- On every normal `append()` the same persisted event is also added to the recent index.
- The index is trimmed to a bounded two-hour window.
- `iter_range()` serves a request from the recent index only when that index fully covers the requested start boundary.
- Older ranges fall back to the existing durable JSONL scan.
- JSONL remains authoritative persistence; the index is an acceleration structure only.

Focused tests cover startup rebuild, recent reads without repeated persistent rescans, and durable fallback for older ranges.

## Validation requirement

After deployment of add-on 0.1.56, live Home Assistant validation must compare the same `sensor.picot_runtime_performance` fields against the 0.1.55 baseline. In particular, `actual_pv_integration_ms`, `total_composed_cycle_ms`, and observed add-on CPU usage must be reviewed before the performance finding is closed.

No execution-path recovery step is considered invalidated by this optimisation because planner and control semantics are unchanged.
