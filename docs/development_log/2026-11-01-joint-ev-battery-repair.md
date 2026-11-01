# Joint EV/battery advice repair - 2026-11-01

Alex reported ED advice 12:45-18:35 for 13.4 kWh, while the cheaper six-hour
price period was earlier. Existing advice protected every intermediate battery
checkpoint. EV consumption of solar energy reserved for the battery could thus
exclude a cheaper total route. Alex authorised battery replanning when the joint
household/EV/battery cost is lower, plus diagnostic evidence and clear advice.

Implementation is in `joint-ev-repair`, based on HEMS dev.324 source verified
against main e72f0bfa3fedb5a26149416a9bf55d958fe47a27. Relevant original blobs
match; live_runtime/store differ only in CRLF line endings. Other changes on
main concern HC; preserve them when preparing a release. No version bump,
publication, installation, or live plan changes were performed here.

## Behaviour

- Assess retained and rebuilt canonical battery routes for every admissible EV
  tariff start/end edge; remove the inherited 200-start sampling cap.
- Rank full-horizon cash cost with identical minimum terminal reserve and daily
  100% goals. Extra terminal stock gets no speculative credit.
- Keep immutable selected-plan proof until explicit user acceptance. Store
  publication and receipt are atomic. ED cannot turn on before the matching ACK.
- Count pending, user-accepted EV energy once in forecasts before ACK, without
  authorising the charger. Fresh ownership, energy and capability checks precede
  adoption. Lost ACK, cancellation, restart, changed ownership and late starts
  fail safely with explicit feedback.
- Publish precise provisional reasons and joint costs/savings. ED exports
  requests, candidate costs/rejections, reserve and execution identity/status.
- Cache only proven equivalent zero-PV physics; re-simulate and canonically
  validate each reused route. All other placements retain full discovery.
  Prune cost groups only after finding a valid cheaper canonical candidate.
- At final evaluation, the live worker excludes starts earlier than current time
  plus 60 seconds, so computation time cannot make a winning start unexecutable.

Architecture decision: V2ADR-068. Existing autonomous daily-plan rules, safety,
physical dispatch, market binding and other daily owners retain their authority.

## Fresh verification

- Combined core/adoption/end-to-end/UI/monitor suite: **77 passed**, 158.11 s.
- Broader existing ED, execution, external-load, commitment and recovery suite:
  **227 passed**, four existing socket HTTP tests failed with Windows sandbox
  `WinError 10013` (not source assertion failures). These must run in release CI.
- Final >200-edge enumeration and diagnostic/UI checks: **9 passed**.
- Strict Mypy: all **12 changed source modules** passed.
- Ruff: all changed source/test surfaces passed.
- Original PV-conflict regression directly shows early EV makes the retained
  battery goal infeasible, while a rebuilt battery route admits earlier EV,
  achieves the original daily target and lowers total cost.
- Real end-to-end test includes ED request, actual planner, pending demand,
  actual Store adoption, ACK, both restarts and charger start/stop. No mocked
  planner or commitment Store.

Measured full-size synthetic benchmarks (not the user's exact missing advice
snapshot): 13.4 kWh at 2300 W, 130 EV placements, 36-hour valuation horizon:
37.03 s without PV and 39.45 s with five hours of 400 W central PV. These are
local measurements, not guaranteed latency on the Home Assistant NUC.

Four specific CI follow-ups: test_ev_direct_start_http::test_direct_start_over_http_socket;
test_daily_plan_recalculation::test_request_recalculates_bound_route_and_is_consumed_once;
test_energy_device_diagnostics::test_diagnosis_download_is_real_zip_and_does_not_mutate_control;
test_energy_device_diagnostics::test_disabled_diagnostics_returns_explicit_503.

Release should include both HEMS and ED because the acceptance handshake and
forecast interpretation span both components. Refresh main before overlaying
only the changed files listed in the local repair-status record. Do not replace
the repository with the historical base copy. Do not change HC.
