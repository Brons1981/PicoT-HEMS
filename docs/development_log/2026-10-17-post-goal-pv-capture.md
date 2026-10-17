# 2026-10-17 — Restore PV capture after daily full charge

Alex authorized the narrow repair after distinguishing physical feasibility from
financial export/storage valuation. Do not broaden this into a new route optimizer
or a global objective-priority change.

Changed production surface: `independent_daily_charge_window_discoverer.py` only.
After trimming the owned charge at completion, the admitted schedule captures
later free forecast surplus in the same delivery day. Full physical re-simulation
and ordinary plan building carry those unowned NOM intervals into execution.

Tests: `test_daily_post_goal_pv_capture.py`. The initial regression run demonstrated
missing post-goal NOM; the pipeline fixture subsequently uses distinct snapshots
for recalculation and explicitly cheap early prices to exercise the incident route.

Offline replay uses a scratch copy of the diagnostic commitment store and the
normal explicit recalculation API. Result: `plan-3c56bba3440c965e`, grid charge
04:15–05:45 unchanged, 1445.54 Wh PV input captured, terminal SOC 63.05%.

The existing HTTP reset test is blocked locally by Windows socket permissions
(WinError 10013). Other recalculation tests and the new direct-pipeline regression
exercise persistence and recalculation without modifying or bypassing that test.

Release remains separate; version numbers are unchanged.

Final local verification: 142 affected tests passed in 69.97 seconds, with the one
socket-blocked HTTP test deselected explicitly. This includes discovery, financial
selection, active pipeline, recalculation, horizon ownership, running-load protection,
PV optimization, future grid reduction, EV execution isolation, and market recovery
scope/isolation. Ruff passes for the changed Python files. Strict mypy with the
Linux target passes for the changed production module. Full repository CI is not
claimed by this local verification.
