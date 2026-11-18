# EV arrival SOC repair

BMW reported 38% at 2026-11-18 18:08:49 Europe/Amsterdam; cable on at 18:09:37. ED rejected this 48-second ordering difference even after three hours without charging.

Accept SOC up to 120 seconds before the current BMW cable connection, with a cable check no older than 30 seconds and no charging power observed after the SOC report. The same rule supports restart/recovery of an already connected car. Existing fresh post-connection SOC handling and charge-stop logic are preserved. No smartplug-on requirement is added. HEMS remains responsible for choosing the charging window.

Diagnoses now include cable state/check/change timestamps, source entities, last observed charging timestamp, SOC value/report/status/reason and the 120-second margin. Export remains allowlisted.

Regression: 38% to 80% using 11.7 kWh full-charge estimate requests 4914 Wh while smartplug remains off. Boundaries 120/121 seconds, later charging, missing/stale cable confirmation, restart and real ZIP export are covered.

Release ED 0.4.0-dev.19 requested by Alex; publication via PR and green CI. No live installation. Source files matched GitHub main by Git blob SHA before changes. Full HEMS release validation is deferred to release; this isolated workspace inherits earlier HEMS dependencies.

Verification: 165 affected ED tests passed (88.05 s); Ruff clean for five changed Python files; strict mypy passed for three changed source files. Initial broad collection missed Jinja2; an oversized HEMS-inclusive run was interrupted. No full-repository CI verdict.
