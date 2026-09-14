# 2026-09-14 — diagnostic evidence capture and rotated export

## Change contract

User authorized the combined audit repair list. This slice repairs the diagnostic
persistence/export boundary, governed by ADR-017 explainability, ADR-028 bounded
resource usage, ADR-035 traceability and the canonical projection contract.
Planning, evaluation, commitment policy and dispatch are out of scope. Diagnostic
records copy canonical inputs and outputs without changing their meaning. Revert
this slice independently; existing JSONL records remain readable.

## Findings and implementation

- There is no six-record retention setting. The uploaded active JSONL contains
  six full records. History has a 36-hour full-detail window, a 64 MiB active-file
  rotation limit, and an 8 MiB individual-record detail limit. The archive alone
  cannot prove whether older evidence was never captured or stayed in rotated files.
- The outcome fingerprint ignored plan identities/segments and execution outcomes.
  A revision with unchanged headline mode/reason and a changed dispatch result
  could therefore disappear. Fingerprints now cover those semantic changes;
  identical polls remain deduplicated. Snapshots include complete canonical
  planning input and opportunities alongside the existing decision/output records.
- ZIP export previously included only the active incident file. It now also exports
  strictly named incident-history rotations from the last 36 hours, with a separate
  128 MiB allowance. Symlinks and unrelated names are excluded. Budget exclusions
  produce an explicit coverage manifest. Source files are never removed or edited.
- Existing HA transport compaction is already bounded to 12,000 serialized bytes;
  it is unchanged. Four HTTP-body tests pass, including Unicode and preservation
  of canonical cards. A real fixture pipeline projection produced nine cards of
  379–5,159 bytes. This does not prove external Nordpool sensors are bounded or
  establish what live Home Assistant recorded previously.

## Evidence

Two new capture regressions first failed because only one record was stored instead
of two. The rotated-export regression first failed because the morning archive was
absent. After repair, 31 focused/adjacent tests passed (incident history, export,
HA projection transport, HTTP endpoints, architecture ownership). Ruff passes for
changed source/tests. Mypy passes three source files using /usr/bin/python3 and
an isolated cache; primary-runtime Python produced a mypy internal error.

## Limitations and integration seam

Runtime must call record for actual boundary-only execution observations and pass
Monitor/commitment evidence when available; this module does not invent those facts.
Full detail can still be explicitly reduced for an individual record exceeding
8 MiB. Rotated export is bounded, not a guarantee under arbitrary event volume.
No historical missing evidence is reconstructed. No live release was performed.

### Clock-only execution integration

Added `record_boundary(bundle, outcome, runtime_diagnostics)` for actual committed
clock events without a new planning run. It stores the existing input identity and
exact boundary outcome, not a fabricated evaluation. Repeated application/command
IDs do not grow history; status, plan, mode, primitive and reason changes do.
Bounded/basic compaction retains the outcome. Two additional regressions passed,
including failure-to-recovery and oversized evidence; 33 adjacent tests now pass.
