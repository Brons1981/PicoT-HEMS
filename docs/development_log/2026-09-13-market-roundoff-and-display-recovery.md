# 2026-09-13 — market roundoff and two display/export corrections

User authorized all three fixes together. No release has been made. Keep these
as separately reviewable slices at their existing ownership boundaries.

## Change contract

- Market binding preservation (ADR-027, ADR-033): proportional allocation can
  produce a negative elapsed remainder through floating-point roundoff. The
  binding constructor rejects that remainder with a misleading lineage error.
  Normalize only negative remainders within the existing 0.000001 Wh balance
  tolerance. Material errors and all ownership/lineage validation stay strict.
- Actual SOC projection (ADR-035, canonical projection boundary): failed history
  requests erase a successfully displayed series. Persist the latest successful
  same-day, same-source view; show it as stale on failure with its original
  coverage endpoint. Never advance the endpoint or supply cached evidence to MEP.
- HA diagnostic transport (ADR-035): large full-detail card attributes exceed
  Recorder's limit. Compact only the HA outgoing copy to 12,000 serialized bytes,
  including omission metadata. Keep dashboard, diagnostics and canonical cards
  complete. External Nordpool entities are outside this change.

MEP, candidate simulation, evaluation, runtime materiality, dispatch policy and
clock-quarter consumption forecasting are outside scope. No new SOC tolerance
or planning safety rule is introduced. Each slice can be reverted independently.
Dev.254 (`21314d8`) remains the agreed pre-stable clock-quarter trial baseline.

## Evidence

- The retained market regression uses a plan built by the real daily pipeline,
  admits a market binding, then preserves it. The original calculation fails
  with `retained market execution requires complete original lineage`; the
  corrected calculation succeeds while preserving allocation and original IDs.
- Material negative elapsed energy remains rejected by the domain contract.
- SOC tests cover failed reads, worker exceptions, restart, recovery, day change,
  source change and absence of previous successful history.
- HA tests inspect actual serialized HTTP bodies, Unicode size, omission metadata
  and unchanged original card data.
- Combined focused, adjacent commitment/pipeline and architecture suites: 121
  tests passed. Ruff passed; mypy passed all 74 v2 source files. Live recovery
  remains to be observed after release.
