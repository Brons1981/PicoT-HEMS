# Supplemental repair against an invalid incumbent — 3 November 2026

Scope: repair the observed HEMS safe-mode failure before extending HC forecasting.
Baseline: dev.328, release merge 3c01af64507212d18aff5ad0b39aa0b646b220e2.
The touched production file matches GitHub main before editing
(blob d744303a35d2f0abc80dda0297ef7d804e4505af).

## Evidence and cause

The 3 November 18:49 diagnostic export records fallback from 18:13 local time.
Replaying its 18:15 Planning Input against the original producer reproduces
supplemental_revision_terminal_inventory_not_equal and daily_main_goal_unreachable.
Supplemental retirement enabled complete cash comparison against the incumbent
without requiring that incumbent to be physically valid. Its failed 100% goal
therefore imposed its deficient terminal inventory on feasible repair candidates.
V2ADR-067 already requires invalid incumbents not to be protected by the financial gate.

## Change

In produce_main_charge_portfolio, supplemental cash/equal-inventory comparison
requires an incumbent without assessed invalidity. Necessary non-market repair
uses the existing acquisition objective. Valid incumbent comparisons retain the
existing complete-cash and equal-stock checks. The invalid incumbent remains
invalid. No execution guard, SOC limit, market recovery contract, goal identity,
persistence format, HC behavior or notification transport is changed.

## Verification

- Original live-input replay: fallback reproduced.
- Corrected live-input replay: winner_selected, seven-segment replacement admitted.
- Fresh projection: no daily-main shortfalls, peak 8160 Wh, minimum 1699.765 Wh
  (above the configured 816 Wh floor).
- Next evaluation: plan_retained; no repeated replacement with unchanged input.
- New producer regression and existing valid-retirement economics: red on the
  original producer's economics contract, green after correction.
- Broad affected suite: 85 passed in 344.04 seconds (Python 3.12).
- Strengthened final regression: 1 passed; the same strengthened test fails on original dev.328 because feasible alternatives with different terminal inventory are excluded.
- Ruff: all src/picot and the new test passed, using the cached Windows executable.
- Mypy: changed producer passed with Python 3.14, matching the cached librt binary.
  Python 3.12 Mypy initially could not load that cp314 binary; no source workaround.
- Release Linux CI and live installation remain outstanding.

The later 18:48 PV-choice request was rejected because the exact offered route
was no longer available. It did not cause the 18:13 incident. Existing full-route
proof protects a feasible plan after rejection. No different user route is substituted.

Notification delivery remains unverified: choices are persisted, but notifier
queue/publication state and HA automation traces are absent from this export.
No phone-delivery repair or success is claimed.

No release, commit, push, deployment, live plan reset or HA command performed.
