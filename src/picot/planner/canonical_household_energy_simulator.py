"""Observer-only canonical household Energy Path simulator from V2ADR-054."""

from __future__ import annotations

from datetime import datetime

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.energy_contract import EnergyContractSnapshot, EnergyTariffInterval
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.household_energy_ledger import (
    HouseholdEnergyLedger,
    HouseholdEnergyLedgerInterval,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.storage_conversion_model import StorageConversionModel

METHOD_VERSION = "canonical-household-energy-simulator:v1"
CONFIDENCE_METHOD_VERSION = "ledger-required-input-min:v1"


class CanonicalHouseholdEnergySimulator:
    """Produce a conserved observer-only ledger without ranking or dispatch."""

    def simulate(
        self,
        *,
        run_id: str,
        candidate_id: str,
        path: EnergyPath,
        snapshot: PlanningInputSnapshot,
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        energy_contract: EnergyContractSnapshot,
        requirement_target_energy_wh: float | None = None,
    ) -> HouseholdEnergyLedger:
        self._validate_inputs(
            run_id=run_id,
            candidate_id=candidate_id,
            path=path,
            snapshot=snapshot,
            storage_state=storage_state,
            energy_contract=energy_contract,
            requirement_target_energy_wh=requirement_target_energy_wh,
        )
        assert snapshot.pv_energy_timeline is not None
        assert snapshot.household_load_forecast is not None
        loads = {
            (item.starts_at, item.ends_at): item
            for item in snapshot.household_load_forecast.intervals
        }
        tariffs = {
            (item.starts_at, item.ends_at): item for item in energy_contract.intervals
        }
        stored_energy_wh = storage_state.current_stored_energy_wh
        intervals: list[HouseholdEnergyLedgerInterval] = []

        for pv in snapshot.pv_energy_timeline.intervals:
            load = loads.get((pv.starts_at, pv.ends_at))
            if load is None:
                raise ValueError(
                    "Reference simulation requires aligned canonical PV and load intervals."
                )
            tariff = tariffs.get((pv.starts_at, pv.ends_at))
            if tariff is None:
                raise ValueError(
                    "Reference simulation requires exact tariff evidence for every interval."
                )
            segment = self._active_storage_segment(path, pv.starts_at, pv.ends_at)
            if segment is not None and segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
                raise ValueError(
                    "First reference slice supports only explicit charging segments."
                )
            policy = segment.charge_source_policy if segment is not None else None
            if policy is ChargeSourcePolicy.GRID_ALLOWED_FOR_MARKET_ACTION:
                raise ValueError("Discretionary market-cycle simulation is not implemented.")
            effective_storage_target_wh = storage_state.usable_capacity_wh
            if policy is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT:
                assert requirement_target_energy_wh is not None
                effective_storage_target_wh = requirement_target_energy_wh

            pv_to_household_wh = min(pv.energy_wh, load.expected_energy_wh)
            remaining_pv_wh = pv.energy_wh - pv_to_household_wh
            remaining_load_wh = load.expected_energy_wh - pv_to_household_wh

            requested_charge_input_wh = self._requested_charge_input_wh(
                segment=segment,
                interval_starts_at=pv.starts_at,
                interval_ends_at=pv.ends_at,
                stored_energy_wh=stored_energy_wh,
                capacity_wh=effective_storage_target_wh,
                charge_efficiency=conversion_model.charge_efficiency,
            )
            pv_to_storage_wh = min(remaining_pv_wh, requested_charge_input_wh)
            remaining_pv_wh -= pv_to_storage_wh
            grid_to_storage_wh = requested_charge_input_wh - pv_to_storage_wh

            if grid_to_storage_wh > 0.0:
                assert policy is not None
                if not policy.permits_grid_import:
                    grid_to_storage_wh = 0.0
                elif not energy_contract.permits_grid_import:
                    if policy is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT:
                        raise ValueError(
                            "Energy contract does not permit required grid charging."
                        )
                    raise ValueError("Energy contract does not permit grid charging.")

            storage_charge_input_wh = pv_to_storage_wh + grid_to_storage_wh
            storage_charge_loss_wh = storage_charge_input_wh * (
                1.0 - conversion_model.charge_efficiency
            )
            storage_energy_added_wh = storage_charge_input_wh - storage_charge_loss_wh
            storage_energy_at_end_wh = stored_energy_wh + storage_energy_added_wh

            grid_to_household_wh = (
                remaining_load_wh if energy_contract.permits_grid_import else 0.0
            )
            unserved_household_wh = remaining_load_wh - grid_to_household_wh
            pv_to_grid_wh = remaining_pv_wh if energy_contract.permits_grid_export else 0.0
            curtailed_pv_wh = remaining_pv_wh - pv_to_grid_wh
            evidence_ids = self._evidence_ids(
                path=path,
                segment=segment,
                pv_evidence_ids=pv.evidence_ids,
                load_forecast_id=snapshot.household_load_forecast.forecast_id,
                storage_state=storage_state,
                conversion_model=conversion_model,
                contract=energy_contract,
                tariff=tariff,
            )
            confidence = min(
                path.confidence,
                pv.confidence,
                load.confidence,
                storage_state.confidence,
                tariff.confidence,
            )
            intervals.append(
                HouseholdEnergyLedgerInterval(
                    starts_at=pv.starts_at,
                    ends_at=pv.ends_at,
                    household_demand_wh=load.expected_energy_wh,
                    usable_pv_wh=pv.energy_wh,
                    pv_to_household_wh=pv_to_household_wh,
                    pv_to_storage_input_wh=pv_to_storage_wh,
                    pv_to_grid_wh=pv_to_grid_wh,
                    curtailed_pv_wh=curtailed_pv_wh,
                    grid_to_household_wh=grid_to_household_wh,
                    grid_to_storage_input_wh=grid_to_storage_wh,
                    storage_to_household_output_wh=0.0,
                    storage_to_grid_output_wh=0.0,
                    storage_charge_loss_wh=storage_charge_loss_wh,
                    storage_discharge_loss_wh=0.0,
                    unserved_household_energy_wh=unserved_household_wh,
                    storage_energy_at_start_wh=stored_energy_wh,
                    storage_energy_at_end_wh=storage_energy_at_end_wh,
                    charge_source_policy=policy,
                    discharge_destination_policy=None,
                    confidence=confidence,
                    confidence_method_version=CONFIDENCE_METHOD_VERSION,
                    capability_ids=(storage_state.capability_id,),
                    evidence_ids=evidence_ids,
                )
            )
            stored_energy_wh = storage_energy_at_end_wh

        return HouseholdEnergyLedger(
            ledger_id=f"ledger:{run_id}:{candidate_id}",
            run_id=run_id,
            snapshot_id=snapshot.snapshot_id,
            candidate_id=candidate_id,
            energy_path_id=path.path_id,
            horizon_start=path.horizon_start,
            horizon_end=path.horizon_end,
            intervals=tuple(intervals),
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _validate_inputs(
        *,
        run_id: str,
        candidate_id: str,
        path: EnergyPath,
        snapshot: PlanningInputSnapshot,
        storage_state: CurrentStorageState,
        energy_contract: EnergyContractSnapshot,
        requirement_target_energy_wh: float | None,
    ) -> None:
        if not run_id.strip() or not candidate_id.strip():
            raise ValueError("Run and Candidate IDs must not be empty.")
        if path.snapshot_id != snapshot.snapshot_id:
            raise ValueError("Energy Path must match the Planning Input Snapshot.")
        if snapshot.pv_energy_timeline is None or snapshot.household_load_forecast is None:
            raise ValueError("Reference simulation requires canonical PV and load inputs.")
        if (
            snapshot.pv_energy_timeline.horizon_start != path.horizon_start
            or snapshot.pv_energy_timeline.horizon_end != path.horizon_end
            or snapshot.household_load_forecast.horizon_start != path.horizon_start
            or snapshot.household_load_forecast.horizon_end != path.horizon_end
        ):
            raise ValueError("Reference simulation inputs must share the Energy Path horizon.")
        if (
            energy_contract.valid_from > path.horizon_start
            or energy_contract.valid_until < path.horizon_end
        ):
            raise ValueError("Energy contract must cover the complete Energy Path horizon.")
        if path.segments and any(
            segment.execution_scope_id != storage_state.execution_scope_id
            for segment in path.segments
        ):
            raise ValueError("Storage simulation cannot reinterpret another execution scope.")
        requirement_segments = tuple(
            segment
            for segment in path.segments
            if segment.charge_source_policy
            is ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT
        )
        if requirement_segments and requirement_target_energy_wh is None:
            raise ValueError("Requirement grid charging requires its target energy.")
        if requirement_target_energy_wh is not None and not (
            0.0 <= requirement_target_energy_wh <= storage_state.usable_capacity_wh
        ):
            raise ValueError("Requirement target energy must remain within storage capacity.")

    @staticmethod
    def _active_storage_segment(
        path: EnergyPath,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PathSegment | None:
        return next(
            (
                segment
                for segment in path.segments
                if segment.starts_at <= starts_at and segment.ends_at >= ends_at
            ),
            None,
        )

    @staticmethod
    def _requested_charge_input_wh(
        *,
        segment: PathSegment | None,
        interval_starts_at: datetime,
        interval_ends_at: datetime,
        stored_energy_wh: float,
        capacity_wh: float,
        charge_efficiency: float,
    ) -> float:
        if segment is None:
            return 0.0
        assert segment.requested_power_w is not None
        duration_h = (interval_ends_at - interval_starts_at).total_seconds() / 3600.0
        requested_wh = segment.requested_power_w * duration_h
        room_input_wh = max(0.0, capacity_wh - stored_energy_wh) / charge_efficiency
        return min(requested_wh, room_input_wh)

    @staticmethod
    def _evidence_ids(
        *,
        path: EnergyPath,
        segment: PathSegment | None,
        pv_evidence_ids: tuple[str, ...],
        load_forecast_id: str,
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        contract: EnergyContractSnapshot,
        tariff: EnergyTariffInterval,
    ) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    path.path_id,
                    *pv_evidence_ids,
                    load_forecast_id,
                    *storage_state.evidence_ids,
                    conversion_model.model_id,
                    *conversion_model.evidence_ids,
                    contract.contract_snapshot_id,
                    *tariff.evidence_ids,
                    *(segment.evidence_ids if segment is not None else ()),
                )
            )
        )
