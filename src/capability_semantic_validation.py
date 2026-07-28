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
_TEMPERATURE_UNITS = {"°c", "c", "°f", "f"}
_PORTABLE_PLATFORMS = {"mobile_app"}
_PORTABLE_TOKENS = {
    "iphone", "ipad", "phone", "smartphone", "mobile", "mobiel", "tablet",
    "laptop", "macbook", "watch", "telefoon", "headset", "earbuds",
}
_CAPACITY_TOKENS = {"capacity", "capaciteit", "rated", "nominal", "nominaal"}
_USABLE_TOKENS = {"usable", "useable", "available", "bruikbaar", "bruikbare", "beschikbaar", "beschikbare"}
_COUNT_TOKENS = {"count", "aantal", "modules", "batteries", "batterijen", "packs", "units"}
_MIN_TOKENS = {"min", "minimum", "lower", "ondergrens", "ontlaadgrens", "reserve"}
_MAX_TOKENS = {"max", "maximum", "upper", "bovengrens", "laadgrens"}
_MODULE_TOKENS = {"module", "pack", "unit", "slave"}
_TEMPERATURE_TOKENS = {"temperature", "temperatuur", "temp"}
_HEALTH_TOKENS = {"health", "gezondheid", "soh", "stateofhealth", "state_of_health"}
_BALANCE_TOKENS = {"balance", "balancing", "balanced", "balans", "balanceren", "gebalanceerd"}
_ENERGY_TOKENS = {"energy", "energie", "yield", "opbrengst", "production", "productie"}
_BATTERY_TOKENS = {"battery", "batterij", "accu", "soc", "stateofcharge", "state_of_charge"}
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


def _discovery_reasons(candidate: dict[str, Any]) -> set[str]:
    return {_normalized(reason) for reason in candidate.get("reasons") or []}


def _has_module_context(candidate: dict[str, Any], tokens: set[str]) -> bool:
    return "explicit_module_context" in _discovery_reasons(candidate) or bool(tokens.intersection(_MODULE_TOKENS))


def _numeric_state(candidate: dict[str, Any]) -> float | None:
    raw = candidate.get("state")
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _validate_battery_identity(tokens: set[str], reasons: list[str]) -> None:
    if not tokens.intersection(_BATTERY_TOKENS):
        reasons.append("battery_identity_not_evidenced")


