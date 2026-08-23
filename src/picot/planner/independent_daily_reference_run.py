"""Produce one canonical complete result from one independent daily simulation."""

from __future__ import annotations

from picot.domain.daily_reference_run import DailyReferenceRun
from picot.domain.daily_reference_simulation import DailyReferenceSimulationSet
from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.planner.independent_daily_financial_settlement import (
    IndependentDailyFinancialSettlement,
)
from picot.planner.independent_daily_path_assessor import IndependentDailyPathAssessor

METHOD_VERSION = "independent-daily-reference-run:v1"


class IndependentDailyReferenceRunProducer:
    """Close assessment and financial lineage around one immutable simulation."""

    def produce(
        self,
        *,
        simulation: DailyReferenceSimulationSet,
        tariffs: DailyReferenceTariffSchedule,
    ) -> DailyReferenceRun:
        assessment = IndependentDailyPathAssessor().assess(simulation)
        financial = IndependentDailyFinancialSettlement().settle(
            simulation=simulation,
            tariffs=tariffs,
        )
        return DailyReferenceRun(
            run_id=f"daily-reference-run:{simulation.simulation_id}",
            snapshot_id=simulation.snapshot_id,
            simulation=simulation,
            assessment=assessment,
            financial=financial,
            candidate_input_complete=True,
            observer_only=True,
            selection_permitted=False,
            method_version=METHOD_VERSION,
        )
