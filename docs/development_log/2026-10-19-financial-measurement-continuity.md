# Financial measurement continuity and valid derived results

## Approved outcome

Complete derived financial results are valid display results without an exclamation
mark or approximation prefix. Derivation remains disclosed in the evidence panel.
Missing evidence continues to receive a warning; historical unreviewed results keep
their separate status. This does not change market admission or financial objectives.

## Confirmed defects

- Household observations were persisted by the normal poll wrapper, but not by
  execution refreshes during planning. On 19 October, a fresh 13:39:43 local capture
  fell between persisted 13:36:36 and 13:42:04 observations.
- Reconstruction consumed a diagnostic list limited to twenty gaps and skipped
  household inference when additional gaps were omitted. The retained measurement
  archives contain 22 household coverage gaps on 18 October and 24 on 19 October.
- An unresolved open household quarter could suppress all earlier valid results.
- The UI used the same warning marker for complete derived values and missing values.

## Ownership and changes

The shared live input capture owns observation/rejection persistence, including
planning refreshes. Main polling does not persist those captures a second time.
Write errors retain existing non-blocking logging behavior.

Coverage analysis can explicitly request every gap; diagnostics retain their bounded
default. Financial inference uses the complete analysis while preserving power,
duration, uncertainty, nonnegative-energy and price-coverage requirements. It does
not alter raw observations, authoritative battery inventory or planner inputs.

If only the unfinished household quarter prevents completion, the observer may
publish a common shorter period for all financial amounts. It uses the closing SOC
at that boundary, records the pending period, and retains the displayed end time.
Actual PV, grid or battery coverage failures are not hidden by this rule. An older
incomplete estimate for the same observation horizon cannot block replacement by
the valid closed-quarter result.

The UI treats available and complete estimated values as valid. Derivation is still
visible in the evidence panel. The separate forward estimate of stored battery
value remains an estimate, not a reconstructed measured financial result.

## Verification

Regression coverage includes more than twenty gaps, real source failure beyond the
twentieth gap, open-quarter handling, earlier/current source outages, persisted old
incomplete estimates, exact-once live persistence, write failures, complete derived
weeks without alerts and missing days retaining alerts. The real Node renderer is
used for UI assertions.

Integrated verification: 153 tests passed; Ruff passed on all changed Python files;
mypy passed on six changed backend modules with the Linux deployment platform.
Native Windows type checking reports pre-existing Linux-only OS/resource APIs in
unmodified passive-history/calendar modules.

Offline replay used `picot-diagnostics - 2026-10-19T191428.993.zip`, stored tariffs,
physical settings and measured histories against a copy of the ledger:

| Date | Result | Through (Amsterdam) | Net battery value | Net PicoT value |
| --- | --- | --- | --- | --- |
| 18 October | Complete derived | 19 October 00:00 | EUR 0.6520 | EUR -0.5250 |
| 19 October | Complete derived | 19 October 19:00 | EUR -1.0554 | EUR -1.7706 |

Original daily amounts and battery inventories were compared unchanged after replay.
The live Home Assistant ledger was not modified. The existing passive observer
recomputes today/yesterday after installation; no extra historical migration or
planner authority is introduced.
