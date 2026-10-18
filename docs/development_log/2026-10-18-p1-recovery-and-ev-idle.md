# P1 recovery and EV idle release — 2026-10-18

Status: implemented locally, not published. Baseline HEMS 2.0.0-dev.304 / Energy Devices 0.4.0-dev.9.

Evidence: Energy Devices diagnostics 20261018T052834Z and 20261012T043420Z.
HTTP 502 on 11 October 07:54:51 UTC caused persistent_measurement_loss at 07:54:59;
measurements restored at 07:55:26 but the persisted correction guard never cleared.
17 October afternoon measurements all used shelly_raw fallback despite calculated corrections.
18 October EV idle 2.2 W kept HEMS exclusion latched after charging completed.

## Changes
- Transient measurement-loss latch retries after 10 seconds continuously fresh measurements.
- Trial correction is served for up to 10 seconds while HEMS exclusion remains active.
- Three distinct fresh consumer confirmations, matching transmitted correction and explicitly
  not fallback, remove the persisted latch. Failed trial returns to blocked and retries after
  stability. Wrong-correction and corrupt-state latches do not automatically clear.
- HEMS release: exact fresh zero retains immediate release; positive idle <=5 W requires fresh
  physical observations spanning >=30 seconds with <=180-second gap. Renewed >5 W, missing,
  stale or nonphysical evidence resets idle confirmation. Restart retains protection.
- Both dashboards expose EV/P1 blocking; Energy Devices separates calculated and measured
  offered P1 and shows blocked/recovery/stale state. No planner or EV deadline change.

## Files for release
src/picot_energy_devices/regulation_guard.py
src/picot_energy_devices/regulation.py
src/picot_energy_devices/runtime.py
src/picot_energy_devices/web_ui.py
src/picot/v2/external_load_policy.py
src/picot/v2/canonical_execution_runtime.py
src/picot/v2/web_ui.py
tests/test_energy_device_regulation_guard.py
tests/test_ev_storage_execution_guard.py
tests/test_regulation_dashboard_health.py
this log

## Validation
Three new P1 regression checks failed on original implementation, then passed.
Combined regulation, policy, EV guard, execution runtime and existing device dashboard tests:
109 passed. Additional dashboard health and full HEMS UI tests: 43 passed.
Ruff and Mypy --platform linux clean on changed source surfaces (coordinator and UI/guard reviewers).
Windows tests require writable TEMP/TMP; UI subprocess requires PYTHONUTF8=1.
No live device commands, deployment or release performed. Live consumer switching remains
an installation check; tests cover API trial versus HEMS authorization and failure recovery.
