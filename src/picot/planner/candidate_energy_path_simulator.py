"""Deterministic ADR-017/ADR-030 Candidate Energy Path simulation.

Simulation projects household import/export and storage state from canonical
planning inputs plus explicit candidate Path Segments. It does not rank
Candidates and does not invent vendor behaviour or economic values.
"""

from __future__ import annotations

from dataclasses import replace

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.energy_path import EnergyPath, PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.planning_input_snapshot import PlanningInputSnapshot


class CandidateEnergyPathSimulator:
    """Project one immutable Candidate Energy Path on the canonical interval grid."""

    def simulate(
        self,
        *,
        path: EnergyPath,
        snapshot: PlanningInputSnapshot,
        storage_state: CurrentStorageState,
    ) -> EnergyPath:
        if path.snapshot_id != snapshot.snapshot_id:
            raise ValueError("Energy Path must match the Planning Input Snapshot.")
        pv_timeline = snapshot.pv_energy_timeline
        load_forecast = snapshot.household_load_forecast
        if pv_timeline is None or load_forecast is None:
            raise ValueError("Candidate simulation requires canonical PV and household load inputs.")
        if storage_state.execution_scope_id not in {
            segment.execution_scope_id for segment in path.segments
        } and path.segments:
            # Other future device scopes may be simulated by their own profile/state inputs.
            # This first storage slice must not reinterpret unrelated scopes.
            raise ValueError("Storage simulation cannot reinterpret another execution scope.")

        load_by_interval = {
            (item.starts_at, item.ends_at): item for item in load_forecast.intervals
        }
        stored_energy_wh = storage_state.current_stored_energy_wh
        capacity_wh = storage_state.usable_capacity_wh
        projected: list[ProjectedEnergyState] = []

        for pv in pv_timeline.intervals:
            if pv.ends_at <= snapshot.captured_at:
                continue
            if pv.starts_at >= path.horizon_end:
                break
            load = load_by_interval.get((pv.starts_at, pv.ends_at))
            if load is None:
                raise ValueError("Candidate simulation requires aligned canonical PV/load intervals.")
            duration_h = (pv.ends_at - pv.starts_at).total_seconds() / 3600.0
            if duration_h <= 0.0:
                raise ValueError("Candidate simulation interval duration must be positive.")

            pv_power_w = pv.energy_wh / duration_h
            load_power_w = load.expected_energy_wh / duration_h
            segment = self._active_storage_segment(path, pv.starts_at, pv.ends_at)
            charge_power_w = self._charge_power(
                segment=segment,
                pv_power_w=pv_power_w,
                load_power_w=load_power_w,
                stored_energy_wh=stored_energy_wh,
                capacity_wh=capacity_wh,
                duration_h=duration_h,
            )
            stored_energy_wh = min(
                capacity_wh,
                stored_energy_wh + charge_power_w * duration_h,
            )
            net_grid_w = load_power_w + charge_power_w - pv_power_w
            projected.append(
                ProjectedEnergyState(
                    at=pv.ends_at,
                    confidence=min(path.confidence, pv.confidence, load.confidence),
                    household_import_w=max(0.0, net_grid_w),
                    household_export_w=max(0.0, -net_grid_w),
                    pv_production_w=pv_power_w,
                    household_demand_w=load_power_w,
                    battery_soc=stored_energy_wh / capacity_wh,
                    controllable_load_w=charge_power_w,
                )
            )

        if not projected:
            raise ValueError("Candidate simulation produced no projected interval states.")
        return replace(path, projected_states=tuple(projected))

    @staticmethod
    def _active_storage_segment(
        path: EnergyPath,
        starts_at: object,
        ends_at: object,
    ) -> PathSegment | None:
        for segment in path.segments:
            if segment.starts_at <= starts_at and segment.ends_at >= ends_at:  # type: ignore[operator]
                return segment
        return None

    @staticmethod
    def _charge_power(
        *,
        segment: PathSegment | None,
        pv_power_w: float,
        load_power_w: float,
        stored_energy_wh: float,
        capacity_wh: float,
        duration_h: float,
    ) -> float:
        if segment is None or segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
            return 0.0
        assert segment.requested_power_w is not None
        room_power_w = max(0.0, capacity_wh - stored_energy_wh) / duration_h
        requested_w = min(segment.requested_power_w, room_power_w)
        if segment.charge_source_policy is ChargeSourcePolicy.PV_ONLY:
            surplus_w = max(0.0, pv_power_w - load_power_w)
            return min(requested_w, surplus_w)
        if segment.charge_source_policy is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED:
            return requested_w
        raise ValueError("Charging segment requires a supported explicit ChargeSourcePolicy.")
