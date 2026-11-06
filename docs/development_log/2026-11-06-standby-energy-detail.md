# Standby household energy and import cost

Show expected household demand, solar directly used by the household, grid household energy and its import cost for the evidenced standby block. Keep the full-route saving separate from the block's import cost.

Producer-owned physical interval flows and settlement import costs are carried as optional display evidence in projected states. The dashboard sums only exact contiguous intervals covering the standby block. Missing data, gaps, overlapping intervals, partial boundaries or grid battery charging suppress the block totals instead of inventing zeros or allocating costs. Negative import prices remain valid. Solar exports are excluded from household solar use. Optional fields preserve older record compatibility.

No candidate scoring, switching policy or execution behavior was changed. This does not address the separate initial-plan versus bridge-comparison inconsistency.

Verification: 49 focused aggregation, DOM rendering and cache tests passed. Ruff passed for all changed files. Linux-target mypy passed for all 278 PicoT modules. An initial test invocation failed to create temporary directories; it was rerun with the existing writable test temp location.

Replay of snapshot-f5900824e52226cf retained candidate main-charge-candidate-4067f057c6e81be4 and the EUR 0.0966476116 full-route saving. For 22:45 to 09:30 Europe/Amsterdam the new evidence reports 3.0905516 kWh demand, 0.14495 kWh directly used solar, 2.9456016 kWh grid energy and EUR 1.2479562 import cost. The block figures exclude later refilling and export revenue.

Prepared separately from dev.337; not released or installed.
