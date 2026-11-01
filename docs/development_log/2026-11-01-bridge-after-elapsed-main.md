# Bridge after an elapsed main block

Incident: diagnostics 2026-11-01T091826.644, fallback at 09:15:52 Europe/Amsterdam.
The daily route owned PV charging until 09:15 and grid charging 11:15–14:45.
After the first block elapsed, the bridge planner correctly retained only the
future main block. Store validation compared that candidate against both original
blocks and raised `bridge cannot move or change the next main session`.
All 43 diagnosed candidates retained the future main action unchanged.

The Store now compares against owned main blocks ending strictly after the new
plan's creation time. An ongoing block remains protected. No remaining main block
still rejects the bridge. Existing exact checks on time, primitive, capability,
power, SOC constraints and charge-source policy remain intact. The bridge endpoint
uses the same remaining set. Existing atomic revision history retains the complete
previous assignment and plan, including elapsed blocks.

Regression tests reproduce the original failure at the exact boundary and 52
seconds after it, through the real pipeline and Store. They verify successful
publication, unchanged future main action, historical evidence and restart, and
continued rejection without partial writes when future power or policy changes.

No migration, tariff change, new planning authority, version bump, release or live
installation is included in this repair. Baseline: HEMS dev.326, merge
e356a86472853e3c1e9de5d286a79ca399818f74. Work directory: bridge-elapsed-main-fix.

Verification: both regression cases failed with the exact incident error before
the repair. After repair, 28 tests passed (bridge pipeline, bridge energy, local
recovery, new regressions and main-revision total costs); Ruff and strict Mypy
passed for the changed source. No live installation or device test performed.
