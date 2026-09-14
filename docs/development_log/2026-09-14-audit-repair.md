# 2026-09-14 — audit repairs and remaining decision

Alex authorized implementation of the combined code/ADR audit list, including
Recorder transport and missing snapshots. Base: cbb5d667 (dev.259). Changes remain
local: no commit, push, release, deployment, HA configuration or device writes.
Existing untracked September 12 replay material is untouched.

## Change contract and ownership

The first bad boundaries are (1) source-option resolution versus live binding,
(2) Monitor admission versus signature-based invocation, (3) native daily
commitments versus their observation producer, (4) approved segment versus
primitive request, (5) transport result versus runtime outcome, (6) canonical
records versus diagnostic/projected records. Controlling contracts are the frozen
pipeline and ADR-015/016/017/024/026/027/028/032/033/034/035, with explicit daily
supplements ADR-037.11/.12/.15. No later ADR silently overrides these contracts.

Source resolution owns SOC identity; Monitor owns admission; the observation
producer uses existing physical feasibility tests without selecting candidates;
Candidate owns route intent; execution owns request constraints and feedback;
projection and diagnostics copy records. Opportunity detection, economic ranking,
Plan Store admission policy, hardware settings, manual authority and clock-quarter
forecast policy are not redesigned. Each slice can be reverted at its boundary;
Monitor gate and native daily producer must be reverted together. New optional
record fields are additive; historical completion evidence is never rewritten.

## Audit-point disposition

| Point | Local result | Evidence / limit |
| --- | --- | --- |
| 1 SOC identity | Existing legacy migration moved to common option loading | Runtime history and live binding share total SOC; custom entity preserved, config file unchanged; historical completed goals untouched |
| 2 execution constraints | SOC/profile retained in projected and persisted requests; new directional commands at bounds blocked | Canonical IDs preserved; recovery charging allowed; already-selected modes and delegated NOM are not replaced with invented stop commands |
| 3 dispatch errors | Real HA failed status normalized, error reason propagated and runtime reports failure | Timeout and HTTP 503 regression; command acceptance is not physical success |
| 4 confirmation/timeout | Selector wait bounded to 60 seconds; timeout reaches Monitor; UI distinguishes selector evidence | No automatic reassertion after uncertain timeout; external Gielz YAML and independent hardware feedback unavailable |
| 5 Monitor bypass | Strict admission with second atomic capture and start/end registration, including initial/reset run | Changed raw input cannot bypass stabilisation; clock checks still run |
| 6 native commitments | Daily context observed directly using existing shortfall/recovery/grid-reduction/bridge tests | Stable strategy/rules/capability/publication/completion changes observable; ordinary progress does not independently admit planning |
| 7 NOM continuity | Existing NOM preserved during own-route rediscovery; original grid action alone is cleared for rediscovery | Existing daily reduction/load protection/other-route tests retained |
| 8 incumbent comparison | Deferred: no experimental incumbent change retained | Explicit rule conflict below; existing net-charge reduction preserved |
| 9 evaluation evidence | Full immutable canonical EvaluationRecord retained, original candidate-set reference preserved | Retained polls do not invent a new evaluation; original plan evaluation ID remains |
| 10 market stop reason | Actual guard reason propagated to boundary history and mode-transition log | Budget/minimum-SOC reasons retained; existing NOM follow-up policy unchanged, still needs explicit policy documentation |
| 11 dashboard | Retained plan no longer blocked; no blanket “pipeline works correctly” conclusion | Real missing plan is fault; already-active and selector timeout explanations corrected |
| 12 architecture verification | Added behavioral regressions through real daily pipeline and adjacent execution/persistence | Existing source-text architecture checks no longer sole evidence |
| 13 Recorder size | Existing 12,000-byte outgoing cap verified, no redundant source change | External Nordpool sensor attributes not owned by PicoT; live Recorder logs still require observation |
| 14 snapshots | Changed plans/results and independent clock outcomes captured; full input/evaluation retained; recent rotated files exported | 36h detail, 8MiB per record, 64MiB active file, 128MiB additional rotated export; explicit omissions, not unlimited history |

## Explicit pending decision: point 8

Adding the freshly simulated incumbent to the daily candidate comparison exposed
an existing rule conflict, not a reason to change tests or silently add a score.
In `source_with_later_cheap_window` with actual SOC 90%, the old route commands
4,800 Wh of grid charging and the reduced route commands 3,600 Wh. Simulation
clips charge at full capacity, making financial and reserve outcomes equivalent
(about EUR 0.10/kWh acquisition, minimum reserve 1,760 Wh in this reproduction).
The incumbent's equivalent-retain rule then blocks four existing ADR-037.12
reduction regressions. Experimental point-8 code was removed; point-7 fix remains.

Required explicit criterion: may proven redundant grid-charge duration be removed
when physical and financial outcomes tie? If accepted, define this openly in the
Evaluation tie-break contract and test current-plan versus reduced-plan selection.
Do not hide this decision in Candidate, runtime or Store. The session contract
requires resolving conflicting accepted decisions before implementation; code-work
also requires stopping before substituting a different binding design.

## External / unverified boundaries

The supplied Gielz log is sufficient to show failed conversion of unavailable
sensor values, but the actual automation YAML is absent. No generic float(0)
patch is applied: it would turn missing settings into invented numeric values.
A future fix must check availability before comparing or applying device settings.
Independent hardware telemetry is not configured by these patches. Selector
agreement is explicitly not physical confirmation.

No missing historical snapshots are fabricated. Dev.254 remains the agreed
pre-stable rollback reference; these corrections do not redefine that trial rule.

## Verification

Focused regressions were run red before fixes at their affected boundaries.
Integration verification results will be appended after the complete run.

### Final integration corrections

Independent review found repeated latched selector timeouts could themselves
request planning indefinitely. RuntimeMonitorSession now validates all input,
then coalesces unchanged execution outcomes per source. A distinct failure or
recovery remains observable; unsuccessful completion cannot synthesize an endless
new failure stream. Both clock outcomes and final apply outcomes feed this same
session. Technical error visibility is independent of replan admission.

The final apply uses a newly captured execution snapshot. Diagnostics now retain
that entire snapshot separately from the immutable planning snapshot, rather than
only timestamp/SOC summaries. A real daily pipeline/execution/history integration
test checks both identities and the complete capabilities, limits and commitments.

The first broad verification found an accidentally removed pre-existing legacy
incumbent argument during rollback of the point-8 experiment. The exact original
argument was restored and all 31 legacy tests passed unchanged. A main-loop test
was updated for the newly passed admission diagnostics and second capture:
closed historical PV data is correctly cached on this second preparation.

Full repository suite: `python -m pytest -q` passed **1,560 tests** in 278.08s.
This full run preceded the final timeout-coalescing and execution-snapshot additions;
these receive the final focused chain check below. Ruff passed changed tests plus
all `src/picot`; mypy passed all 211 source files with an isolated cache.
Commands use `/usr/bin/python3` and the existing development site-packages on
PYTHONPATH; no dependency or lockfile modifications were made. CI/live not run.

Final integrated affected chain: **97 tests passed** in 30.42s (Monitor, daily
producer, live polling, execution, fresh execution input, incident persistence,
PV coupling, dashboard evidence and architecture). Ruff and mypy were freshly
rerun after the final production changes and passed. `git diff --check` passed.
No code changes follow this verification.
