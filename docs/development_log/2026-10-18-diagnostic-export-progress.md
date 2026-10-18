# Diagnostic export progress — 2026-10-18

Status: implemented locally; not released. Baseline main ce9fa788dfc05fac273abd5da1dd53282dfdc964,
HEMS dev.305 and Energy Devices dev.10. User asks observable receipt/build/download status.

Both dashboards now POST a background export and receive HTTP 202 before ZIP generation.
GET status reports actual bytes (HEMS) or rows (Energy Devices), then GET exact job downloads
completed bytes. One worker/result per server; concurrent starts reuse a running job. New
explicit export replaces prior completed data. Errors are visible, duplicate clicks disabled,
network request/inactive-download timeout 30s. Browser receives a streamed Blob with byte
progress and reports handoff to browser rather than falsely claiming the file was saved.

ZIP builders preserve allowlists, rotated history budget, live-file EOF behavior and ED read
transaction consistency. Progress callbacks are optional. Old direct download routes remain.
Generic worker has no HEMS/app dependencies; both Dockerfiles explicitly include it (ED only
copies the standalone module, no HEMS planner/runtime). No planner/EV control changes.

Files:
- src/picot/diagnostic_export_job.py
- src/picot/v2/diagnostic_downloads.py
- src/picot/v2/web_ui.py
- src/picot_energy_devices/diagnostics.py
- src/picot_energy_devices/web_ui.py
- picot_hems/Dockerfile
- picot_energy_devices/Dockerfile
- tests/test_diagnostic_export_job.py
- tests/test_diagnostic_builder_progress.py
- tests/test_diagnostic_export_web.py
- tests/test_v2_diagnostic_downloads.py
- tests/test_energy_device_diagnostics.py
- this log

Validation: 71 passed, 1 skipped in combined worker, builders, handlers, JS lifecycle, ZIP,
ED diagnostics and full HEMS UI tests. Ruff clean; mypy --platform linux clean for five source
files. Node tests execute both dashboard success/failure flows. Packaging test imports the
worker isolated from all other source code. One pre-existing passive-history test skipped.
No live HA ingress test or container build performed. No version bumps/publication yet.
