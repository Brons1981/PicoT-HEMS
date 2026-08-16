"""Observer-only evidence capture for V2ADR-049 PV attenuation."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from picot.v2.contracts import PVAttenuationObservation
from picot.v2.pv_deviation import PVDeviationResult

ATTENUATION_EVIDENCE_METHOD_VERSION = "pv-attenuation-evidence-capture:v1"
ATTENUATION_EVIDENCE_SCHEMA_VERSION = 2


def build_pv_attenuation_observation(
    *,
    deviation: PVDeviationResult,
    installation_scope_id: str,
    forecast_captured_at: datetime,
    solar_azimuth_degrees: float,
    solar_elevation_degrees: float,
    sunset_at: datetime,
    forecast_mapping_version: str,
    alignment_status: str,
    coverage_status: str,
    solar_evidence_id: str = "solar-evidence-unavailable",
    solar_observed_at: datetime | None = None,
    solar_alignment_method_version: str = (
        "solar-alignment-unavailable"
    ),
) -> PVAttenuationObservation:
    """Preserve one aligned closed interval without classifying attenuation."""
    if (
        forecast_captured_at.tzinfo is None
        or forecast_captured_at.utcoffset() is None
    ):
        raise ValueError("forecast_captured_at must be timezone-aware")
    if sunset_at.tzinfo is None or sunset_at.utcoffset() is None:
        raise ValueError("sunset_at must be timezone-aware")
    if (
        deviation.forecast_range_status != "available"
        or deviation.forecast_lower_energy_wh is None
        or deviation.forecast_central_energy_wh is None
        or deviation.forecast_upper_energy_wh is None
    ):
        raise ValueError("available original forecast range is required")
    if not installation_scope_id.strip():
        raise ValueError("installation_scope_id must be explicit")
    if not forecast_mapping_version.strip():
        raise ValueError("forecast_mapping_version must be explicit")
    if deviation.forecast_conversion_method_version is None:
        raise ValueError("forecast conversion method must be explicit")
    if deviation.actual_conversion_method_version is None:
        raise ValueError("actual conversion method must be explicit")

    midpoint = deviation.starts_at + (
        deviation.ends_at - deviation.starts_at
    ) / 2
    minutes_from_sunset = (
        midpoint - sunset_at
    ).total_seconds() / 60.0
    seed = "|".join(
        (
            installation_scope_id,
            deviation.starts_at.isoformat(),
            deviation.ends_at.isoformat(),
            forecast_captured_at.isoformat(),
            str(deviation.forecast_lower_energy_wh),
            str(deviation.forecast_central_energy_wh),
            str(deviation.forecast_upper_energy_wh),
            str(deviation.forecast_confidence),
            str(deviation.actual_energy_wh),
            str(deviation.actual_confidence),
            str(solar_azimuth_degrees),
            str(solar_elevation_degrees),
            str(minutes_from_sunset),
            solar_evidence_id,
            (
                solar_observed_at.isoformat()
                if solar_observed_at is not None
                else "unavailable"
            ),
            sunset_at.isoformat(),
            solar_alignment_method_version,
            alignment_status,
            coverage_status,
            forecast_mapping_version,
            deviation.forecast_conversion_method_version,
            deviation.actual_conversion_method_version,
            *deviation.forecast_evidence_ids,
            *deviation.actual_evidence_ids,
            ATTENUATION_EVIDENCE_METHOD_VERSION,
        )
    )
    observation_id = (
        "pv-attenuation-observation-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )
    return PVAttenuationObservation(
        observation_id=observation_id,
        installation_scope_id=installation_scope_id,
        starts_at=deviation.starts_at,
        ends_at=deviation.ends_at,
        forecast_captured_at=forecast_captured_at,
        forecast_lower_energy_wh=deviation.forecast_lower_energy_wh,
        forecast_central_energy_wh=deviation.forecast_central_energy_wh,
        forecast_upper_energy_wh=deviation.forecast_upper_energy_wh,
        forecast_confidence=deviation.forecast_confidence,
        actual_energy_wh=deviation.actual_energy_wh,
        actual_confidence=deviation.actual_confidence,
        solar_azimuth_degrees=solar_azimuth_degrees,
        solar_elevation_degrees=solar_elevation_degrees,
        minutes_from_sunset=minutes_from_sunset,
        forecast_evidence_ids=deviation.forecast_evidence_ids,
        actual_evidence_ids=deviation.actual_evidence_ids,
        forecast_mapping_version=forecast_mapping_version,
        forecast_conversion_method_version=(
            deviation.forecast_conversion_method_version
        ),
        actual_conversion_method_version=(
            deviation.actual_conversion_method_version
        ),
        eligibility_status="unassessed",
        eligibility_reason="eligibility_not_assessed",
        eligibility_method_version="not_applied",
        alignment_status=alignment_status,
        coverage_status=coverage_status,
        observation_method_version=ATTENUATION_EVIDENCE_METHOD_VERSION,
        solar_evidence_id=solar_evidence_id,
        solar_observed_at=solar_observed_at,
        sunset_at=sunset_at,
        solar_alignment_method_version=(
            solar_alignment_method_version
        ),
    )


class PVAttenuationEvidenceStore:
    """Append-only JSONL storage for reconstructable observations."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, observation: PVAttenuationObservation) -> bool:
        if any(
            item.observation_id == observation.observation_id
            for item in self.load()
        ):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    _observation_payload(observation),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            handle.write("\n")
        return True

    def load(self) -> tuple[PVAttenuationObservation, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()
        observations: list[PVAttenuationObservation] = []
        seen: set[str] = set()
        for line in lines:
            observation = _decode_observation(line)
            if (
                observation is not None
                and observation.observation_id not in seen
            ):
                observations.append(observation)
                seen.add(observation.observation_id)
        return tuple(observations)


def project_pv_attenuation_observation(
    observation: PVAttenuationObservation,
) -> dict[str, object]:
    """Expose retained facts directly; do not recalculate evidence."""
    return {
        "pv_attenuation_observation_status": (
            observation.eligibility_status
        ),
        "pv_attenuation_observer_only": True,
        "pv_attenuation_observation_id": observation.observation_id,
        "pv_attenuation_installation_scope_id": (
            observation.installation_scope_id
        ),
        "pv_attenuation_starts_at": observation.starts_at.isoformat(),
        "pv_attenuation_ends_at": observation.ends_at.isoformat(),
        "pv_attenuation_forecast_captured_at": (
            observation.forecast_captured_at.isoformat()
        ),
        "pv_attenuation_forecast_lower_energy_wh": (
            observation.forecast_lower_energy_wh
        ),
        "pv_attenuation_forecast_central_energy_wh": (
            observation.forecast_central_energy_wh
        ),
        "pv_attenuation_forecast_upper_energy_wh": (
            observation.forecast_upper_energy_wh
        ),
        "pv_attenuation_forecast_confidence": (
            observation.forecast_confidence
        ),
        "pv_attenuation_actual_energy_wh": observation.actual_energy_wh,
        "pv_attenuation_actual_confidence": observation.actual_confidence,
        "pv_attenuation_solar_azimuth_degrees": (
            observation.solar_azimuth_degrees
        ),
        "pv_attenuation_solar_elevation_degrees": (
            observation.solar_elevation_degrees
        ),
        "pv_attenuation_minutes_from_sunset": (
            observation.minutes_from_sunset
        ),
        "pv_attenuation_alignment_status": observation.alignment_status,
        "pv_attenuation_coverage_status": observation.coverage_status,
        "pv_attenuation_eligibility_reason": (
            observation.eligibility_reason
        ),
        "pv_attenuation_forecast_evidence_ids": list(
            observation.forecast_evidence_ids
        ),
        "pv_attenuation_actual_evidence_ids": list(
            observation.actual_evidence_ids
        ),
        "pv_attenuation_forecast_mapping_version": (
            observation.forecast_mapping_version
        ),
        "pv_attenuation_forecast_conversion_method_version": (
            observation.forecast_conversion_method_version
        ),
        "pv_attenuation_actual_conversion_method_version": (
            observation.actual_conversion_method_version
        ),
        "pv_attenuation_observation_method_version": (
            observation.observation_method_version
        ),
        "pv_attenuation_eligibility_method_version": (
            observation.eligibility_method_version
        ),
    }


def _observation_payload(
    observation: PVAttenuationObservation,
) -> dict[str, object]:
    return {
        "schema_version": ATTENUATION_EVIDENCE_SCHEMA_VERSION,
        "observation_id": observation.observation_id,
        "installation_scope_id": observation.installation_scope_id,
        "starts_at": observation.starts_at.isoformat(),
        "ends_at": observation.ends_at.isoformat(),
        "forecast_captured_at": observation.forecast_captured_at.isoformat(),
        "forecast_lower_energy_wh": observation.forecast_lower_energy_wh,
        "forecast_central_energy_wh": observation.forecast_central_energy_wh,
        "forecast_upper_energy_wh": observation.forecast_upper_energy_wh,
        "forecast_confidence": observation.forecast_confidence,
        "actual_energy_wh": observation.actual_energy_wh,
        "actual_confidence": observation.actual_confidence,
        "solar_azimuth_degrees": observation.solar_azimuth_degrees,
        "solar_elevation_degrees": observation.solar_elevation_degrees,
        "minutes_from_sunset": observation.minutes_from_sunset,
        "solar_evidence_id": observation.solar_evidence_id,
        "solar_observed_at": (
            observation.solar_observed_at.isoformat()
            if observation.solar_observed_at is not None
            else None
        ),
        "sunset_at": (
            observation.sunset_at.isoformat()
            if observation.sunset_at is not None
            else None
        ),
        "solar_alignment_method_version": (
            observation.solar_alignment_method_version
        ),
        "forecast_evidence_ids": list(observation.forecast_evidence_ids),
        "actual_evidence_ids": list(observation.actual_evidence_ids),
        "forecast_mapping_version": observation.forecast_mapping_version,
        "forecast_conversion_method_version": (
            observation.forecast_conversion_method_version
        ),
        "actual_conversion_method_version": (
            observation.actual_conversion_method_version
        ),
        "eligibility_status": observation.eligibility_status,
        "eligibility_reason": observation.eligibility_reason,
        "eligibility_method_version": (
            observation.eligibility_method_version
        ),
        "alignment_status": observation.alignment_status,
        "coverage_status": observation.coverage_status,
        "observation_method_version": (
            observation.observation_method_version
        ),
    }


def _decode_observation(line: str) -> PVAttenuationObservation | None:
    try:
        raw: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    schema_version = raw.get("schema_version")
    if schema_version not in (1, ATTENUATION_EVIDENCE_SCHEMA_VERSION):
        return None
    payload: dict[str, Any] = raw
    try:
        forecast_ids = _string_tuple(payload["forecast_evidence_ids"])
        actual_ids = _string_tuple(payload["actual_evidence_ids"])
        return PVAttenuationObservation(
            observation_id=_string(payload["observation_id"]),
            installation_scope_id=_string(
                payload["installation_scope_id"]
            ),
            starts_at=_datetime(payload["starts_at"]),
            ends_at=_datetime(payload["ends_at"]),
            forecast_captured_at=_datetime(
                payload["forecast_captured_at"]
            ),
            forecast_lower_energy_wh=_number(
                payload["forecast_lower_energy_wh"]
            ),
            forecast_central_energy_wh=_number(
                payload["forecast_central_energy_wh"]
            ),
            forecast_upper_energy_wh=_number(
                payload["forecast_upper_energy_wh"]
            ),
            forecast_confidence=_number(
                payload["forecast_confidence"]
            ),
            actual_energy_wh=_number(payload["actual_energy_wh"]),
            actual_confidence=_number(payload["actual_confidence"]),
            solar_azimuth_degrees=_number(
                payload["solar_azimuth_degrees"]
            ),
            solar_elevation_degrees=_number(
                payload["solar_elevation_degrees"]
            ),
            minutes_from_sunset=_number(
                payload["minutes_from_sunset"]
            ),
            forecast_evidence_ids=forecast_ids,
            actual_evidence_ids=actual_ids,
            forecast_mapping_version=_string(
                payload["forecast_mapping_version"]
            ),
            forecast_conversion_method_version=_string(
                payload["forecast_conversion_method_version"]
            ),
            actual_conversion_method_version=_string(
                payload["actual_conversion_method_version"]
            ),
            eligibility_status=_string(
                payload["eligibility_status"]
            ),
            eligibility_reason=_optional_string(
                payload["eligibility_reason"]
            ),
            eligibility_method_version=_string(
                payload["eligibility_method_version"]
            ),
            alignment_status=_string(payload["alignment_status"]),
            coverage_status=_string(payload["coverage_status"]),
            observation_method_version=_string(
                payload["observation_method_version"]
            ),
            solar_evidence_id=(
                _string(payload["solar_evidence_id"])
                if schema_version == ATTENUATION_EVIDENCE_SCHEMA_VERSION
                else "solar-evidence-unavailable"
            ),
            solar_observed_at=(
                _optional_datetime(payload["solar_observed_at"])
                if schema_version == ATTENUATION_EVIDENCE_SCHEMA_VERSION
                else None
            ),
            sunset_at=(
                _optional_datetime(payload["sunset_at"])
                if schema_version == ATTENUATION_EVIDENCE_SCHEMA_VERSION
                else None
            ),
            solar_alignment_method_version=(
                _string(payload["solar_alignment_method_version"])
                if schema_version == ATTENUATION_EVIDENCE_SCHEMA_VERSION
                else "solar-alignment-unavailable"
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TypeError


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError
    return float(value)


def _datetime(value: object) -> datetime:
    return datetime.fromisoformat(_string(value).replace("Z", "+00:00"))


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError
    return tuple(_string(item) for item in value)
