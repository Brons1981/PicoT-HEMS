# HC dev.34: CV standby and feedback recovery

Automatic CV demand ends at heat / 15 C. The thermostat remains available for later demand. The existing manual override expires at the next comfort boundary; when no schedule is enabled, explicit resume is still needed. Confirmed satisfied CV standby permits airco takeover. The minimum restart interval is retained.

Independent HA feedback can confirm the latest failed, timed-out or interrupted intent. No command is resent for recovery. A newer intent, unavailable device or mismatched mode/target prevents this recovery. Previous error/status/time are retained with the recovery time. Historical source faults clear only when fresh feedback matches the latest confirmed source intent. Manual holds remain authoritative. After recovery the normal regulator can make new decisions.

A historical CV fault no longer invalidates airco/cooling learning if CV is available, has no pending command, and is off or explicitly idle with a satisfied setpoint. Unknown activity still blocks this exception. Existing cooling age, identity, weather, temperature and comfort checks remain intact. The dashboard separates stored and currently comparable cooling counts; diagnostics include the cooling records and current segment.

The 10 November diagnosis had 25 stored cooling records, 20 recent, but no valid context due to the historical CV fault. Its latest CV command was confirmed off and the reported state was off. Offline replay clears this fault without creating any command. No measurements are fabricated or deleted.

Local checks cover late/mismatched feedback, newer intent, restart persistence, manual takeover, CV standby, cooling/coasting, exported evidence and downstream forecasts. JavaScript syntax passes. Full HC tests, browser interaction and container packaging are required in CI before merge. This release does not include the separate unpublished shadow-comparison work and does not change HEMS or ED.

Release CI also exposed three pre-existing calendar-dependent root tests: August 2026 fixtures had aged outside the 90-day history retention window. The same failures reproduce on the unchanged HEMS source. Freeze only the history-store clock to each test scenario; retain pruning and all assertions. No HEMS production change. All eight tests in the affected modules pass with the fixed clocks.
