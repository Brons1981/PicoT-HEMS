"""Screened household gas as an estimated CV warmup bound, never a heat meter."""

from .cv_auxiliary import assumptions
from .cv_auxiliary import estimate as auxiliary_estimate
from .energy_model import finite
from .thermal_weather import comparable


def matching(record, sample, now):
    """Only fully reviewed, recent, comparable sessions can support an estimate."""
    try:
        screen = record["gas_screening"]
        numbers = [
            record[k]
            for k in (
                "start",
                "measured_at",
                "stable_at",
                "gas_start_reported_at",
                "gas_end_reported_at",
                "household_gas_delta_m3",
                "indoor",
                "outdoor",
                "target",
            )
        ]
        if not all(finite(v) for v in numbers):
            return False
        end, start = record["measured_at"], record["start"]
        return (
            isinstance(record["command_id"], str)
            and bool(record["command_id"])
            and 0 <= now - end <= 7 * 86400
            and 300 <= end - start <= 10800
            and record["identity"] == sample["identity"]
            and comparable(record, sample)
            and abs(record["indoor"] - sample["indoor"]) <= 0.25
            and abs(record["outdoor"] - sample["outdoor"]) <= 1.5
            and abs(record["target"] - sample["target"]) <= 0.05
            and 0 < record["household_gas_delta_m3"] <= 20
            # A stale initial counter can include a previous heating/DHW run.
            and 0 <= start - record["gas_start_reported_at"] <= 60
            and start < record["stable_at"] <= record["gas_end_reported_at"] <= end
            and screen.get("status") == "no_dhw_observed"
            and isinstance(screen.get("identity"), str)
            and bool(screen["identity"])
            and screen["identity"] == sample.get("gas_screening", {}).get("identity")
            and screen.get("polling_complete") is True
            and screen.get("provisional") is False
            and screen.get("delay_margin_seconds") == 90
            and finite(screen.get("checked_at"))
            and end + 90 <= screen["checked_at"] <= now
            and record["electricity"].get("status") == "estimated"
            and record["electricity"].get("assumptions") == sample["auxiliary_assumptions"]
        )
    except (KeyError, TypeError, AttributeError):
        return False


def estimate(records, sample, now, *, gas_price=None):
    result = dict(
        status="collecting",
        samples=0,
        gas_m3=None,
        gas_cost_eur=None,
        duration_seconds=None,
        electricity=None,
        margin_fraction=0.25,
        method="screened_household_gas_upper_margin:v1",
        heating_only_confirmed=False,
        comparison_eligible=False,
        execution_authorized=False,
        reason="Drie passende CV-opwarmbeurten met afgeronde warmwatercontrole nodig.",
        blockers=[
            "joint_replacement_basis_required",
            "cv_maintenance_evidence_required",
            "hems_start_permission_required",
        ],
    )
    if (
        not isinstance(sample, dict)
        or not finite(now)
        or not all(finite(sample.get(k)) for k in ("indoor", "outdoor", "target"))
    ):
        return result
    parameters = sample.get("auxiliary_assumptions")
    if not isinstance(parameters, dict):
        return result
    validated = assumptions(
        dict(
            cv_auxiliary_mode="estimated",
            cv_auxiliary_running_w=parameters.get("running_power_w"),
            cv_auxiliary_postrun_w=parameters.get("postrun_power_w"),
            cv_auxiliary_postrun_seconds=parameters.get("postrun_seconds"),
        )
    )
    if validated is None:
        return result
    matched = []
    seen = set()
    for record in records:
        if matching(record, sample, now) and record["command_id"] not in seen:
            matched.append(record)
            seen.add(record["command_id"])
    result["samples"] = len(matched)
    if len(matched) < 3:
        return result
    gas = max(r["household_gas_delta_m3"] for r in matched) * 1.25
    # Include stabilization and the wait for a gas counter report in the deadline.
    duration = max(r["measured_at"] - r["start"] for r in matched) * 1.25
    cost = gas * gas_price if finite(gas_price) and gas_price >= 0 else None
    return dict(
        result,
        status="estimated",
        gas_m3=gas,
        duration_seconds=duration,
        gas_cost_eur=cost if finite(cost) else None,
        electricity=auxiliary_estimate(validated, duration),
        reason="CV-opwarming geraamd; plannen vereisen handhaafbewijs en een passende HEMS-basis.",
    )
