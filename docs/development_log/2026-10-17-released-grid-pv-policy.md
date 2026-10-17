# PV-aware mode after grid-charge reduction

Alex approved this focused correction after installing HEMS dev.301. Baseline
main: 300cd7a25a51724a08d9dee21cadcac6fddd3db9. The initial repair was local; Alex subsequently requested release dev.302.

The September 15 rule unconditionally retained NOM in freed grid slots to keep
PV capture available. In the October 17 diagnostic replay, all eight released
night quarters have zero PV under lower, central and upper. NOM and household
support only produce identical physical intervals and terminal SOC 61.506923%.
Standby changes the energy balance, so it is not substituted.

V2ADR-064.8 replaces unconditional NOM with a selected-PV-surplus rule. The
feasibility trial, retained challenger and market-revision seed share one helper;
the simulator exposes its existing PV basis selection without changing its
calculation. Total demand includes EV load, so PV already consumed by the EV
cannot be counted as available battery surplus. Exact incumbents and unrelated
owned segments remain unchanged. Existing stored NOM requires a newly admitted
plan or explicit recalculation; there is no in-place plan mutation.

Regression-first: the configured lower and midpoint cases failed against dev.301
because they selected NOM despite insufficient/zero surplus. Central and upper
cases retain NOM where their forecasts exceed demand. The existing full-pipeline
test now expects discharge-only for its zero-PV freed slots while retaining
winning-path lineage. The new baseline cases include battery-excluded demand.

Verification: 32 mode/simulator/window tests pass. Future-grid and PV optimisation
tests also pass; the first intermediate run's single failure was the old explicit
unconditional-NOM expectation, updated to the accepted rule and rerun green.
Ruff passes for both modified source modules and the test; mypy passes for both
source modules. Diagnostic replay and market comparison results follow below.

Diagnostic replay passed: canonical winner plan-5b04d9c92d8a9b0f retains grid charge 04:15-05:45 Amsterdam and EUR 0.10463215744 improvement. Released intervals 02:30-04:15 and 05:45-06:00 now use balance_discharge_only. The independently retained 06:00-07:15 NOM interval is outside the removed grid window and remains unchanged; this is not a global NOM cleanup. No live plan or release was changed.

Final market-regression suite: 9 passed in 410.64 seconds, including keep/shorten/remove economics, recovery horizon and full-pipeline goal preservation. All selected verification is complete. Implementation remains local and unreleased.

Release authorization: Alex requested publication at 19:29 Europe/Amsterdam.
HEMS 2.0.0-dev.302 will be published via PR and green CI from unchanged main.
Energy Devices remains 0.4.0-dev.9. Installation and live verification are separate.

Initial release CI: 2213 passed, 1 skipped, one obsolete unconditional-NOM
expectation in the missing-PV/net-balance pipeline regression. The fixture
predicts zero PV in the released intervals. Its expected primitive now follows
V2ADR-064.8, with an added zero-PV assertion; all goal, provenance, running-owner
and repeat-evidence assertions remain. No production change was needed.
