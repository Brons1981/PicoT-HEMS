"""Committed-plan materiality producers defined by V2ADR-063."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.architecture_ownership import architecture_ownership
from picot.domain.runtime import RuntimeObservation, RuntimeObservationKind
from picot.v2.contracts import CurrentStorageState
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    CommittedHouseholdLoadInterval,
)
from picot.v2.planning_input import HouseholdLoadObservation, PlanningInputBundle

ARCHITECTURE_OWNERSHIP = architecture_ownership("materiality_producer", __name__)

METHOD_VERSION = "committed-trajectory-materiality:v1"
MINIMUM_ABSOLUTE_DEVIATION_WH = 250.0
STORAGE_CAPACITY_DEVIATION_FRACTION = 0.05
HOUSEHOLD_EXPECTED_DEVIATION_FRACTION = 0.25
MINIMUM_HOUSEHOLD_INTERVALS = 2
MINIMUM_SAMPLE_SPAN_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class _HouseholdEnergyEvidence:
    expected_energy_wh: float
    actual_energy_wh: float
    interval_ids: tuple[str, ...]
    actual_evidence_ids: tuple[str, ...]


class MaterialReplanningObservationProducer:
    """Mark accepted plan-relative thresholds without starting planning."""

    def __init__(self, *, history: HouseholdLoadHistoryStore) -> None:
        self._history = history
        self._highest_emitted_bucket: dict[tuple[str, int, str], int] = {}

    def observe(
        self,
        bundle: PlanningInputBundle,
    ) -> tuple[RuntimeObservation, ...]:
        observations: list[RuntimeObservation] = []
        active_keys = {
            (item.plan_id, item.plan_revision)
            for item in bundle.snapshot.active_plan_commitments
        }
        self._highest_emitted_bucket = {
            key: bucket
            for key, bucket in self._highest_emitted_bucket.items()
            if (key[0], key[1]) in active_keys
        }
        history = self._history.load()

        for commitment in bundle.snapshot.active_plan_commitments:
            storage = next(
                (
                    item
                    for item in bundle.snapshot.current_storage_states
                    if item.execution_scope_id == commitment.execution_scope_id
                ),
                None,
            )
            if storage is None:
                continue
            storage_observation = self._storage_observation(
                commitment=commitment,
                storage=storage,
                bundle=bundle,
            )
            if storage_observation is not None:
                observations.append(storage_observation)
            household_observation = self._household_observation(
                commitment=commitment,
                storage=storage,
                history=history,
                bundle=bundle,
            )
            if household_observation is not None:
                observations.append(household_observation)

        return tuple(observations)

    def _storage_observation(
        self,
        *,
        commitment: ActivePlanCommitment,
        storage: CurrentStorageState,
        bundle: PlanningInputBundle,
    ) -> RuntimeObservation | None:
        checkpoint = next(
            (
                item
                for item in reversed(commitment.storage_energy_checkpoints)
                if item.at <= bundle.snapshot.captured_at
            ),
            None,
        )
        if checkpoint is None:
            return None
        actual = storage.current_stored_energy_wh
        deviation = (
            actual - checkpoint.lower_energy_wh
            if actual < checkpoint.lower_energy_wh
            else actual - checkpoint.upper_energy_wh
            if actual > checkpoint.upper_energy_wh
            else 0.0
        )
        threshold = self._storage_threshold(storage.usable_capacity_wh)
        bucket = self._material_bucket(deviation, threshold)
        if bucket is None or not self._claim_bucket(
            commitment,
            evidence_kind="storage",
            bucket=bucket,
        ):
            return None
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *storage.evidence_ids,
                    commitment.schedule_id or commitment.plan_id,
                )
            )
        )
        return RuntimeObservation(
            observation_id=(
                f"committed-storage:{commitment.plan_id}:"
                f"r{commitment.plan_revision}:bucket-{bucket}"
            ),
            kind=RuntimeObservationKind.STORAGE_STATE_CHANGED,
            observed_at=bundle.snapshot.captured_at,
            source_reference="committed-storage-trajectory",
            old_value=(
                f"corridor:{checkpoint.lower_energy_wh:.6f}.."
                f"{checkpoint.upper_energy_wh:.6f}"
            ),
            new_value=f"actual:{actual:.6f}",
            unit="Wh",
            execution_scope_id=commitment.execution_scope_id,
            source_version=commitment.plan_revision,
            evidence_ids=evidence_ids,
            material_transition=True,
        )

    def _household_observation(
        self,
        *,
        commitment: ActivePlanCommitment,
        storage: CurrentStorageState,
        history: tuple[HouseholdLoadObservation, ...],
        bundle: PlanningInputBundle,
    ) -> RuntimeObservation | None:
        evidence = self._household_energy_evidence(
            commitment.household_load_intervals,
            history,
            captured_at=bundle.snapshot.captured_at,
        )
        if evidence is None:
            return None
        deviation = evidence.actual_energy_wh - evidence.expected_energy_wh
        threshold = max(
            self._storage_threshold(storage.usable_capacity_wh),
            evidence.expected_energy_wh
            * HOUSEHOLD_EXPECTED_DEVIATION_FRACTION,
        )
        bucket = self._material_bucket(deviation, threshold)
        if bucket is None or not self._claim_bucket(
            commitment,
            evidence_kind="household",
            bucket=bucket,
        ):
            return None
        return RuntimeObservation(
            observation_id=(
                f"committed-household:{commitment.plan_id}:"
                f"r{commitment.plan_revision}:bucket-{bucket}"
            ),
            kind=RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
            observed_at=bundle.snapshot.captured_at,
            source_reference="committed-household-load",
            old_value=f"expected:{evidence.expected_energy_wh:.6f}",
            new_value=f"actual:{evidence.actual_energy_wh:.6f}",
            unit="Wh",
            execution_scope_id=commitment.execution_scope_id,
            source_version=commitment.plan_revision,
            evidence_ids=tuple(
                dict.fromkeys(
                    (*evidence.interval_ids, *evidence.actual_evidence_ids)
                )
            ),
            material_transition=True,
        )

    @staticmethod
    def _household_energy_evidence(
        intervals: tuple[CommittedHouseholdLoadInterval, ...],
        history: tuple[HouseholdLoadObservation, ...],
        *,
        captured_at: datetime,
    ) -> _HouseholdEnergyEvidence | None:
        closed = tuple(
            interval for interval in intervals if interval.ends_at <= captured_at
        )
        if len(closed) < MINIMUM_HOUSEHOLD_INTERVALS:
            return None
        expected = 0.0
        actual = 0.0
        interval_ids: list[str] = []
        actual_evidence_ids: list[str] = []
        covered = 0
        previous_ends_at: datetime | None = None
        for interval in closed:
            if previous_ends_at is not None and interval.starts_at != previous_ends_at:
                break
            samples = tuple(
                sorted(
                    (
                        item
                        for item in history
                        if interval.starts_at <= item.sampled_at < interval.ends_at
                    ),
                    key=lambda item: item.sampled_at,
                )
            )
            if len(samples) < 2:
                break
            duration = interval.ends_at - interval.starts_at
            if samples[-1].sampled_at - samples[0].sampled_at < (
                duration * MINIMUM_SAMPLE_SPAN_FRACTION
            ):
                break
            mean_power_w = sum(item.power_w for item in samples) / len(samples)
            expected += interval.expected_energy_wh
            actual += mean_power_w * duration.total_seconds() / 3600.0
            interval_ids.append(interval.interval_id)
            actual_evidence_ids.extend(samples[0].evidence_ids)
            actual_evidence_ids.extend(samples[-1].evidence_ids)
            covered += 1
            previous_ends_at = interval.ends_at
        if covered < MINIMUM_HOUSEHOLD_INTERVALS:
            return None
        return _HouseholdEnergyEvidence(
            expected_energy_wh=expected,
            actual_energy_wh=actual,
            interval_ids=tuple(interval_ids),
            actual_evidence_ids=tuple(dict.fromkeys(actual_evidence_ids)),
        )

    @staticmethod
    def _storage_threshold(usable_capacity_wh: float) -> float:
        return max(
            MINIMUM_ABSOLUTE_DEVIATION_WH,
            usable_capacity_wh * STORAGE_CAPACITY_DEVIATION_FRACTION,
        )

    @staticmethod
    def _material_bucket(deviation_wh: float, threshold_wh: float) -> int | None:
        if abs(deviation_wh) + 1e-6 < threshold_wh:
            return None
        return max(1, int(abs(deviation_wh) // threshold_wh))

    def _claim_bucket(
        self,
        commitment: ActivePlanCommitment,
        *,
        evidence_kind: str,
        bucket: int,
    ) -> bool:
        key = (
            commitment.plan_id,
            commitment.plan_revision,
            evidence_kind,
        )
        if bucket <= self._highest_emitted_bucket.get(key, 0):
            return False
        self._highest_emitted_bucket[key] = bucket
        return True