def _validate_battery_scope(
    capability_id: str,
    candidate: dict[str, Any],
    tokens: set[str],
    reasons: list[str],
) -> None:
    is_module = _has_module_context(candidate, tokens)
    if capability_id.startswith("battery.system.") and is_module:
        reasons.append("module_candidate_not_valid_for_system_capability")
    if capability_id.startswith("battery.module.") and not is_module:
        reasons.append("module_context_not_evidenced")


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

    if capability_id.startswith("battery.system.") or capability_id.startswith("battery.module."):
        _validate_battery_identity(tokens, reasons)
        _validate_battery_scope(capability_id, candidate, tokens, reasons)

    if capability_id in {"battery.system.observation.soc", "battery.module.observation.soc"}:
        if platform in _PORTABLE_PLATFORMS or tokens.intersection(_PORTABLE_TOKENS):
            reasons.append("portable_device_battery_not_home_battery")
        if domain != "sensor":
            reasons.append("battery_soc_requires_sensor")
        if unit != "%":
            reasons.append("battery_soc_requires_percent_unit")
        value = _numeric_state(candidate)
        if value is not None and not 0 <= value <= 100:
            reasons.append("battery_soc_out_of_range")

    elif capability_id in {
        "battery.system.observation.power", "pv.observation.power",
        "grid.observation.import_power", "grid.observation.export_power",
    }:
        if domain != "sensor":
            reasons.append("power_observation_requires_sensor")
        if device_class != "power" and unit not in _POWER_UNITS:
            reasons.append("instantaneous_power_semantics_missing")
        if tokens.intersection(_CAPACITY_TOKENS):
            reasons.append("rated_capacity_not_instantaneous_power")
        if tokens.intersection({"energy", "energie", "today", "total", "daily"}):
            reasons.append("energy_counter_not_instantaneous_power")
        if capability_id.startswith("pv.") and not tokens.intersection(_PV_TOKENS):
            reasons.append("pv_identity_not_evidenced")
        if capability_id.startswith("grid.") and not tokens.intersection(_GRID_TOKENS):
            reasons.append("grid_identity_not_evidenced")
        if capability_id.endswith("import_power") and not tokens.intersection(_IMPORT_TOKENS):
            reasons.append("grid_import_direction_not_evidenced")
        if capability_id.endswith("export_power") and not tokens.intersection(_EXPORT_TOKENS):
            reasons.append("grid_export_direction_not_evidenced")

    elif capability_id in {
        "battery.system.observation.energy", "pv.observation.energy",
        "grid.observation.import_energy", "grid.observation.export_energy",
    }:
        if domain != "sensor":
            reasons.append("energy_observation_requires_sensor")
        if device_class != "energy" and unit not in _ENERGY_UNITS:
            reasons.append("energy_semantics_missing")
        if tokens.intersection(_CAPACITY_TOKENS):
            reasons.append("rated_capacity_not_measured_energy")
        if capability_id.startswith("pv."):
            if not tokens.intersection(_PV_TOKENS):
                reasons.append("pv_identity_not_evidenced")
            if tokens.intersection({"battery", "batterij", "accu", "charge", "charging", "laden", "laad"}):
                reasons.append("battery_charge_energy_not_pv_energy")
        if capability_id.startswith("grid.") and not tokens.intersection(_GRID_TOKENS):
            reasons.append("grid_identity_not_evidenced")
        if capability_id.endswith("import_energy") and not tokens.intersection(_IMPORT_TOKENS):
            reasons.append("grid_import_direction_not_evidenced")
        if capability_id.endswith("export_energy") and not tokens.intersection(_EXPORT_TOKENS):
            reasons.append("grid_export_direction_not_evidenced")

    elif capability_id in {
        "battery.system.observation.capacity.total",
        "battery.system.observation.capacity.usable",
    }:
        if domain != "sensor":
            reasons.append("battery_capacity_requires_sensor")
        if device_class != "energy" and unit not in _ENERGY_UNITS:
            reasons.append("battery_capacity_requires_energy_unit")
        if not tokens.intersection(_CAPACITY_TOKENS):
            reasons.append("capacity_semantics_missing")
        usable_evidenced = bool(tokens.intersection(_USABLE_TOKENS))
        if capability_id.endswith("capacity.usable") and not usable_evidenced:
            reasons.append("usable_capacity_semantics_missing")
        if capability_id.endswith("capacity.total") and usable_evidenced:
            reasons.append("usable_capacity_not_total_capacity")
        value = _numeric_state(candidate)
        if value is not None and value <= 0:
            reasons.append("battery_capacity_not_positive")

    elif capability_id == "battery.system.observation.module_count":
        if domain != "sensor":
            reasons.append("module_count_requires_sensor")
        if unit not in {"", "none", "modules", "batteries", "batterijen", "packs"}:
            reasons.append("module_count_requires_count_unit")
        if not tokens.intersection(_COUNT_TOKENS):
            reasons.append("module_count_semantics_missing")
        value = _numeric_state(candidate)
        if value is not None and (value < 0 or not value.is_integer()):
            reasons.append("module_count_requires_non_negative_integer")

    elif capability_id in {
        "battery.system.configuration.soc_min",
        "battery.system.configuration.soc_max",
    }:
        if domain not in {"sensor", "number"}:
            reasons.append("battery_soc_limit_domain_not_supported")
        if unit != "%":
            reasons.append("battery_soc_limit_requires_percent_unit")
        expected_tokens = _MIN_TOKENS if capability_id.endswith("soc_min") else _MAX_TOKENS
        if not tokens.intersection(expected_tokens):
            reasons.append("battery_soc_limit_semantics_missing")
        value = _numeric_state(candidate)
        if value is not None and not 0 <= value <= 100:
            reasons.append("battery_soc_limit_out_of_range")

    elif capability_id == "battery.module.observation.temperature":
        if domain != "sensor":
            reasons.append("module_temperature_requires_sensor")
        if device_class != "temperature" and unit not in _TEMPERATURE_UNITS:
            reasons.append("temperature_semantics_missing")
        if not tokens.intersection(_TEMPERATURE_TOKENS) and device_class != "temperature":
            reasons.append("module_temperature_identity_not_evidenced")

    elif capability_id == "battery.module.observation.health":
        if domain != "sensor":
            reasons.append("module_health_requires_sensor")
        if not tokens.intersection(_HEALTH_TOKENS):
            reasons.append("module_health_semantics_missing")
        if unit not in {"", "%"}:
            reasons.append("module_health_unit_not_supported")

    elif capability_id == "battery.module.observation.balance_status":
        if domain not in {"sensor", "binary_sensor"}:
            reasons.append("module_balance_status_domain_not_supported")
        if not tokens.intersection(_BALANCE_TOKENS):
            reasons.append("module_balance_semantics_missing")

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
        _validate_battery_identity(tokens, reasons)
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
        capability_id = capability["id"]
        validated_candidates: list[dict[str, Any]] = []
        for candidate in capability.get("candidates") or []:
            status, reasons = _validate_candidate(capability_id, candidate)
            record = dict(candidate)
            record["semantic_validation"] = {"status": status, "reasons": reasons}
            if capability_id.startswith("battery.system.configuration."):
                record["configuration_governance"] = {
                    "management": "external",
                    "writable_by_picot": False,
                    "configuration_source": candidate.get("platform") or candidate.get("config_entry_id"),
                }
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
            "schema_version": "0.2.0",
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
