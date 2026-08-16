"""Complete observer-only PV attenuation learning chain."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from hashlib import sha256
from pathlib import Path
from typing import Any

from picot.v2.contracts import (
    PVAttenuationObservation,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    PVForecastAttenuationProfile,
)
from picot.v2.pv_attenuation_aggregation import (
    PVAttenuationAggregationConfig,
)
from picot.v2.pv_attenuation_eligibility import (
    PVAttenuationEligibilityConfig,
    classify_pv_attenuation_observation,
)
from picot.v2.pv_attenuation_evidence import (
    PVAttenuationEvidenceStore,
    build_pv_attenuation_observation,
)
from picot.v2.pv_attenuation_history import (
    build_pv_attenuation_profile_from_history,
)
from picot.v2.pv_deviation import evaluate_pv_energy_deviation
from picot.v2.pv_solar_context_alignment import (
    SolarContextAlignmentResult,
    align_solar_context_to_deviation,
)
from picot.v2.pv_solar_history import SolarHistoryReadResult

ATTENUATION_LEARNING_METHOD_VERSION = "pv-attenuation-learning:v1"
FORECAST_BASIS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArchivedPVForecastBasis:
    basis_id: str
    installation_scope_id: str
    captured_at: datetime
    interval: PVEnergyTimelineInterval


@dataclass(frozen=True, slots=True)
class PVAttenuationLearningResult:
    status: str
    observer_only: bool
    cache_hit: bool
    closed_actual_interval_count: int
    archived_forecast_match_count: int
    solar_aligned_count: int
    persisted_observation_count: int
    rejection_reasons: dict[str, int]
    alignments: tuple[SolarContextAlignmentResult, ...]
    observations: tuple[PVAttenuationObservation, ...]
    profile: PVForecastAttenuationProfile
    solar_history_status: str
    solar_history_error: str | None
    method_version: str


SolarHistoryReader = Callable[..., SolarHistoryReadResult]


class _ForecastBasisStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def capture(
        self,
        *,
        installation_scope_id: str,
        timeline: PVEnergyTimeline,
        captured_at: datetime,
    ) -> int:
        existing = {
            (
                basis.installation_scope_id,
                basis.interval.starts_at,
                basis.interval.ends_at,
            )
            for basis in self.load()
        }
        added = 0
        for interval in timeline.intervals:
            key = (
                installation_scope_id,
                interval.starts_at,
                interval.ends_at,
            )
            if (
                interval.evidence_type != "FORECAST"
                or interval.forecast_range_status != "available"
                or captured_at >= interval.starts_at
                or key in existing
            ):
                continue
            basis = _forecast_basis(
                installation_scope_id=installation_scope_id,
                captured_at=captured_at,
                interval=interval,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        _forecast_basis_payload(basis),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
                handle.write("\n")
            existing.add(key)
            added += 1
        return added

    def load(self) -> tuple[ArchivedPVForecastBasis, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()
        bases: list[ArchivedPVForecastBasis] = []
        seen: set[str] = set()
        for line in lines:
            basis = _decode_forecast_basis(line)
            if basis is not None and basis.basis_id not in seen:
                bases.append(basis)
                seen.add(basis.basis_id)
        return tuple(
            sorted(
                bases,
                key=lambda basis: (
                    basis.interval.starts_at,
                    basis.interval.ends_at,
                    basis.basis_id,
                ),
            )
        )


class ObserverOnlyPVAttenuationLearningRuntime:
    """Persist and evaluate attenuation evidence without planning influence."""

    def __init__(
        self,
        *,
        forecast_basis_path: Path,
        evidence_store: PVAttenuationEvidenceStore,
        solar_history_reader: SolarHistoryReader,
        installation_scope_id: str,
        local_timezone: tzinfo,
        maximum_solar_age_seconds: float,
        forecast_mapping_version: str,
        eligibility_config: PVAttenuationEligibilityConfig,
        aggregation_config: PVAttenuationAggregationConfig,
    ) -> None:
        if not installation_scope_id.strip():
            raise ValueError("installation_scope_id must be explicit")
        if maximum_solar_age_seconds <= 0:
            raise ValueError(
                "maximum_solar_age_seconds must be positive"
            )
        if not forecast_mapping_version.strip():
            raise ValueError("forecast_mapping_version must be explicit")
        self._forecast_store = _ForecastBasisStore(
            forecast_basis_path
        )
        self._evidence_store = evidence_store
        self._solar_history_reader = solar_history_reader
        self._installation_scope_id = installation_scope_id
        self._local_timezone = local_timezone
        self._maximum_solar_age_seconds = maximum_solar_age_seconds
        self._forecast_mapping_version = forecast_mapping_version
        self._eligibility_config = eligibility_config
        self._aggregation_config = aggregation_config
        self._cache_key: tuple[tuple[object, ...], ...] | None = None
        self._cached_result: PVAttenuationLearningResult | None = None

    def capture_forecast_basis(
        self,
        *,
        timeline: PVEnergyTimeline,
        captured_at: datetime,
    ) -> int:
        _require_aware(captured_at, "captured_at")
        return self._forecast_store.capture(
            installation_scope_id=self._installation_scope_id,
            timeline=timeline,
            captured_at=captured_at,
        )

    def evaluate_closed_actuals(
        self,
        *,
        actual_intervals: tuple[PVEnergyTimelineInterval, ...],
        evaluated_at: datetime,
    ) -> PVAttenuationLearningResult:
        _require_aware(evaluated_at, "evaluated_at")
        closed_actuals = tuple(
            sorted(
                (
                    interval
                    for interval in actual_intervals
                    if (
                        interval.evidence_type == "ACTUAL"
                        and interval.ends_at <= evaluated_at
                    )
                ),
                key=lambda interval: (
                    interval.starts_at,
                    interval.ends_at,
                    interval.interval_id,
                ),
            )
        )
        cache_key = tuple(
            (
                interval.interval_id,
                interval.starts_at,
                interval.ends_at,
                interval.pv_energy_wh,
                interval.confidence,
                interval.actual_evidence_ids,
            )
            for interval in closed_actuals
        )
        if (
            cache_key == self._cache_key
            and self._cached_result is not None
        ):
            return replace(
                self._cached_result,
                cache_hit=True,
                persisted_observation_count=0,
            )

        basis_by_bounds = {
            (basis.interval.starts_at, basis.interval.ends_at): basis
            for basis in self._forecast_store.load()
            if basis.installation_scope_id
            == self._installation_scope_id
        }
        matched = tuple(
            (basis_by_bounds[(actual.starts_at, actual.ends_at)], actual)
            for actual in closed_actuals
            if (actual.starts_at, actual.ends_at) in basis_by_bounds
        )
        deviations = tuple(
            (
                basis,
                evaluate_pv_energy_deviation(
                    forecast=basis.interval,
                    actual=actual,
                    evaluated_at=evaluated_at,
                ),
            )
            for basis, actual in matched
        )

        if deviations:
            midpoints = tuple(
                deviation.starts_at
                + (deviation.ends_at - deviation.starts_at) / 2
                for _, deviation in deviations
            )
            history = self._solar_history_reader(
                starts_at=min(midpoints)
                - timedelta(
                    seconds=self._maximum_solar_age_seconds
                ),
                ends_at=max(midpoints),
                local_timezone=self._local_timezone,
            )
        else:
            history = SolarHistoryReadResult(
                source_entity_id="sun.sun",
                starts_at=evaluated_at,
                ends_at=evaluated_at,
                status="not_requested",
                error=None,
                observations=(),
                method_version="not_requested",
            )

        alignments = tuple(
            align_solar_context_to_deviation(
                deviation=deviation,
                observations=history.observations,
                local_timezone=self._local_timezone,
                maximum_age_seconds=(
                    self._maximum_solar_age_seconds
                ),
            )
            for _, deviation in deviations
        )
        unassessed = tuple(
            build_pv_attenuation_observation(
                deviation=deviation,
                installation_scope_id=self._installation_scope_id,
                forecast_captured_at=basis.captured_at,
                solar_azimuth_degrees=alignment.solar_azimuth_degrees,
                solar_elevation_degrees=(
                    alignment.solar_elevation_degrees
                ),
                sunset_at=alignment.sunset_at,
                forecast_mapping_version=(
                    self._forecast_mapping_version
                ),
                alignment_status="aligned",
                coverage_status="complete",
                solar_evidence_id=(
                    alignment.solar_observation_evidence_id
                ),
                solar_observed_at=(
                    alignment.solar_observation_sampled_at
                ),
                solar_alignment_method_version=(
                    alignment.method_version
                ),
            )
            for (basis, deviation), alignment in zip(
                deviations,
                alignments,
                strict=True,
            )
            if (
                alignment.status == "aligned"
                and alignment.solar_azimuth_degrees is not None
                and alignment.solar_elevation_degrees is not None
                and alignment.sunset_at is not None
                and alignment.solar_observation_evidence_id is not None
                and alignment.solar_observation_sampled_at is not None
            )
        )
        existing = self._evidence_store.load()
        classification_context = (*existing, *unassessed)
        classified = tuple(
            classify_pv_attenuation_observation(
                target_observation_id=observation.observation_id,
                observations=classification_context,
                evaluated_at=evaluated_at,
                config=self._eligibility_config,
            )
            for observation in unassessed
        )
        persisted_count = sum(
            self._evidence_store.append(observation)
            for observation in classified
        )
        profile = build_pv_attenuation_profile_from_history(
            store=self._evidence_store,
            installation_scope_id=self._installation_scope_id,
            evaluated_at=evaluated_at,
            eligibility_config=self._eligibility_config,
            aggregation_config=self._aggregation_config,
        )
        rejection_reasons = dict(
            Counter(
                observation.eligibility_reason
                for observation in classified
                if observation.eligibility_reason is not None
            )
        )
        if profile.status == "available":
            status = "profile_available"
        elif classified:
            status = "insufficient_evidence"
        elif deviations:
            status = "solar_context_unavailable"
        else:
            status = "no_archived_forecast_matches"

        result = PVAttenuationLearningResult(
            status=status,
            observer_only=True,
            cache_hit=False,
            closed_actual_interval_count=len(closed_actuals),
            archived_forecast_match_count=len(matched),
            solar_aligned_count=sum(
                alignment.status == "aligned"
                for alignment in alignments
            ),
            persisted_observation_count=persisted_count,
            rejection_reasons=rejection_reasons,
            alignments=alignments,
            observations=classified,
            profile=profile,
            solar_history_status=history.status,
            solar_history_error=history.error,
            method_version=ATTENUATION_LEARNING_METHOD_VERSION,
        )
        self._cache_key = cache_key
        self._cached_result = result
        return result


def project_pv_attenuation_learning_result(
    result: PVAttenuationLearningResult,
) -> dict[str, object]:
    """Expose learning state without changing planning input."""
    return {
        "pv_attenuation_learning_status": result.status,
        "pv_attenuation_learning_observer_only": True,
        "pv_attenuation_learning_cache_hit": result.cache_hit,
        "pv_attenuation_learning_closed_actual_interval_count": (
            result.closed_actual_interval_count
        ),
        "pv_attenuation_learning_archived_forecast_match_count": (
            result.archived_forecast_match_count
        ),
        "pv_attenuation_learning_solar_aligned_count": (
            result.solar_aligned_count
        ),
        "pv_attenuation_learning_persisted_observation_count": (
            result.persisted_observation_count
        ),
        "pv_attenuation_learning_rejection_reasons": dict(
            result.rejection_reasons
        ),
        "pv_attenuation_learning_profile_status": result.profile.status,
        "pv_attenuation_learning_profile_id": result.profile.profile_id,
        "pv_attenuation_learning_solar_history_status": (
            result.solar_history_status
        ),
        "pv_attenuation_learning_solar_history_error": (
            result.solar_history_error
        ),
        "pv_attenuation_learning_method_version": result.method_version,
    }


def _forecast_basis(
    *,
    installation_scope_id: str,
    captured_at: datetime,
    interval: PVEnergyTimelineInterval,
) -> ArchivedPVForecastBasis:
    seed = "|".join(
        (
            installation_scope_id,
            captured_at.isoformat(),
            interval.interval_id,
            interval.starts_at.isoformat(),
            interval.ends_at.isoformat(),
            str(interval.pv_energy_wh),
            *interval.forecast_evidence_ids,
            FORECAST_BASIS_SCHEMA_VERSION.__str__(),
        )
    )
    return ArchivedPVForecastBasis(
        basis_id=(
            "pv-forecast-basis-"
            f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
        ),
        installation_scope_id=installation_scope_id,
        captured_at=captured_at,
        interval=interval,
    )


def _forecast_basis_payload(
    basis: ArchivedPVForecastBasis,
) -> dict[str, object]:
    interval = basis.interval
    return {
        "schema_version": FORECAST_BASIS_SCHEMA_VERSION,
        "basis_id": basis.basis_id,
        "installation_scope_id": basis.installation_scope_id,
        "captured_at": basis.captured_at.isoformat(),
        "interval_id": interval.interval_id,
        "starts_at": interval.starts_at.isoformat(),
        "ends_at": interval.ends_at.isoformat(),
        "pv_energy_wh": interval.pv_energy_wh,
        "confidence": interval.confidence,
        "forecast_evidence_ids": list(
            interval.forecast_evidence_ids
        ),
        "conversion_method_version": interval.conversion_method_version,
        "forecast_lower_energy_wh": interval.forecast_lower_energy_wh,
        "forecast_central_energy_wh": interval.forecast_central_energy_wh,
        "forecast_upper_energy_wh": interval.forecast_upper_energy_wh,
        "forecast_range_source_fields": list(
            interval.forecast_range_source_fields
        ),
        "forecast_range_method_version": (
            interval.forecast_range_method_version
        ),
    }


def _decode_forecast_basis(
    line: str,
) -> ArchivedPVForecastBasis | None:
    try:
        raw: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version")
        != FORECAST_BASIS_SCHEMA_VERSION
    ):
        return None
    payload: dict[str, Any] = raw
    try:
        interval = PVEnergyTimelineInterval(
            interval_id=_string(payload["interval_id"]),
            starts_at=_datetime(payload["starts_at"]),
            ends_at=_datetime(payload["ends_at"]),
            pv_energy_wh=_number(payload["pv_energy_wh"]),
            evidence_type="FORECAST",
            confidence=_number(payload["confidence"]),
            actual_evidence_ids=(),
            forecast_evidence_ids=_string_tuple(
                payload["forecast_evidence_ids"]
            ),
            conversion_method_version=_optional_string(
                payload["conversion_method_version"]
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
            forecast_range_status="available",
            forecast_range_source_fields=_string_tuple(
                payload["forecast_range_source_fields"]
            ),
            forecast_range_method_version=_string(
                payload["forecast_range_method_version"]
            ),
        )
        return ArchivedPVForecastBasis(
            basis_id=_string(payload["basis_id"]),
            installation_scope_id=_string(
                payload["installation_scope_id"]
            ),
            captured_at=_datetime(payload["captured_at"]),
            interval=interval,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


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


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError
    return tuple(_string(item) for item in value)
