"""Deterministic capability discovery for PicoT HEMS."""

from __future__ import annotations

from collections import Counter
from typing import Any

from capabilities import get_capabilities


def _entity_domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokens(entity: dict[str, Any]) -> set[str]:
    entity_id = _normalized(entity.get("entity_id"))
    original_name = _normalized(entity.get("original_name"))
    name = _normalized(entity.get("name"))
    friendly_name = _normalized(entity.get("attributes", {}).get("friendly_name"))
    text = " ".join((entity_id, original_name, name, friendly_name))
    for character in "._-/:()[]":
        text = text.replace(character, " ")
    return {token for token in text.split() if token}


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


def _match_observation(entity: dict[str, Any]) -> list[tuple[str, list[str]]]:
    entity_id = str(entity.get("entity_id", ""))
    domain = _entity_domain(entity_id)
    attributes = entity.get("attributes") or {}
    device_class = _normalized(entity.get("device_class") or attributes.get("device_class"))
    state_class = _normalized(entity.get("state_class") or attributes.get("state_class"))
    unit = _normalized(entity.get("unit_of_measurement") or attributes.get("unit_of_measurement"))
    tokens = _tokens(entity)
    matches: list[tuple[str, list[str]]] = []

    if domain == "sensor":
        if device_class == "battery" or unit == "%" or "soc" in tokens or {"state", "charge"}.issubset(tokens):
            if "battery" in tokens or device_class == "battery" or "soc" in tokens:
                matches.append(("battery.observation.soc", ["sensor", "battery_or_soc", f"unit:{unit or 'none'}"]))

        if device_class == "power" or unit in {"w", "kw", "mw"}:
            if "battery" in tokens or "accu" in tokens:
                matches.append(("battery.observation.power", ["sensor", "power", "battery_token"]))
            if tokens.intersection({"pv", "solar", "photovoltaic", "inverter", "omvormer"}):
                matches.append(("pv.observation.power", ["sensor", "power", "pv_token"]))
            if tokens.intersection({"grid", "net", "meter", "p1"}):
                if tokens.intersection({"import", "consumption", "afname", "in"}):
                    matches.append(("grid.observation.import_power", ["sensor", "power", "grid_import_token"]))
                if tokens.intersection({"export", "production", "teruglevering", "out"}):
                    matches.append(("grid.observation.export_power", ["sensor", "power", "grid_export_token"]))

        if device_class == "energy" or state_class in {"total", "total_increasing"} or unit in {"wh", "kwh", "mwh"}:
            if "battery" in tokens or "accu" in tokens:
                matches.append(("battery.observation.energy", ["sensor", "energy", "battery_token"]))
            if tokens.intersection({"pv", "solar", "photovoltaic", "inverter", "omvormer"}):
                matches.append(("pv.observation.energy", ["sensor", "energy", "pv_token"]))
            if tokens.intersection({"grid", "net", "meter", "p1"}):
                if tokens.intersection({"import", "consumption", "afname", "in"}):
                    matches.append(("grid.observation.import_energy", ["sensor", "energy", "grid_import_token"]))
                if tokens.intersection({"export", "production", "teruglevering", "out"}):
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

    if domain in {"switch", "number", "select", "button"} and tokens.intersection({"battery", "accu"}):
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
            "schema_version": "0.2.0",
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
