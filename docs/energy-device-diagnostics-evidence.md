# Energy Devices diagnostics — implementation evidence

Release candidate: Energy Devices 0.4.0-dev.5; live installation remains unverified. Runtime regulation calculation,
thresholds, storage actuation and HEMS remain unchanged.

## Implemented

- Read-only dashboard ZIP download with settings/version, 48-hour sample window,
  persistent state-change events and honest timestamps/coverage.
- Independent SQLite WAL database and bounded non-blocking writer queue. Queue
  pressure and write failures drop telemetry rather than changing regulation.
  Health counters refer to the current process; recovered logging also preserves
  its failure counters in the events log.
- RAW, intended/freed correction, actual observed consumer value, configured
  battery power, EV power/switch/session and source timestamps are separate.
- Latch time and the original triggering context persist across restart. Missing
  source and correction-mismatch contexts are kept separate. Legacy files do not
  acquire invented historical causes.
- Explicit settings/data whitelists exclude tokens, full add-on options, local
  RPC URL and unrelated user/device content. Disabled observation functions may
  produce incomplete coverage; export reports that coverage rather than guessing.

## Fresh evidence

101 affected pytest tests passed in 6.26 seconds, including nine new diagnostic
checks. Checks cover export content/privacy, retention and physical sample cleanup,
event persistence/restart, consumer fallback transitions, bounded queue overload,
database failure/recovery health events, persisted first-cause metadata, legacy
latches, genuine HTTP ZIP delivery, explicit unavailable response and runtime
readback without extra sensor requests.

Ruff passed for all Energy Devices source and new tests. Fresh-cache Mypy passed
for all 13 Energy Devices source files. Embedded dashboard JavaScript passed
Node syntax validation. `git diff --check` passed.

Live HA ingress/download, long-running disk usage and future charging/PV sessions
remain installation checks. No retrospective EV-regulation history is created.
