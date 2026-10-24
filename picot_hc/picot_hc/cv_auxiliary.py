"""Explicit CV auxiliary assumptions, kept separate from measured electricity."""

from .energy_model import finite


def assumptions(config):
    if config.get("cv_auxiliary_mode", "measured") != "estimated":
        return None
    # Do not silently replace a configured but faulty dedicated meter.
    if config.get("cv_power") or config.get("cv_energy"):
        return None
    fields = {
        "running_power_w": config.get("cv_auxiliary_running_w"),
        "postrun_power_w": config.get("cv_auxiliary_postrun_w"),
        "postrun_seconds": config.get("cv_auxiliary_postrun_seconds"),
    }
    if not all(finite(v) for v in fields.values()):
        return None
    if (
        not 0 < fields["running_power_w"] <= 2000
        or not 0 <= fields["postrun_power_w"] <= 2000
        or not 0 <= fields["postrun_seconds"] <= 3600
    ):
        return None
    return fields


def estimate(parameters, duration_seconds):
    if parameters is None or not finite(duration_seconds) or not 0 < duration_seconds <= 86400:
        return dict(status="unavailable")
    running = parameters["running_power_w"] * duration_seconds / 3600
    tail = parameters["postrun_power_w"] * parameters["postrun_seconds"] / 3600
    return dict(
        status="estimated",
        method="configured_cv_auxiliary_power",
        assumptions=dict(parameters),
        duration_seconds=duration_seconds,
        energy_wh=running,
        postrun_energy_wh=tail,
        total_energy_if_stopped_wh=running + tail,
        postrun_included_in_energy_wh=False,
        measured=False,
        forecast_eligible=False,
        forecast_reason="cv_baseline_attribution_required",
    )
