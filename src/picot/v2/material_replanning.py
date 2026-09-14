"""Material observations for native daily and historical commitments."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import datetime
from hashlib import sha256

from picot.architecture_ownership import architecture_ownership
from picot.domain.runtime import RuntimeObservation, RuntimeObservationKind
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import CurrentStorageState, PlanningInputSnapshot
from picot.v2.daily_pv_comparison import DailyPVComparison, DailyPVComparisonState, compare_daily_pv
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
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

    def __init__(
        self, *, history: HouseholdLoadHistoryStore,
        conversion_model: Callable[[PlanningInputSnapshot], StorageConversionModel] | None = None,
    ) -> None:
        self._history = history
        self._conversion_model = conversion_model
        self._daily_context_identity: object = None
        self._daily_input_identities: dict[RuntimeObservationKind, object] = {}
        self._highest_emitted_bucket: dict[tuple[str, int, str], int] = {}

    def observe(
        self,
        bundle: PlanningInputBundle,
    ) -> tuple[RuntimeObservation, ...]:
        if bundle.snapshot.daily_charge_context is not None:
            return self._daily_observations(bundle)
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

    def _daily_observations(
        self, bundle: PlanningInputBundle,
    ) -> tuple[RuntimeObservation, ...]:
        """Observe native daily commitments using their accepted physical tests.

        No legacy trajectory buckets, candidate search, evaluation, plan write or
        dispatch occurs here. The planner repeats these tests on its fresh input.
        """
        snapshot = bundle.snapshot
        context = snapshot.daily_charge_context
        assert context is not None
        identity = (
            context.status, context.reason, context.active_main_plan_ids,
            tuple((a.assignment_id, a.route_plan_id, a.revision, a.completed_at)
                  for a in context.assignments),
            context.supplemental_assignments,
        )
        changed = identity != self._daily_context_identity
        self._daily_context_identity = identity

        def observation(reason: str, kind: RuntimeObservationKind,
                        evidence: tuple[str, ...] = ()) -> tuple[RuntimeObservation, ...]:
            return (RuntimeObservation(
                observation_id="daily-material:" + sha256(repr((
                    snapshot.snapshot_id, reason, identity, evidence,
                )).encode()).hexdigest(),
                kind=kind, observed_at=snapshot.captured_at,
                source_reference="daily-commitment-physical-assessment",
                old_value="retained_route", new_value=reason,
                evidence_ids=tuple(dict.fromkeys((
                    snapshot.snapshot_id, *context.active_main_plan_ids, *evidence,
                ))),
                material_transition=True,
            ),)

        capabilities = snapshot.capability_snapshot_set
        provenance = snapshot.storage_mode_control_provenance
        regime = snapshot.household_planning_regime
        inputs: dict[RuntimeObservationKind, object] = {
            RuntimeObservationKind.STRATEGY_CHANGED: (
                snapshot.strategy_id,
                (regime.regime, regime.objective_order, regime.method_version) if regime else None,
            ),
            RuntimeObservationKind.USER_RULES_CHANGED: (
                snapshot.user_objective_profile,
                snapshot.market_user_rule, snapshot.household_unexpected_reserve_fraction,
            ),
            RuntimeObservationKind.CAPABILITY_MAPPING_CHANGED: (
                capabilities.mapping_version if capabilities else None,
                tuple(tuple((f.name, getattr(c, f.name)) for f in fields(c)
                            if f.name != "fresh_at")
                      for c in capabilities.capabilities) if capabilities else (),
                tuple((e.category, e.semantic_role, e.entity_id, e.availability, e.mapping_version)
                      for e in bundle.evidence),
            ),
            RuntimeObservationKind.PRICE_CHANGED: tuple(
                (e.semantic_role, tuple((p.starts_at, p.ends_at, p.value_eur_per_kwh)
                                       for p in e.price_points))
                for e in bundle.evidence if e.price_points
            ),
            RuntimeObservationKind.COMMITMENT_CHANGED: (
                provenance.manual_override_active, provenance.reset_id,
            ) if provenance else None,
        }
        input_changes = tuple(kind for kind, value in inputs.items()
                              if kind in self._daily_input_identities
                              and value != self._daily_input_identities[kind])
        self._daily_input_identities = inputs
        if input_changes:
            return tuple(item for kind in input_changes
                         for item in observation(kind.value, kind))

        # Restored binding/completion changes must enter the monitor even if no
        # legacy ActivePlanCommitment exists. Repeated unchanged recovery is inert.
        if changed:
            return observation(
                "daily_commitment_changed", RuntimeObservationKind.COMMITMENT_CHANGED,
            )
        if context.status != "ready":
            return ()
        if any(a.route_plan_id is None and a.completed_at is None
               and a.ends_at > snapshot.captured_at for a in context.assignments):
            return observation(
                "daily_assignment_unbound", RuntimeObservationKind.COMMITMENT_CHANGED,
            )
        if not context.active_main_plan_ids:
            return ()
        if self._conversion_model is None:
            raise ValueError("daily material observation requires planner conversion model")
        try:
            conversion = self._conversion_model(snapshot)
            adapter = IndependentDailyReferenceAdapter()
            for trigger in adapter.main_route_shortfalls(
                snapshot=snapshot, conversion_model=conversion,
            ):
                if adapter.main_repair_required(
                    snapshot=snapshot, trigger=trigger, conversion_model=conversion,
                ):
                    return observation(
                        trigger.revision_reason.value, RuntimeObservationKind.STORAGE_STATE_CHANGED,
                        (trigger.assignment_id, trigger.route_plan_id),
                    )
            for state in context.pv_comparison_states:
                owner = next(a for a in context.assignments
                             if a.assignment_id == state.assignment_id)
                if state.basis is None or owner.completed_at is not None or (
                    owner.ends_at <= snapshot.captured_at
                ):
                    continue
                comparison = daily_grid_review_comparison(snapshot, state)
                if comparison.status != "complete" or (
                    comparison.evidence_id in state.assessed_evidence_ids
                ):
                    continue
                surplus = adapter.pv_surplus_trigger(
                    snapshot=snapshot, assignment=owner, comparison=comparison,
                    conversion_model=conversion,
                )
                if surplus is not None:
                    return observation(
                        surplus.revision_reason.value, RuntimeObservationKind.STORAGE_STATE_CHANGED,
                        (surplus.assignment_id, surplus.comparison_evidence_id),
                    )
            bridge = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion)
            if bridge.trigger is not None:
                return observation(
                    bridge.trigger.revision_reason.value,
                    RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
                    (bridge.trigger.assignment_id, bridge.trigger.route_plan_id),
                )
        except ValueError as exc:
            # An unavailable physical assessment is explicit evidence; the fresh
            # pipeline owns validation/fallback, never silently retain as healthy.
            return observation(
                "daily_assessment_unavailable:" + str(exc),
                RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
            )
        return ()

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


def daily_grid_review_comparison(
    snapshot: PlanningInputSnapshot, state: DailyPVComparisonState,
) -> DailyPVComparison:
    """Identical read-only grid-review evidence for monitoring and planning."""
    assert snapshot.daily_charge_context is not None
    assert state.basis is not None
    if snapshot.pv_energy_timeline is None:
        raise ValueError("daily_main_planning_data_unavailable")
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == state.assignment_id)
    comparison = compare_daily_pv(state.basis, snapshot.pv_energy_timeline,
                                  at=snapshot.captured_at)
    storage_basis = tuple(
        (s.execution_scope_id, s.current_soc, s.usable_capacity_wh)
        for s in snapshot.current_storage_states
        if s.execution_scope_id == owner.execution_scope_id
    )
    guard = snapshot.household_load_guard
    return replace(comparison, evidence_id="grid-review:" + sha256(repr((
        comparison.evidence_id, storage_basis,
        (guard.active, guard.quality, guard.extra_power_w) if guard is not None else None,
    )).encode()).hexdigest())
