# HC / HEMS: Linux CI preparation and repairs

Draft PR: https://github.com/Brons1981/PicoT-HEMS/pull/725
Base: 3b7d410a3d4e89ebe2792390354f576f36ca2a03 (published dev.314).
Source/test head: 8a162f18671b2ab6a30f00d4a717db9554532bcc.
No merge, release, version bump, installation or live control performed.

## CI findings and fixes

Repository text was normalized to LF to remove upload-only CRLF diff noise.
The root pytest configuration now includes picot_hc/tests for shared HC helpers
used by the end-to-end proposal test. Three runtime startup tests now explicitly
use a temporary accepted-load database instead of the production /data path.
Production behavior was not changed by these CI repairs.

## Verification

- Local focused rerun: 19 passed in 43.43 seconds; Ruff clean for changed tests.
- Root collection: 2560 tests collected without errors.
- Linux v2 run 40088550110 on source/test head: 878 passed, 1 skipped;
  Ruff and mypy (120 files) passed.
- Core CI run 40088550109 on source/test head passed.
- Initial HC run 40088246302: 428 tests and 30 subtests passed, Docker build,
  container import/assets, JavaScript checks and real browser interactions passed.
  HC source is unchanged by the subsequent test-discovery and isolation repair.
- The complete root tests and repeat HC run were still running when this record
  was written. The PR check results and description carry their final outcome.

Live home behavior and actual HA hourly-weather capability remain separate
installation checks. The draft PR does not authorize a release.
