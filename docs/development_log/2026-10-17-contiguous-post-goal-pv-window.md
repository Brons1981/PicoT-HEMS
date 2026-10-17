# 2026-10-17 — Remove unnecessary daytime mode fragmentation

Requested after Alex's 22:01 screenshot and 22:03 confirmation. The dev.303
post-goal capture rule switched mode on individual forecast quarters. Replace
that with NOM over the bounded solar window, preserving existing action barriers.

Production change is limited to the daily charge-window discoverer. Forecast
surplus still selects boundaries, while intermediate deficit intervals delegate
normal balancing to Zendure. No global priority change or new economic policy.

Canonical replay of the 20:14 diagnosis produces plan-a540ceaadbb1439b:
- 18 October 04:15–05:45 Europe/Amsterdam: grid charging unchanged.
- 09:30–16:30: one continuous NOM segment instead of six fragments.
- PV captured: 1445.54 Wh; terminal SOC: 63.05%, identical to the dev.303 replay.
- All remaining times: household-support-only.

Two regression tests fail on dev.303 at the internal zero-PV gap. The updated
focused suite passes all 16 tests, including existing actions inside the window.
Ruff and strict mypy for the changed production file pass.

Affected regression run: 143 passed, one existing HTTP reset test explicitly
deselected due to the previously confirmed local socket restriction. The final
16-test focused run additionally includes three parameter cases for existing
actions in the internal gap. Full repository CI remains a release gate.

Version and publication remain unchanged pending a separate release request.
