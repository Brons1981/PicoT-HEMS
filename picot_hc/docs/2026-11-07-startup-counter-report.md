# Full-start learning: unchanged energy counter

The 5 November 18:09 and 6 November 17:15 starts had a cached energy-counter report age of 525 and 301 seconds before dispatch. The power report was fresh. `meter_context` rejected both baselines under its 90-second counter limit, and `StartupEnergy` could not reconstruct a full trajectory after heat started.

Fetch the downstairs energy counter through the existing direct HA report template alongside temperature and power. Use the returned value and source report timestamp together. Reject `hc_report_error`, genuinely stale/future reports, invalid units and counter values; do not substitute retrieval time for report time or relax limits.

Record missing or incompatible pre-start baselines in the existing bounded, deduplicated event log and expose a Dutch explanation on the dashboard. An already processed/completed command must not generate a new missing-baseline warning. Existing completed records and live measurements are not rewritten.

Scope: passive measurement and learning diagnostics only. No source-selection, COP, comfort, door, CV or HEMS policy changes. No version bump or deployment.

Regression evidence: new direct-report and startup tests fail on the unchanged source (cached unchanged counters rejected, missing direct report accepted, missing reasons). They pass with the fix. Ages 301/525 seconds reproduce the observed conditions; matching fresh reports allow a baseline, truly stale/future/unknown reports remain rejected. Restart/completion and no-command idle behavior are covered.

Local verification uses Python 3.14.6; CI uses Python 3.12. Full HC execution was attempted but interrupted after network-dependent fixtures failed or stalled under local socket restrictions. The unchanged source also fails `ControlTests.test_ack_is_not_feedback_and_old_read_cannot_confirm` with HA unreachable; direct fixture access separately reported Windows socket error 10013. Full CI and browser/container checks remain for release.

Final focused checks: 25 startup/warmup tests plus 5 subtests; 23 downstream energy-proposal, delayed-start, day-ahead and readiness tests. All passed. Dashboard JavaScript syntax passed.
