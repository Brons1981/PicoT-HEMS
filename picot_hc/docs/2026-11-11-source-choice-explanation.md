# Heating choice evidence

Scope: explain existing HC source choices and their execution, without changing
source policy, temperature targets, CV recovery, HEMS/ED contracts or releases.
Base: PicoT-HEMS main 5b42f7582b063cad6df6735505f787b0af1fea42; HC dev.34.
The 115 local HC baseline files were verified against GitHub blob hashes before editing.

The source selector now attaches its actual branch reason (cost preference,
unavailable alternative, room floor or minimum run). Active start plans are named
separately, and current unit heat prices are explicitly reference prices for them.
Eligibility reasons share the actual selector checks. Execution conflicts share
the actual action guard. No independent explanation planner is introduced.

Dashboard evidence includes electricity price and interval, confirmed tariff
basis, configured gas price and validity, COP and CV efficiency assumptions,
estimated unit heat costs and electricity break-even price. These are not total
period costs or learned efficiencies; PV, battery opportunity cost, warmup,
residual heat and CV auxiliary electricity are not priced by this simple comparison.
Room and thermostat temperatures are separate. Pending/off/idle/reported heat,
faults, ownership conflicts and restart delay are separate from the selected source.

Diagnostics contain the last evaluated decision with its original timestamp and
the basis at the last automatic command intent. Export does not replan, expire
commands or change stored data. Current thermostat temperature and preset are
included with reported states. Evidence is bounded to the latest evaluation and
latest command intent, not a new unbounded event history.

Morning agreements recovered for 11 November (07:16 and 07:22 Amsterdam): HC owns
comfort and heat decisions. HEMS supplies advice, not a veto on heating. Future
period advice should include available energy, power, PV, cost, confidence and
validity, with HC returning chosen demand. This change displays existing advice
separately; implementing that expanded exchange remains separate work.

Validation: five new decision tests (including three price subcases), five
diagnostic tests, eight room-floor tests and one readiness test passed (19 tests,
3 subtests). Seven existing in-process continuity/restart tests passed; JavaScript
syntax and real explanation-function rendering assertions passed. An exploratory
run of all 48 heating cases through the local fixture passed 41; the other seven
require HTTP/template collection and failed with blocked local sockets (WinError
10013 or disconnected collector). A broader mixed run was interrupted and is not
a passing result. Headless Edge launch failed under environment permissions, so
desktop/mobile visual verification is pending. CI is extended with explanation
rendering and layout checks; actual dashboard CV assertions are also added.
No release, deployment, live device commands, settings changes or calibration.

## Follow-up: CV start and failed-start handover

The public msvisser/remeha_home climate implementation ignores temperature
requests in OFF and restores its saved manual setpoint when entering HEAT.
HC now sends HEAT separately, waits for observed confirmation, and only then
sets the requested temperature if needed. The exact confirmed mode transition
may restore a device setpoint without being mistaken for a manual override;
subsequent manual edits still take precedence. The dashboard distinguishes
waiting for mode confirmation from waiting for the temperature target.

A failed CV command no longer blocks airco indefinitely when fresh feedback
confirms CV OFF and there is no pending command. The fault and ownership remain
visible, so late confirmation is handled and uncertain commands are not replayed.
Unavailable or uncertain CV state still prevents overlapping heat. Cancellation
between steps waits for feedback before setting the existing 15 C standby target.
No thermostat calibration, cost-policy change or expanded HEMS contract is added.

Follow-up verification: 29 focused tests and 3 subtests passed, including ten
Remeha-style command-sequence cases; ten existing CV energy-start tests passed.
Execution receipts also require the observed requested temperature before
reporting running. Full HTTP/browser CI remains pending under local restrictions.

The final regression run passed all 41 applicable existing heating cases using
the in-process HA boundary. JavaScript syntax and explanation rendering passed,
including the separate CV mode-confirmation stage.
