# Explicit planning recovery — dev.289

User-authorized change: the new-plan button is a recovery reset, not an incremental reprice request. Existing charge/market commitments may be released even when an old goal is unresolved. Proven completion and physical limits remain authoritative; a manual vendor-mode override is separate.

The reset archives prior planner state atomically before releasing active pointers, open route bindings, market obligations and supplemental plans. Measurements and rules are untouched. Completed owners keep their admitted route and completion evidence. The existing planning barrier prevents stale publication; process-local execution dispatch state is cleared inside it.

The canonical daily planner alone assesses feasibility on a fresh snapshot. Only during an explicit pending recovery, a current-day goal rejected for insufficient remaining charge capacity is durably recorded as unreachable, never completed, and omitted from subsequent live planning context. Future-day goals and missing-input failures are not waived. A successful canonical plan publication completes the recovery request.

Evidence: uploaded diagnosis `picot-diagnostics - 2026-10-08T235107.048.zip`, latest input 23:47:34 Europe/Amsterdam, SOC 48%, physical charge limit 2400 W. An isolated copy of its saved commitment state reproduces `fallback_active / insufficient_remaining_charge_capacity`. After the explicit reset, the same canonical pipeline produces `winner_selected / objective:financial_result` and binds 9 October. 8 October remains uncompleted and is recorded as unreachable. No live HA writes were performed.

Regression coverage includes late restored day, persistent restart, no incumbent, preserved measured completion, released/archived market obligations and atomic disk failure. Legacy incremental recalculation remains available internally; the UI invokes recovery reset explicitly.
