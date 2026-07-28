"""Deterministic semantic validation for PicoT capability candidates.

This layer sits between capability discovery and capability selection. It never
selects an entity. It validates whether the factual semantics of each candidate
fit the stable capability ID and preserves every candidate with explicit rules
and reasons for auditability.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


_POWER_UNITS = {"w", "kw", "mw"}
_ENERGY_UNITS = {"wh", "kwh", "mwh"}
_PORTABLE_PLATFORMS = {"mobile_app"}
_PORTABLE_TOKENS = {
    "iphone", "ipad", "phone", "smartphone", "mobile", "mobiel", "tablet",
    "laptop", "macbook", "watch", "telefoon", "headset", "earbuds",
}
_CAPACITY_TOKENS = {"capacity", "capaciteit", "rated", "nominal", "nominaal"}
_CURRENT_POWER_TOKENS = {"power", "vermogen", "current", "active", "actual"}
_ENERGY_TOKENS = {"energy", "energie", "yield", "opbrengst", "production", "productie"}
_BATTERY_TOKENS = {"battery", "accu", "soc", "state_of_charge", "zendure"}
_PV_TOKENS = {"pv", "solar", "photovoltaic", "inverter", "omvormer", "yield", "opbrengst"}
_GRID_TOKENS = {"grid", "net", "meter", "p1"}
_IMPORT_TOKENS = {"import", "consumption", "afname", "in"}
_EXPORT_TOKENS = {"export", "production", "teruglevering", "terugleveren", "out"}
_FORECAST_TOKENS = {"forecast", "prices", "prijzen", "tomorrow", "morgen"}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokens(candidate: dict[str, Any]) -> set[str]:
    text = " ".join(
        _normalized(candidate.get(field))
        for field in ("entity_id", "platform", "device_class", "state_class", "unit_of_measurement")
    )
    for character in ". _-/:()[]":
        text = text.replace(character, " ")
    return {token for token in text.split() if token}


def _validate_candidate(capability_id: str, candidate: dict[str, Any]) -> tuple[str, list[str]]:
    """Return VALID or REJECTED plus deterministic semantic reasons."""
    tokens = _tokens(candidate)
    domain = _normalized(candidate.get("domain"))
    platform = _normalized(candidate.get("platform"))
    device_class = _normalized(candidate.get("device_class"))
    unit = _normalized(candidate.get("unit_of_measurement"))
    reasons: list[str] = []

    if capability_id.startswith("device."):
        return "REJECTED", ["generic_control_requires_explicit_assignment"]

    if capability_id == "battery.observation.soc":
        if platform in _PORTABLE_PLATFORMS or tokens.intersection(_PORTABLE_TOKENS):
            reasons.append("portable_device_battery_not_home_battery")
        if domain != "sensor":
            reasons.append("battery_soc_requires_sensor")
        if unit != "%":
            reasons.append("battery_soc_requires_percent_unit")
        if not tokens.intersection(_BATTERY_TOKENS):
            reasons.append("battery_identity_not_evidenced")

    elif capability_id in {
        "battery.observation.power", "pv.observation.power",
        "grid.observation.import_power", "grid.observation.export_power",
    }:
        if domain != "sensor":
            reasons.append("power_observation_requires_sensor")
        if device_class != "power" and unit not in _POWER_UNITS:
            reasons.append("instantaneous_power_semantics_missing")
        if tokens.intersection(_CAPACITY_TOKENS) and not tokens.intersection(_CURRENT_POWER_TOKENS):
            reasons.append("rated_capacity_not_instantaneous_power")
        if tokens.intersection({"energy", "energie", "today", "total", "daily"}):
            reasons.append("energy_counter_not_instantaneous_power")
        if capability_id.startswith("battery.") and not tokens.intersection(_BATTERY_TOKENS):
            reasons.append("battery_identity_not_evidenced")
        if capability_id.startswith("pv.") and not tokens.intersection(_PV_TOKENS):
            reasons.append("pv_identity_not_evidenced")
        if capability_id.startswith("grid.") and not tokens.intersection(_GRID_TOKENS):
            reasons.append("grid_identity_not_evidenced")
        if capability_id.endswith("import_power") and not tokens.intersection(_IMPORT_TOKENS):
            reasons.append("grid_import_direction_not_evidenced")
        if capability_id.endswith("export_power") and not tokens.intersection(_EXPORT_TOKENS):
            reasons.append("grid_export_direction_not_evidenced")

    elif capability_id in {
        "battery.observation.energy", "pv.observation.energy",
        "grid.observation.import_energy", "grid.observation.export_energy",
    }:
        if domain != "sensor":
            reasons.append("energy_observation_requires_sensor")
        if device_class != "energy" and unit not in _ENERGY_UNITS:
            reasons.append("energy_semantics_missing")
        if tokens.intersection(_CAPACITY_TOKENS):
            reasons.append("rated_capacity_not_measured_energy")
        if capability_id.startswith("battery.") and not tokens.intersection(_BATTERY_TOKENS):
            reasons.append("battery_identity_not_evidenced")
        if capability_id.startswith("pv."):
            if not tokens.intersection(_PV_TOKENS):
                reasons.append("pv_identity_not_evidenced")
            if tokens.intersection({"battery", "accu", "charge", "charging", "laden", "laad"}):
                reasons.append("battery_charge_energy_not_pv_energy")
        if capability_id.startswith("grid.") and not tokens.intersection(_GRID_TOKENS):
            reasons.append("grid_identity_not_evidenced")
        if capability_id.endswith("import_energy") and not tokens.intersection(_IMPORT_TOKENS):
            reasons.append("grid_import_direction_not_evidenced")
        if capability_id.endswith("export_energy") and not tokens.intersection(_EXPORT_TOKENS):
            reasons.append("grid_export_direction_not_evidenced")

    elif capability_id == "market.price.current":
        if tokens.intersection(_FORECAST_TOKENS):
            reasons.append("forecast_price_not_current_price")
        if not tokens.intersection({"price", "tariff", "tarief", "prijs"}):
            reasons.append("price_semantics_missing")

    elif capability_id == "market.price.forecast":
        if not tokens.intersection(_FORECAST_TOKENS):
            reasons.append("price_forecast_semantics_missing")
        if not tokens.intersection({"price", "tariff", "tarief", "prijs", "prices", "prijzen"}):
            reasons.append("price_semantics_missing")

    elif capability_id == "weather.forecast":
        if domain != "weather" and not tokens.intersection({"weather", "weer", "meteo", "forecast"}):
            reasons.append("weather_forecast_semantics_missing")

    elif capability_id.startswith("battery.control."):
        if domain not in {"switch", "number", "select", "button"}:
            reasons.append("battery_control_domain_not_supported")
        if not tokens.intersection(_BATTERY_TOKENS):
            reasons.append("battery_identity_not_evidenced")
        action = capability_id.rsplit(".", 1)[-1]
        action_tokens = {
            "charge": {"charge", "charging", "laden", "laad"},
            "discharge": {"discharge", "discharging", "ontladen", "ontlaad"},
            "standby": {"standby", "idle", "pause", "stop"},
        }[action]
        if not tokens.intersection(action_tokens):
            reasons.append(f"{action}_control_semantics_missing")

    return ("REJECTED", reasons) if reasons else ("VALID", ["semantic_rules_satisfied"])


def validate_capability_candidates(discovery_result: dict[str, Any]) -> dict[str, Any]:
    """Validate all candidates and preserve them with an explicit audit result."""
    capabilities: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for capability in discovery_result.get("capabilities", []):
        validated_candidates: list[dict[str, Any]] = []
        for candidate in capability.get("candidates") or []:
            status, reasons = _validate_candidate(capability["id"], candidate)
            record = dict(candidate)
            record["semantic_validation"] = {"status": status, "reasons": reasons}
            validated_candidates.append(record)
            status_counts[status] += 1

        valid_count = sum(
            1 for candidate in validated_candidates
            if candidate["semantic_validation"]["status"] == "VALID"
        )
        capabilities.append({
            **{key: value for key, value in capability.items() if key != "candidates"},
            "candidate_count": len(validated_candidates),
            "semantically_valid_candidate_count": valid_count,
            "semantically_rejected_candidate_count": len(validated_candidates) - valid_count,
            "candidates": validated_candidates,
        })

    return {
        "metadata": {
            "schema": "picot_hems.capability.semantic_validation",
            "schema_version": "0.1.0",
            "method": "fixed_semantic_rules",
            "selection_performed": False,
            "learning_used": False,
            "probabilistic_validation": False,
        },
        "summary": {
            "capability_count": len(capabilities),
            "candidate_count": sum(row["candidate_count"] for row in capabilities),
            "valid_candidate_count": status_counts["VALID"],
            "rejected_candidate_count": status_counts["REJECTED"],
            "status_counts": dict(sorted(status_counts.items())),
        },
        "capabilities": capabilities,
    }
