# V2ADR-060 — Fast vendor-mode dispatch and failure containment

Status: **Accepted**

Date: 2026-08-30

## Context

Canonical MEP execution expresses explicit market actions as
`CHARGE_AT_POWER` and `DISCHARGE_AT_POWER`.  The Zendure integration does not
accept a direct watt setpoint for these live actions; its admitted capability
maps them to the fixed vendor modes `Snel opladen` and `Snel ontladen`.

The canonical runtime constructed those mappings correctly, but the shared
Home Assistant adapter only accepted balance primitives as fixed
`input_select` modes.  It treated charge as a legacy numeric mapping and
rejected discharge.  The resulting `ValueError` escaped the external boundary
and terminated the add-on when a live export segment became due.

## Decision

1. A canonical fast power primitive may translate through
   `input_select.select_option` when its admitted mapping supplies one explicit
   fixed vendor mode.
2. Existing numeric `CHARGE_AT_POWER` mappings through `number.set_value` or
   `input_number.set_value` remain supported for compatibility.  The mapping
   domain determines which translation contract applies.
3. The adapter never derives or sends a direct Zendure watt value for the
   canonical fast-mode mappings.  Requested power remains planning and
   provenance evidence; the selected vendor option remains the command.
4. Translation and transport are one external failure boundary.  Any exception
   there is contained: no command is claimed, adapter status becomes
   `translation_failed`, vendor status becomes `dispatch_failed`, and the
   failure reason is retained in canonical diagnostics.
5. A failed dispatch clears process-local pending-mode state so a later healthy
   cycle may retry.  It does not mutate, replace or reinterpret the MEP plan.

## Verification

Tests must traverse the real Home Assistant adapter and prove both fast modes
produce their exact fixed `input_select` option.  Separate runtime coverage
must prove that an adapter exception returns a diagnostic failed outcome
instead of escaping the live cycle.  Existing numeric charge translation and
all planner tests remain unchanged.

## Core principle

> MEP owns the power intent, the capability mapping owns the vendor mode, and
> an unavailable actuator must fail visibly without taking the planner down.
