"""Deterministic capability discovery for PicoT HEMS.

Discovery only produces candidates and factual evidence. It never ranks, selects,
or infers a capability from a vendor name alone.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from capabilities import get_capabilities


_POWER_UNITS = {"w", "kw", "mw"}
_ENERGY_UNITS = {"wh", "kwh", "mwh"}
_TEMPERATURE_UNITS = {"°c", "c", "°f", "f"}
_BATTERY_TOKENS = {"battery", "batterij", "accu", "soc", "stateofcharge", "state_of_charge"}
_MODULE_TOKENS = {"module", "pack", "unit", "slave"}
_SYSTEM_TOKENS = {"system", "systeem", "overall", "aggregate", "combined", "totaal", "totale", "total"}
_CAPACITY_TOKENS = {"capacity", "capaciteit", "rated", "nominal", "nominaal"}
_USABLE_TOKENS = {"usable", "useable", "available", "bruikbaar", "bruikbare", "beschikbaar", "beschikbare"}
_COUNT_TOKENS = {"count", "aantal", "modules", "batteries", "batterijen", "packs", "units"}
_MIN_TOKENS = {"min", "minimum", "lower", "ondergrens", "ontlaadgrens", "reserve"}
_MAX_TOKENS = {"max", "maximum", "upper", "bovengrens", "laadgrens"}
_TEMPERATURE_TOKENS = {"temperature", "temperatuur", "temp"}
_HEALTH_TOKENS = {"health", "gezondheid", "soh", "stateofhealth", "state_of_health"}
_BALANCE_TOKENS = {"balance", "balancing", "balanced", "balans", "balanceren", "gebalanceerd"}


def _entity_domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _entity_text(entity: dict[str, Any]) -> str:
    attributes = entity.get("attributes") or {}
    return " ".join(
        _normalized(value)
        for value in (
            entity.get("entity_id"),
            entity.get("original_name"),
            entity.get("name"),
            attributes.get("friendly_name"),
        )
    )


def _tokens(entity: dict[str, Any]) -> set[str]:
    text = _entity_text(entity)
    for character in "._-/:()[]":
        text = text.replace(character, " ")
    return {token for token in text.split() if token}


def _has_battery_identity(tokens: set[str], device_class: str) -> bool:
    return device_class == "battery" or bool(tokens.intersection(_BATTERY_TOKENS))


def _has_module_context(entity: dict[str, Any], tokens: set[str]) -> bool:
    if tokens.intersection(_MODULE_TOKENS):
        return True

    # Numeric suffixes are only module evidence when directly attached to an
    # explicit battery noun, for example "battery_2" or "batterij 3".
    text = _entity_text(entity)
    return bool(
        re.search(
            r"(?:battery|batterij|accu|module|pack)[\s._-]*[1-9]\d*(?:\b|_)",
            text,
        )
    )


def _candidate_record(entity: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    attributes = entity.get("attributes") or {}
    return {
        "entity_id": entity.get("entity_id"),
        "domain": _entity_domain(str(entity.get("entity_id", ""))),
        "device_id": entity.get("device_id"),
        "config_entry_id": entity.get("config_entry_id"),
        "platform": entity.get("platform"),
        "state": entity.get("state"),
        "device_class": entity.get("device_class") or attributes.get("device_class"),
        "state_class": entity.get("state_class") or attributes.get("state_class"),
        "unit_of_measurement": entity.get("unit_of_measurement") or attributes.get("unit_of_measurement"),
        "reasons": reasons,
    }


def _match_battery(entity: dict[str, Any]) -> list[tuple[str, list[str]]]:
    entity_id = str(entity.get("entity_id", ""))
    domain = _entity_domain(entity_id)
    attributes = entity.get("attributes") or {}
    device_class = _normalized(entity.get("device_class") or attributes.get("device_class"))
    state_class = _normalized(entity.get("state_class") or attributes.get("state_class"))
    unit = _normalized(entity.get("unit_of_measurement") or attributes.get("unit_of_measurement"))
    tokens = _tokens(entity)
    matches: list[tuple[str, list[str]]] = []

    if not _has_battery_identity(tokens, device_class):
        return matches

    is_module = _has_module_context(entity, tokens)
    scope_reason = "explicit_module_context" if is_module else "no_module_context"

    if domain == "sensor":
        soc_evidence = (
            device_class == "battery"
            or unit == "%"
            or "soc" in tokens
            or {"state", "charge"}.issubset(tokens)
            or {"state", "of", "charge"}.issubset(tokens)
            or {"laad", "percentage"}.issubset(tokens)
            or "laadpercentage" in tokens
        )
        if soc_evidence:
            capability_id = (
                "battery.module.observation.soc"
                if is_module
                else "battery.system.observation.soc"
            )
            matches.append((capability_id, ["sensor", "battery_soc_evidence", scope_reason, f"unit:{unit or 'none'}"]))

        if (device_class == "power" or unit in _POWER_UNITS) and not tokens.intersection(_CAPACITY_TOKENS):
            if not is_module:
                matches.append(("battery.system.observation.power", ["sensor", "power", "battery_identity", scope_reason]))

        energy_semantics = device_class == "energy" or state_class in {"total", "total_increasing"} or unit in _ENERGY_UNITS
        if energy_semantics:
            if tokens.intersection(_USABLE_TOKENS) and tokens.intersection(_CAPACITY_TOKENS):
                if not is_module:
                    matches.append(("battery.system.observation.capacity.usable", ["sensor", "energy_unit", "usable_capacity_tokens", scope_reason]))
            elif tokens.intersection(_CAPACITY_TOKENS):
                if not is_module:
                    matches.append(("battery.system.observation.capacity.total", ["sensor", "energy_unit", "capacity_tokens", scope_reason]))
            elif not is_module:
                matches.append(("battery.system.observation.energy", ["sensor", "energy", "battery_identity", scope_reason]))

        if tokens.intersection(_COUNT_TOKENS) and (
            "module" in tokens
            or "modules" in tokens
            or "batteries" in tokens
            or "batterijen" in tokens
            or "packs" in tokens
        ):
            matches.append(("battery.system.observation.module_count", ["sensor", "battery_module_count_tokens"]))

        if is_module and (
            device_class == "temperature"
            or unit in _TEMPERATURE_UNITS
            or tokens.intersection(_TEMPERATURE_TOKENS)
        ):
            matches.append(("battery.module.observation.temperature", ["sensor", "temperature_evidence", scope_reason, f"unit:{unit or 'none'}"]))

        if is_module and tokens.intersection(_HEALTH_TOKENS):
            matches.append(("battery.module.observation.health", ["sensor", "health_tokens", scope_reason]))

        if is_module and tokens.intersection(_BALANCE_TOKENS):
            matches.append(("battery.module.observation.balance_status", ["sensor", "balance_tokens", scope_reason]))

    if domain in {"sensor", "number"} and unit == "%":
        if tokens.intersection(_MIN_TOKENS):
            matches.append(("battery.system.configuration.soc_min", [f"domain:{domain}", "percent_unit", "minimum_soc_tokens"]))
        if tokens.intersection(_MAX_TOKENS):
            matches.append(("battery.system.configuration.soc_max", [f"domain:{domain}", "percent_unit", "maximum_soc_tokens"]))

    return matches


def _match_observation(entity: dict[str, Any]) -> list[tuple[str, list[str]]]:
    entity_id = str(entity.get("entity_id", ""))
    domain = _entity_domain(entity_id)
    attributes = entity.get("attributes") or {}
    device_class = _normalized(entity.get("device_class") or attributes.get("device_class"))
    state_class = _normalized(entity.get("state_class") or attributes.get("state_class"))
    unit = _normalized(entity.get("unit_of_measurement") or attributes.get("unit_of_measurement"))
    tokens = _tokens(entity)
    matches = _match_battery(entity)

    if domain == "sensor":
        if device_class == "power" or unit in _POWER_UNITS:
            if tokens.intersection({"pv", "solar", "photovoltaic", "inverter", "omvormer"}):
                matches.append(("pv.observation.power", ["sensor", "power", "pv_token"]))
            if tokens.intersection({"grid", "net", "meter", "p1"}):
                if tokens.intersection({"import", "consumption", "afname", "in"}):
                    matches.append(("grid.observation.import_power", ["sensor", "power", "grid_import_token"]))
                if tokens.intersection({"export", "production", "teruglevering", "terugleveren", "out"}):
                    matches.append(("grid.observation.export_power", ["sensor", "power", "grid_export_token"]))

        if device_class == "energy" or state_class in {"total", "total_increasing"} or unit in _ENERGY_UNITS:
            if tokens.intersection({"pv", "solar", "photovoltaic", "inverter", "omvormer"}):
                matches.append(("pv.observation.energy", ["sensor", "energy", "pv_token"]))
            if tokens.intersection({"grid", "net", "meter", "p1"}):
                if tokens.intersection({"import", "consumption", "afname", "in"}):
                    matches.append(("grid.observation.import_energy", ["sensor", "energy", "grid_import_token"]))
                if tokens.intersection({"export", "production", "teruglevering", "terugleveren", "out"}):
                    matches.append(("grid.observation.export_energy", ["sensor", "energy", "grid_export_token"]))

        if device_class in {"monetary", "currency"} or unit in {"eur/kwh", "€/kwh", "eur", "€"}:
            if tokens.intersection({"price", "tariff", "tarief", "prijs"}):
                matches.append(("market.price.current", ["sensor", "price", f"unit:{unit or 'none'}"]))

    if domain in {"weather", "sensor"} and tokens.intersection({"weather", "forecast", "weer", "meteo"}):
        matches.append(("weather.forecast", [f"domain:{domain}", "forecast_token"]))

    if domain == "sensor" and tokens.intersection({"forecast", "prices", "prijzen"}) and tokens.intersection({"price", "tariff", "tarief", "prijs"}):
        matches.append(("market.price.forecast", ["sensor", "price_forecast_tokens"]))

    return matches


def _match_control(entity: dict[str, Any]) -> list[tuple[str, list[str]]]:
    entity_id = str(entity.get("entity_id", ""))
    domain = _entity_domain(entity_id)
    tokens = _tokens(entity)
    matches: list[tuple[str, list[str]]] = []

    generic = {
        "switch": "device.switch",
        "number": "device.number",
        "select": "device.select",
        "button": "device.button",
    }
    if domain in generic:
        matches.append((generic[domain], [f"domain:{domain}"]))

    if domain in {"switch", "number", "select", "button"} and tokens.intersection({"battery", "batterij", "accu"}):
        if tokens.intersection({"charge", "charging", "laden", "laad"}):
            matches.append(("battery.control.charge", [f"domain:{domain}", "battery_token", "charge_token"]))
        if tokens.intersection({"discharge", "discharging", "ontladen", "ontlaad"}):
            matches.append(("battery.control.discharge", [f"domain:{domain}", "battery_token", "discharge_token"]))
        if tokens.intersection({"standby", "idle", "pause", "stop"}):
            matches.append(("battery.control.standby", [f"domain:{domain}", "battery_token", "standby_token"]))

    return matches


def discover_capabilities(structure: dict[str, list[dict[str, Any]]], states: list[dict[str, Any]]) -> dict[str, Any]:
    """Discover capability candidates without ranking or selection."""
    registry_entities = structure.get("entities", [])
    state_by_entity_id = {state.get("entity_id"): state for state in states if state.get("entity_id")}
    entity_by_id: dict[str, dict[str, Any]] = {}

    for registry_entity in registry_entities:
        entity_id = registry_entity.get("entity_id")
        if not entity_id:
            continue
        merged = dict(registry_entity)
        state = state_by_entity_id.get(entity_id)
        if state:
            merged["state"] = state.get("state")
            merged["attributes"] = state.get("attributes") or {}
        entity_by_id[entity_id] = merged

    for entity_id, state in state_by_entity_id.items():
        if entity_id not in entity_by_id:
            entity_by_id[entity_id] = {
                "entity_id": entity_id,
                "state": state.get("state"),
                "attributes": state.get("attributes") or {},
                "source": "state_only",
            }

    capability_catalog = {capability.id: capability for capability in get_capabilities()}
    candidates: dict[str, list[dict[str, Any]]] = {capability_id: [] for capability_id in capability_catalog}

    for entity in entity_by_id.values():
        if entity.get("disabled_by") is not None:
            continue
        seen: set[str] = set()
        for capability_id, reasons in _match_observation(entity) + _match_control(entity):
            if capability_id not in capability_catalog or capability_id in seen:
                continue
            candidates[capability_id].append(_candidate_record(entity, reasons))
            seen.add(capability_id)

    capability_rows = []
    for capability_id, capability in capability_catalog.items():
        capability_candidates = sorted(candidates[capability_id], key=lambda item: str(item.get("entity_id")))
        capability_rows.append(
            {
                "id": capability.id,
                "category": capability.category,
                "kind": capability.kind,
                "description": capability.description,
                "candidate_count": len(capability_candidates),
                "candidates": capability_candidates,
            }
        )

    category_counts = Counter(row["category"] for row in capability_rows)
    populated_counts = Counter(row["category"] for row in capability_rows if row["candidate_count"] > 0)
    candidate_count = sum(row["candidate_count"] for row in capability_rows)

    return {
        "metadata": {
            "schema": "picot_hems.capability.discovery",
            "schema_version": "0.3.0",
            "method": "deterministic_rules",
            "selection_performed": False,
        },
        "capabilities": capability_rows,
        "summary": {
            "capability_count": len(capability_rows),
            "populated_capability_count": sum(1 for row in capability_rows if row["candidate_count"] > 0),
            "empty_capability_count": sum(1 for row in capability_rows if row["candidate_count"] == 0),
            "candidate_count": candidate_count,
            "entities_evaluated": len(entity_by_id),
        },
        "statistics": {
            "capabilities_by_category": dict(sorted(category_counts.items())),
            "populated_capabilities_by_category": dict(sorted(populated_counts.items())),
            "candidates_by_capability": {
                row["id"]: row["candidate_count"] for row in capability_rows
            },
        },
    }
