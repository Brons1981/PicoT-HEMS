# Partial HC load, bridge options and decision evidence

Local implementation on main daa1d5e1b5be971c1a12735a6d14dc4d25bc269c.
No version bump, release, HA action or plan reset. See V2ADR-070.

Acceptance evidence:
- HC timing survives missing warmup, invalid thermal context and model failure.
  Complete publications do not transmit climate targets. Current maintenance can
  remain quantified when cooling is unknown. No cooling/cold room produces no fake zero.
- Real HC publication -> HEMS application integration uses the same public payload.
  Known energy replaces exact airco history only; unknown periods keep historical
  demand. Timing stays in the snapshot even without energy attribution. Stale
  envelopes rejected; bad optional rows quarantined without erasing valid ones or
  complete legacy forecasts. Restart persistence and no double application tested.
- Bridge regressions (ordinary/revision and PV/no-PV) show contiguous multi-price
  partial standby, reserve coverage, unchanged main/export commitments and bounded
  simulations. Existing equivalent-plan/elapsed-main behavior remains green.
- Oversize decisions retain bounded comparisons/validity/policy with explicit omissions,
  survive aging and appear in diagnosis. A full replay is not claimed.

Fresh final verification: 205 tests passed in 61.63 seconds in one combined run:
test_hc_partial_load_facts, test_hc_day_ahead, test_load_replacement,
test_accepted_loads, test_controlled_load_history, test_bridge_partial_standby,
test_bridge_local_recovery, test_daily_bridge_energy, test_daily_bridge_pipeline,
test_bridge_elapsed_main, test_bridge_financial_stability,
test_compact_decision_evidence, test_v2_planning_incident_history,
test_market_revision_incident_history, test_v2_diagnostic_downloads,
test_diagnostics_timeline, and HC partial/day_ahead/recovery/energy_outlook/
warmup/startup suites.

Ruff passed for src/picot and changed HC modules/tests. Mypy --platform linux
passed for all 275 src/picot files. Native Windows-wide Mypy reports existing
Linux-only os/resource attribute errors; Linux target matches deployment.
Node dashboard syntax passed; 17 tablet behavioral checks passed.
Earlier failures: sandbox default temp was unwritable (workspace temp used);
integration test fixture missed optimization_band (corrected); local UTF-8 edit
corrupted degree literals in weather checks (restored as explicit Unicode escapes).
Final rerun includes those failures and is green.

Full release CI, container/browser interaction and installed behavior are not yet
verified for these changes. The missing full 5-Nov 21:42 snapshot means exact live
counterfactual savings cannot be reconstructed. Timing-only future heating does not
fabricate watts and does not by itself demonstrate increased evening SOC.
