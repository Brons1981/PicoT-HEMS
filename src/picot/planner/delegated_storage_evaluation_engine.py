"""Canonical delegated-storage selection owned by the Evaluation layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from picot.v2.contracts import (
    Candidate,
    CandidateSet,
    DelegatedStorageCandidateOutcome,
    PlanningInputSnapshot,
)


@dataclass(frozen=True, slots=True)
class DelegatedStorageEvaluationResult:
    winning_outcome: DelegatedStorageCandidateOutcome | None
    incumbent_retained: bool
    decisive_step: str | None


class DelegatedStorageEvaluationEngine:
    """Select supplied outcomes without constructing or executing a plan."""

    def evaluate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate_set: CandidateSet,
        actionable_outcomes: tuple[DelegatedStorageCandidateOutcome, ...],
    ) -> DelegatedStorageEvaluationResult:
        if not actionable_outcomes:
            return DelegatedStorageEvaluationResult(None, False, None)

        incumbent_ids = self.incumbent_candidate_ids(
            snapshot=snapshot,
            candidate_set=candidate_set,
            candidate_ids=tuple(item.candidate_id for item in actionable_outcomes),
        )
        incumbent_outcomes = tuple(
            item
            for item in actionable_outcomes
            if item.candidate_id in incumbent_ids
        )
        material_shrink_ids = self._material_shrink_candidate_ids(
            snapshot,
            actionable_outcomes,
            incumbent_outcomes,
        )
        winner = min(
            actionable_outcomes,
            key=lambda item: (
                not item.requirement_satisfied,
                item.grid_storage_contribution_wh,
                (
                    item.candidate_id not in material_shrink_ids
                    if material_shrink_ids
                    else item.requirement_satisfied
                    and bool(incumbent_ids)
                    and item.candidate_id not in incumbent_ids
                ),
                self._average_price(snapshot, item),
                -item.confidence,
                (
                    self._distance_from_pv_energy_centre(snapshot, item)
                    if snapshot.household_planning_regime is not None
                    and snapshot.household_planning_regime.pv_timing_confident
                    else self._distance_from_local_midday(
                        snapshot,
                        item,
                    )
                ),
                -(
                    item.pv_storage_contribution_wh
                    + item.grid_storage_contribution_wh
                ),
                item.conversion_losses_wh,
                -item.recoverability,
                item.charge_window_starts_at,
                item.candidate_id,
            ),
        )
        retained = (
            winner.requirement_satisfied
            and winner.candidate_id in incumbent_ids
        )
        return DelegatedStorageEvaluationResult(
            winning_outcome=winner,
            incumbent_retained=retained,
            decisive_step=(
                (
                    "stability:scheduled_plan_commitment_retained"
                    if winner.charge_window_starts_at > snapshot.captured_at
                    else "stability:active_plan_commitment_retained"
                )
                if retained
                else (
                    "material_change:one_or_more_execution_intervals_removed"
                    if winner.candidate_id in material_shrink_ids
                    else None
                )
            ),
        )

    def _material_shrink_candidate_ids(
        self,
        snapshot: PlanningInputSnapshot,
        outcomes: tuple[DelegatedStorageCandidateOutcome, ...],
        incumbents: tuple[DelegatedStorageCandidateOutcome, ...],
    ) -> set[str]:
        """Return contained challengers that remove a full executable interval."""

        if len(incumbents) != 1:
            return set()
        incumbent = incumbents[0]
        if not incumbent.requirement_satisfied:
            return set()
        interval_seconds = min(
            (
                (item.ends_at - item.starts_at).total_seconds()
                for item in (
                    snapshot.pv_energy_timeline.intervals
                    if snapshot.pv_energy_timeline is not None
                    else ()
                )
                if item.ends_at > snapshot.captured_at
            ),
            default=0.0,
        )
        if interval_seconds <= 0.0:
            return set()
        incumbent_duration = (
            incumbent.charge_window_ends_at - incumbent.charge_window_starts_at
        ).total_seconds()
        incumbent_price = self._average_price(snapshot, incumbent)
        return {
            item.candidate_id
            for item in outcomes
            if item.candidate_id != incumbent.candidate_id
            and item.requirement_satisfied
            and item.charge_window_starts_at >= incumbent.charge_window_starts_at
            and item.charge_window_ends_at <= incumbent.charge_window_ends_at
            and incumbent_duration
            - (item.charge_window_ends_at - item.charge_window_starts_at).total_seconds()
            >= interval_seconds
            and self._average_price(snapshot, item) <= incumbent_price + 1e-12
        }

    def incumbent_candidate_ids(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        candidate_set: CandidateSet,
        candidate_ids: tuple[str, ...],
    ) -> set[str]:
        candidates_by_id = {
            item.candidate_id: item for item in candidate_set.candidates
        }
        paths_by_id = {item.path_id: item for item in candidate_set.energy_paths}
        return {
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id in candidates_by_id
            and self._matches_active_commitment(
                snapshot,
                candidates_by_id[candidate_id],
                paths_by_id[candidates_by_id[candidate_id].energy_path_id],
            )
        }

    @staticmethod
    def _matches_active_commitment(
        snapshot: PlanningInputSnapshot,
        candidate: Candidate,
        path: object,
    ) -> bool:
        segments = getattr(path, "segments", ())
        if not segments:
            return False
        for commitment in snapshot.active_plan_commitments:
            matching = tuple(
                segment
                for segment in segments
                if segment.execution_scope_id == commitment.execution_scope_id
                and segment.primitive.value == commitment.primitive
                and segment.charge_source_policy == commitment.source_policy
            )
            if (
                matching
                and min(item.starts_at for item in matching)
                == max(snapshot.captured_at, commitment.starts_at)
                and max(item.ends_at for item in matching) == commitment.ends_at
            ):
                return True
        return False

    @staticmethod
    def _average_price(
        snapshot: PlanningInputSnapshot,
        outcome: DelegatedStorageCandidateOutcome,
    ) -> float:
        weighted_price = 0.0
        total_seconds = 0.0
        for point in snapshot.price_points:
            overlap_start = max(point.starts_at, outcome.charge_window_starts_at)
            overlap_end = min(point.ends_at, outcome.charge_window_ends_at)
            seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
            weighted_price += point.value_eur_per_kwh * seconds
            total_seconds += seconds
        return weighted_price / total_seconds if total_seconds > 0.0 else float("inf")

    @staticmethod
    def _distance_from_pv_energy_centre(
        snapshot: PlanningInputSnapshot,
        outcome: DelegatedStorageCandidateOutcome,
    ) -> float:
        """Return seconds between a window midpoint and the forecast PV centre."""

        timeline = snapshot.pv_energy_timeline
        weighted_timestamp = 0.0
        total_energy_wh = 0.0
        for interval in (() if timeline is None else timeline.intervals):
            if interval.ends_at <= snapshot.captured_at:
                continue
            energy_wh = (
                interval.forecast_lower_energy_wh
                if interval.forecast_range_status == "available"
                and interval.forecast_lower_energy_wh is not None
                else interval.pv_energy_wh
            )
            if energy_wh <= 0.0:
                continue
            midpoint = interval.starts_at + (interval.ends_at - interval.starts_at) / 2
            weighted_timestamp += midpoint.timestamp() * energy_wh
            total_energy_wh += energy_wh
        if total_energy_wh <= 0.0:
            return 0.0
        pv_centre = weighted_timestamp / total_energy_wh
        window_midpoint = outcome.charge_window_starts_at + (
            outcome.charge_window_ends_at - outcome.charge_window_starts_at
        ) / 2
        return abs(window_midpoint.timestamp() - pv_centre)

    @staticmethod
    def _distance_from_local_midday(
        snapshot: PlanningInputSnapshot,
        outcome: DelegatedStorageCandidateOutcome,
    ) -> float:
        """Return distance to local noon when PV timing is not trustworthy.

        The Dutch market timezone is explicit throughout the v2 price and UI
        contracts.  A low-confidence forecast may establish feasibility, but
        its long low-energy tail must not move an otherwise equal-price window.
        """

        del snapshot
        market_timezone = ZoneInfo("Europe/Amsterdam")
        window_midpoint = outcome.charge_window_starts_at + (
            outcome.charge_window_ends_at - outcome.charge_window_starts_at
        ) / 2
        local_midpoint = window_midpoint.astimezone(market_timezone)
        local_midday = local_midpoint.replace(
            hour=time(12, 0).hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        return abs((local_midpoint - local_midday).total_seconds())
