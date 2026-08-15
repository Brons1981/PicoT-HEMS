"""Authoritative Home Assistant ingestion for PicoT v2 Planning Input.

HA entity ids exist only in source evidence. Canonical facts and forecasts are
created once at the ingestion boundary and then carried by one immutable snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import (
    CurrentStorageState,
    PlanningInputSnapshot,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.household_load_forecast import (
    build_fallback_household_load_forecast,
    build_historical_household_load_forecast,
    derive_household_load_power_w,
)


@dataclass(frozen=True, slots=True)
class SourceBinding:
    category: str
    semantic_role: str
    entity_id: str | None


@dataclass(frozen=True, slots=True)
class StorageStateConfig:
    execution_scope_id: str
    capability_id: str
    usable_capacity_wh: float


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    evidence_id: str
    category: str
    semantic_role: str
    entity_id: str | None
    raw_state: str | None
    raw_unit: str | None
    observed_at: datetime | None
    availability: str
    mapping_version: str
    error: str | None = None
    price_points: tuple[PriceForecastPoint, ...] = ()
    pv_energy_intervals: tuple[PVEnergyTimelineInterval, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalInputFact:
    fact_id: str
    run_id: str
    snapshot_id: str
    category: str
    semantic_role: str
    value: float | str | None
    unit: str | None
    observed_at: datetime | None
    availability: str
    evidence_id: str
    mapping_version: str
    confidence: float | None = None
    confidence_status: str = "unassessed"


@dataclass(frozen=True, slots=True)
class HouseholdLoadObservation:
    power_w: float
    sampled_at: datetime
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not isfinite(self.power_w) or self.power_w < 0.0:
            raise ValueError("power_w must be finite and non-negative")
        if self.sampled_at.tzinfo is None:
            raise ValueError("sampled_at must be timezone-aware")
        if not self.evidence_ids:
            raise ValueError("evidence_ids must not be empty")
        if not self.method_version.strip():
            raise ValueError("method_version must be explicit")


@dataclass(frozen=True, slots=True)
class PlanningInputBundle:
    snapshot: PlanningInputSnapshot
    evidence: tuple[SourceEvidence, ...]
    facts: tuple[CanonicalInputFact, ...]
    assembly_started_at: datetime
    assembly_finished_at: datetime
    household_load_observation: HouseholdLoadObservation | None = None


DEFAULT_BINDINGS = (
    ("p1", "grid_power", "p1_power_entity"),
    ("pv", "pv_power", "pv_power_entity"),
    ("zendure", "storage_soc", "zendure_soc_entity"),
    (
        "zendure",
        "storage_power_signed",
        "zendure_signed_power_entity",
    ),
    (
        "zendure",
        "storage_power_to_house",
        "zendure_power_to_house_entity",
    ),
    (
        "zendure",
        "storage_power_from_house",
        "zendure_power_from_house_entity",
    ),
    ("solcast", "pv_forecast", "solcast_forecast_entity"),
    ("nordpool", "energy_price", "nordpool_price_entity"),
)

DEFAULT_STORAGE_POWER_CONSISTENCY_TOLERANCE_W = 25.0
HOUSEHOLD_LOAD_OBSERVATION_METHOD_VERSION = "complete-power-balance:v1"


def _stable_id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def derive_validated_storage_power_w(
    *,
    signed_power_w: float | None,
    power_to_house_w: float | None,
    power_from_house_w: float | None,
    consistency_tolerance_w: float = (
        DEFAULT_STORAGE_POWER_CONSISTENCY_TOLERANCE_W
    ),
) -> float | None:
    """Accept signed storage power only with consistent directional evidence."""
    if (
        signed_power_w is None
        or power_to_house_w is None
        or power_from_house_w is None
    ):
        return None
    values = (
        signed_power_w,
        power_to_house_w,
        power_from_house_w,
    )
    if any(isinstance(value, bool) for value in values):
        return None
    if not all(isfinite(value) for value in values):
        return None
    if power_to_house_w < 0.0 or power_from_house_w < 0.0:
        return None
    if (
        isinstance(consistency_tolerance_w, bool)
        or not isfinite(consistency_tolerance_w)
        or consistency_tolerance_w < 0.0
    ):
        return None

    charge_power_w = max(0.0, signed_power_w)
    discharge_power_w = max(0.0, -signed_power_w)
    if (
        abs(discharge_power_w - power_to_house_w)
        > consistency_tolerance_w
        or abs(charge_power_w - power_from_house_w)
        > consistency_tolerance_w
    ):
        return None
    return signed_power_w


def _household_load_observation_from_evidence(
    evidence: tuple[SourceEvidence, ...],
    *,
    sampled_at: datetime,
) -> HouseholdLoadObservation | None:
    required_roles = (
        "grid_power",
        "pv_power",
        "storage_power_signed",
        "storage_power_to_house",
        "storage_power_from_house",
    )
    available: dict[str, tuple[float, str]] = {}

    for item in evidence:
        if item.semantic_role not in required_roles:
            continue
        if item.semantic_role in available:
            return None
        if (
            item.availability != "available"
            or item.raw_state is None
            or item.raw_unit != "W"
            or item.observed_at is None
        ):
            return None
        try:
            value = float(item.raw_state)
        except ValueError:
            return None
        available[item.semantic_role] = (value, item.evidence_id)

    if set(available) != set(required_roles):
        return None

    storage_power_w = derive_validated_storage_power_w(
        signed_power_w=available["storage_power_signed"][0],
        power_to_house_w=available["storage_power_to_house"][0],
        power_from_house_w=available["storage_power_from_house"][0],
    )
    household_load_power_w = derive_household_load_power_w(
        grid_power_w=available["grid_power"][0],
        pv_power_w=available["pv_power"][0],
        battery_power_w=storage_power_w,
    )
    if household_load_power_w is None:
        return None

    return HouseholdLoadObservation(
        power_w=household_load_power_w,
        sampled_at=sampled_at,
        evidence_ids=tuple(
            available[role][1]
            for role in required_roles
        ),
        method_version=HOUSEHOLD_LOAD_OBSERVATION_METHOD_VERSION,
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else result.replace(tzinfo=UTC)


def _canonical_value(raw_state: str | None) -> float | str | None:
    if raw_state is None:
        return None
    try:
        return float(raw_state)
    except ValueError:
        return raw_state


def _current_storage_states_from_evidence(
    evidence: tuple[SourceEvidence, ...],
    *,
    config: StorageStateConfig | None,
) -> tuple[CurrentStorageState, ...]:
    if config is None or config.usable_capacity_wh <= 0.0:
        return ()

    states: list[CurrentStorageState] = []
    for item in evidence:
        if (
            item.category != "zendure"
            or item.semantic_role != "storage_soc"
            or item.availability != "available"
            or item.raw_state is None
            or item.observed_at is None
        ):
            continue
        try:
            raw_soc = float(item.raw_state)
        except ValueError:
            continue

        current_soc = raw_soc / 100.0 if item.raw_unit == "%" else raw_soc
        if not 0.0 <= current_soc <= 1.0:
            continue

        seed = (
            f"{item.evidence_id}|{config.execution_scope_id}|"
            f"{config.capability_id}|{config.usable_capacity_wh}"
        )
        states.append(
            CurrentStorageState(
                storage_state_id=_stable_id("storage-state", seed),
                execution_scope_id=config.execution_scope_id,
                capability_id=config.capability_id,
                current_soc=current_soc,
                usable_capacity_wh=config.usable_capacity_wh,
                measured_at=item.observed_at,
                confidence=0.0,
                evidence_ids=(item.evidence_id,),
            )
        )
    return tuple(states)


def _pv_forecast_intervals_from_attributes(
    attributes: dict[str, Any],
    *,
    evidence_id: str,
) -> tuple[PVEnergyTimelineInterval, ...]:
    if attributes.get("dataCorrect") is not True:
        return ()

    raw_forecast = attributes.get("detailedForecast")
    analysis = attributes.get("analysis")
    if not isinstance(raw_forecast, list):
        return ()
    if not isinstance(analysis, dict):
        return ()

    confidence_by_start: dict[str, float] = {}
    raw_confidence_intervals = analysis.get("intervals", [])
    if isinstance(raw_confidence_intervals, list):
        for item in raw_confidence_intervals:
            if not isinstance(item, dict):
                continue
            period_start = item.get("period_start")
            confidence = item.get("confidence")
            if (
                isinstance(period_start, str)
                and not isinstance(confidence, bool)
                and isinstance(confidence, (int, float))
            ):
                confidence_by_start[period_start] = float(confidence)

    method_version = (
        "solcast-detailed-forecast-average-kw-30m:v1"
    )
    range_method_version = (
        "solcast-pv-estimate-range-average-kw-30m:v1"
    )
    range_source_fields = (
        "pv_estimate10",
        "pv_estimate",
        "pv_estimate90",
    )
    result: list[PVEnergyTimelineInterval] = []
    for item in raw_forecast:
        if not isinstance(item, dict):
            continue
        raw_start = item.get("period_start")
        starts_at = _parse_datetime(raw_start)
        raw_power_kw = item.get("pv_estimate")
        raw_lower_power_kw = item.get("pv_estimate10")
        raw_upper_power_kw = item.get("pv_estimate90")
        confidence = (
            confidence_by_start.get(raw_start)
            if isinstance(raw_start, str)
            else None
        )
        if (
            starts_at is None
            or isinstance(raw_power_kw, bool)
            or not isinstance(raw_power_kw, (int, float))
            or confidence is None
        ):
            continue

        average_power_kw = float(raw_power_kw)
        if average_power_kw < 0.0:
            continue

        range_values_are_numeric = all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            for value in (raw_lower_power_kw, raw_upper_power_kw)
        )
        lower_energy_wh: float | None = None
        central_energy_wh: float | None = None
        upper_energy_wh: float | None = None
        range_status = "unavailable"
        range_fields: tuple[str, ...] = ()
        range_version: str | None = None
        if range_values_are_numeric:
            lower_power_kw = float(raw_lower_power_kw)
            upper_power_kw = float(raw_upper_power_kw)
            if (
                isfinite(lower_power_kw)
                and isfinite(average_power_kw)
                and isfinite(upper_power_kw)
                and 0.0
                <= lower_power_kw
                <= average_power_kw
                <= upper_power_kw
            ):
                lower_energy_wh = lower_power_kw * 0.5 * 1000.0
                central_energy_wh = average_power_kw * 0.5 * 1000.0
                upper_energy_wh = upper_power_kw * 0.5 * 1000.0
                range_status = "available"
                range_fields = range_source_fields
                range_version = range_method_version

        ends_at = starts_at + timedelta(minutes=30)
        seed = (
            f"{evidence_id}|{starts_at.isoformat()}|"
            f"{ends_at.isoformat()}|{average_power_kw}|"
            f"{method_version}"
        )
        result.append(
            PVEnergyTimelineInterval(
                interval_id=_stable_id(
                    "pv-energy-interval",
                    seed,
                ),
                starts_at=starts_at,
                ends_at=ends_at,
                pv_energy_wh=average_power_kw * 0.5 * 1000.0,
                evidence_type="FORECAST",
                forecast_lower_energy_wh=lower_energy_wh,
                forecast_central_energy_wh=central_energy_wh,
                forecast_upper_energy_wh=upper_energy_wh,
                forecast_range_status=range_status,
                forecast_range_source_fields=range_fields,
                forecast_range_method_version=range_version,
                confidence=confidence,
                actual_evidence_ids=(),
                forecast_evidence_ids=(evidence_id,),
                conversion_method_version=method_version,
            )
        )

    return tuple(
        sorted(
            result,
            key=lambda interval: interval.starts_at,
        )
    )


def _price_points_from_attributes(
    attributes: dict[str, Any],
    *,
    evidence_id: str,
) -> tuple[PriceForecastPoint, ...]:
    raw_points: list[dict[str, Any]] = []
    for key in ("raw_today", "raw_tomorrow"):
        value = attributes.get(key, [])
        if isinstance(value, list):
            raw_points.extend(item for item in value if isinstance(item, dict))

    result: list[PriceForecastPoint] = []
    for item in raw_points:
        starts_at = _parse_datetime(item.get("start"))
        ends_at = _parse_datetime(item.get("end"))
        raw_price = item.get("value", item.get("price"))
        if starts_at is None or ends_at is None or ends_at <= starts_at:
            continue
        if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
            continue
        seed = f"{evidence_id}|{starts_at.isoformat()}|{ends_at.isoformat()}|{float(raw_price)}"
        result.append(
            PriceForecastPoint(
                point_id=_stable_id("price-point", seed),
                starts_at=starts_at,
                ends_at=ends_at,
                value_eur_per_kwh=float(raw_price),
                confidence=1.0,
                evidence_id=evidence_id,
            )
        )
    return tuple(sorted(result, key=lambda point: (point.starts_at, point.ends_at)))


def load_options(options_path: str = "/data/options.json") -> dict[str, Any]:
    path = Path(options_path)
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def load_storage_state_config(
    options_path: str = "/data/options.json",
) -> StorageStateConfig | None:
    options = load_options(options_path)
    execution_scope_id = options.get("storage_execution_scope_id")
    capability_id = options.get("storage_capability_id")
    raw_capacity = options.get("storage_usable_capacity_wh")

    if (
        not isinstance(execution_scope_id, str)
        or not execution_scope_id.strip()
        or not isinstance(capability_id, str)
        or not capability_id.strip()
        or isinstance(raw_capacity, bool)
        or not isinstance(raw_capacity, (int, float))
    ):
        return None

    usable_capacity_wh = float(raw_capacity)
    if usable_capacity_wh <= 0.0:
        return None

    return StorageStateConfig(
        execution_scope_id=execution_scope_id.strip(),
        capability_id=capability_id.strip(),
        usable_capacity_wh=usable_capacity_wh,
    )


def load_bindings(options_path: str = "/data/options.json") -> tuple[SourceBinding, ...]:
    options = load_options(options_path)
    result: list[SourceBinding] = []
    for category, semantic_role, option_key in DEFAULT_BINDINGS:
        raw = options.get(option_key)
        entity_id = raw.strip() if isinstance(raw, str) and raw.strip() else None
        result.append(SourceBinding(category, semantic_role, entity_id))
    return tuple(result)


class HomeAssistantStateReader:
    """Reads each configured HA source exactly once during snapshot assembly."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(self, binding: SourceBinding) -> SourceEvidence:
        mapping_version = _stable_id(
            "mapping", f"{binding.category}|{binding.semantic_role}|{binding.entity_id or 'none'}"
        )
        evidence_id = _stable_id(
            "evidence", f"{mapping_version}|{datetime.now(UTC).isoformat()}"
        )
        if binding.entity_id is None:
            return SourceEvidence(
                evidence_id=evidence_id,
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=None,
                raw_state=None,
                raw_unit=None,
                observed_at=None,
                availability="unconfigured",
                mapping_version=mapping_version,
            )

        request = Request(
            f"http://supervisor/core/api/states/{quote(binding.entity_id, safe='.')}",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return SourceEvidence(
                evidence_id=evidence_id,
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=binding.entity_id,
                raw_state=None,
                raw_unit=None,
                observed_at=None,
                availability="unavailable",
                mapping_version=mapping_version,
                error=type(exc).__name__,
            )

        raw_state = str(payload.get("state")) if payload.get("state") is not None else None
        attributes = payload.get("attributes")
        typed_attributes = attributes if isinstance(attributes, dict) else {}
        unit = typed_attributes.get("unit_of_measurement")
        unavailable = raw_state in {"unknown", "unavailable", None}
        price_points: tuple[PriceForecastPoint, ...] = ()
        pv_energy_intervals: tuple[PVEnergyTimelineInterval, ...] = ()
        if binding.category == "nordpool" and not unavailable:
            price_points = _price_points_from_attributes(
                typed_attributes,
                evidence_id=evidence_id,
            )
        if binding.category == "solcast" and not unavailable:
            pv_energy_intervals = _pv_forecast_intervals_from_attributes(
                typed_attributes,
                evidence_id=evidence_id,
            )
        return SourceEvidence(
            evidence_id=evidence_id,
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state=raw_state,
            raw_unit=str(unit) if unit is not None else None,
            observed_at=_parse_datetime(payload.get("last_updated")),
            availability="unavailable" if unavailable else "available",
            mapping_version=mapping_version,
            error=(
                "price_forecast_points_missing"
                if binding.category == "nordpool" and not unavailable and not price_points
                else None
            ),
            price_points=price_points,
            pv_energy_intervals=pv_energy_intervals,
        )


def assemble_planning_input(
    token: str,
    *,
    bindings: tuple[SourceBinding, ...] | None = None,
    storage_state_config: StorageStateConfig | None = None,
    options_path: str = "/data/options.json",
    captured_at: datetime | None = None,
    household_load_fallback_power_w: float | None = None,
    household_load_observations: tuple[
        HouseholdLoadObservation,
        ...,
    ] = (),
) -> PlanningInputBundle:
    started = datetime.now(UTC)
    reader = HomeAssistantStateReader(token)
    selected = bindings if bindings is not None else load_bindings(options_path)
    selected_storage_config = storage_state_config
    if bindings is None and selected_storage_config is None:
        selected_storage_config = load_storage_state_config(options_path)

    evidence = tuple(reader.read(binding) for binding in selected)
    finished = datetime.now(UTC)
    capture = captured_at or finished
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    household_load_observation = (
        _household_load_observation_from_evidence(
            evidence,
            sampled_at=capture,
        )
    )

    evidence_seed = "|".join(
        f"{item.mapping_version}:{item.raw_state}:{item.observed_at}" for item in evidence
    )
    run_id = _stable_id(
        "run", f"{__version__}|{capture.isoformat()}|{ARCHITECTURE_BASELINE_COMMIT}|{evidence_seed}"
    )
    snapshot_id = _stable_id("snapshot", run_id)

    facts = tuple(
        CanonicalInputFact(
            fact_id=_stable_id("fact", f"{snapshot_id}|{item.evidence_id}"),
            run_id=run_id,
            snapshot_id=snapshot_id,
            category=item.category,
            semantic_role=item.semantic_role,
            value=_canonical_value(item.raw_state) if item.availability == "available" else None,
            unit=item.raw_unit,
            observed_at=item.observed_at,
            availability=item.availability,
            evidence_id=item.evidence_id,
            mapping_version=item.mapping_version,
        )
        for item in evidence
    )
    price_points = tuple(
        point
        for item in evidence
        for point in item.price_points
        if point.ends_at > capture
    )
    price_horizon_end = max(
        (point.ends_at for point in price_points),
        default=None,
    )
    household_load_horizon_end = capture + timedelta(hours=36)
    household_load_forecast_requested = (
        household_load_fallback_power_w is not None
        or bool(household_load_observations)
    )
    horizon_end = (
        household_load_horizon_end
        if household_load_forecast_requested
        else price_horizon_end
    )
    current_storage_states = _current_storage_states_from_evidence(
        evidence,
        config=selected_storage_config,
    )
    pv_energy_intervals = tuple(
        interval
        for item in evidence
        for interval in item.pv_energy_intervals
    )
    pv_energy_timeline = (
        PVEnergyTimeline(
            timeline_id=_stable_id(
                "pv-energy-timeline",
                snapshot_id,
            ),
            run_id=run_id,
            snapshot_id=snapshot_id,
            intervals=tuple(
                sorted(
                    pv_energy_intervals,
                    key=lambda interval: interval.starts_at,
                )
            ),
        )
        if pv_energy_intervals
        else None
    )
    eligible_household_load_observations = tuple(
        observation
        for observation in household_load_observations
        if observation.sampled_at <= capture
    )
    household_load_forecast = (
        build_historical_household_load_forecast(
            run_id=run_id,
            snapshot_id=snapshot_id,
            starts_at=capture,
            horizon_end=household_load_horizon_end,
            observations=eligible_household_load_observations,
        )
        if eligible_household_load_observations
        else None
    )
    if (
        household_load_forecast is None
        and household_load_fallback_power_w is not None
    ):
        household_load_forecast = (
            build_fallback_household_load_forecast(
                run_id=run_id,
                snapshot_id=snapshot_id,
                starts_at=capture,
                horizon_end=household_load_horizon_end,
                fallback_power_w=household_load_fallback_power_w,
            )
        )

    snapshot = PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=snapshot_id,
        captured_at=capture,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
        horizon_end=horizon_end,
        price_points=price_points,
        current_storage_states=current_storage_states,
        pv_energy_timeline=pv_energy_timeline,
        household_load_forecast=household_load_forecast,
    )
    return PlanningInputBundle(
        snapshot,
        evidence,
        facts,
        started,
        finished,
        household_load_observation,
    )
