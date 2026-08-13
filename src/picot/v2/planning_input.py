"""Authoritative Home Assistant ingestion for PicoT v2 Planning Input.

HA entity ids exist only in source evidence. Canonical facts and forecasts are
created once at the ingestion boundary and then carried by one immutable snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint


@dataclass(frozen=True, slots=True)
class SourceBinding:
    category: str
    semantic_role: str
    entity_id: str | None


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
class PlanningInputBundle:
    snapshot: PlanningInputSnapshot
    evidence: tuple[SourceEvidence, ...]
    facts: tuple[CanonicalInputFact, ...]
    assembly_started_at: datetime
    assembly_finished_at: datetime


DEFAULT_BINDINGS = (
    ("p1", "grid_power", "p1_power_entity"),
    ("pv", "pv_power", "pv_power_entity"),
    ("zendure", "storage_soc", "zendure_soc_entity"),
    ("solcast", "pv_forecast", "solcast_forecast_entity"),
    ("nordpool", "energy_price", "nordpool_price_entity"),
)


def _stable_id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


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
        price_points = ()
        if binding.category == "nordpool" and not unavailable:
            price_points = _price_points_from_attributes(
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
        )


def assemble_planning_input(
    token: str,
    *,
    bindings: tuple[SourceBinding, ...] | None = None,
    captured_at: datetime | None = None,
) -> PlanningInputBundle:
    started = datetime.now(UTC)
    reader = HomeAssistantStateReader(token)
    selected = bindings if bindings is not None else load_bindings()
    evidence = tuple(reader.read(binding) for binding in selected)
    finished = datetime.now(UTC)
    capture = captured_at or finished
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

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
    horizon_end = max((point.ends_at for point in price_points), default=None)

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
    )
    return PlanningInputBundle(snapshot, evidence, facts, started, finished)
