"""Machine-readable ownership for the canonical PicoT architecture.

This registry is a guardrail, not a replacement for the Accepted ADR text.
Every listed module exposes its entry as ``ARCHITECTURE_OWNERSHIP`` so the
controlling boundary is visible at the code being changed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArchitectureOwnership:
    layer: str
    module: str
    adr_paths: tuple[str, ...]
    owns: tuple[str, ...]
    must_not: tuple[str, ...]


OWNERSHIP_BY_LAYER: dict[str, ArchitectureOwnership] = {
    "runtime_monitor": ArchitectureOwnership(
        layer="runtime_monitor",
        module="picot.runtime.runtime_monitor",
        adr_paths=(
            "docs/architecture/ADR-017-planning-decision-pipeline.md",
            "docs/architecture/ADR-034-runtime-monitor-material-change-replanning-contract.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
        ),
        owns=("material_change_classification", "fresh_snapshot_request"),
        must_not=("planning", "plan_mutation", "observation_suppression"),
    ),
    "live_runtime_composition": ArchitectureOwnership(
        layer="live_runtime_composition",
        module="picot.v2.live_runtime",
        adr_paths=(
            "docs/architecture/ADR-017-planning-decision-pipeline.md",
            "docs/architecture/ADR-028-runtime-resource-governance.md",
            "docs/architecture/ADR-034-runtime-monitor-material-change-replanning-contract.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
        ),
        owns=("fresh_input_polling", "planner_run_scheduling"),
        must_not=(
            "material_threshold_derivation",
            "candidate_selection",
            "plan_construction",
        ),
    ),
    "materiality_producer": ArchitectureOwnership(
        layer="materiality_producer",
        module="picot.v2.material_replanning",
        adr_paths=(
            "docs/architecture/ADR-034-runtime-monitor-material-change-replanning-contract.md",
            "docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
        ),
        owns=("material_threshold_derivation", "runtime_observation_evidence"),
        must_not=("planner_run_start", "candidate_selection", "plan_replacement"),
    ),
    "opportunity_engine": ArchitectureOwnership(
        layer="opportunity_engine",
        module="picot.v2.opportunity_engine",
        adr_paths=(
            "docs/architecture/ADR-023-opportunity-engine.md",
            "docs/architecture/ADR-036-price-opportunity-detection-contract.md",
        ),
        owns=("evidence_only_opportunities", "planning_constraints"),
        must_not=("candidate_generation", "winner_selection", "plan_construction"),
    ),
    "mep_candidate_generation": ArchitectureOwnership(
        layer="mep_candidate_generation",
        module="picot.planner.market_daily_planner",
        adr_paths=(
            "docs/architecture/ADR-017-planning-decision-pipeline.md",
            "docs/architecture/ADR-024-candidate-engine.md",
            "docs/architecture/ADR-031-candidate-scenario-construction-contract.md",
            "docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
            "docs/rebuild/V2ADR-055-mep-sole-canonical-planner.md",
        ),
        owns=("complete_candidate_paths", "physical_and_financial_outcomes"),
        must_not=("winner_selection", "commitment_admission", "vendor_dispatch"),
    ),
    "mep_candidate_outcomes": ArchitectureOwnership(
        layer="mep_candidate_outcomes",
        module="picot.planner.mep_candidate_outcomes",
        adr_paths=(
            "docs/architecture/ADR-024-candidate-engine.md",
            "docs/architecture/ADR-030-energy-path-capability-snapshot-contract.md",
            "docs/architecture/ADR-031-candidate-scenario-construction-contract.md",
            "docs/architecture/ADR-032-candidate-evaluation-contract.md",
            "docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md",
            "docs/rebuild/V2ADR-055-mep-sole-canonical-planner.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
        ),
        owns=(
            "canonical_candidate_projection",
            "canonical_projected_energy_states",
            "storage_requirement_projection",
            "fresh_incumbent_outcomes",
        ),
        must_not=("winner_selection", "commitment_admission", "plan_construction"),
    ),
    "evaluation_engine": ArchitectureOwnership(
        layer="evaluation_engine",
        module="picot.planner.market_daily_evaluation_engine",
        adr_paths=(
            "docs/architecture/ADR-026-evaluation-engine.md",
            "docs/architecture/ADR-032-candidate-evaluation-contract.md",
            "docs/rebuild/V2ADR-052-persistent-plan-commitment-and-material-replanning.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
        ),
        owns=("candidate_comparison", "incumbent_challenger_selection"),
        must_not=("candidate_generation", "plan_construction", "vendor_dispatch"),
    ),
    "execution_plan_builder": ArchitectureOwnership(
        layer="execution_plan_builder",
        module="picot.planner.execution_plan_builder",
        adr_paths=(
            "docs/architecture/ADR-016-execution-plan-architecture.md",
            "docs/architecture/ADR-033-winning-energy-path-to-execution-plans.md",
            "docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md",
            "docs/rebuild/V2ADR-050-timed-delegated-storage-control.md",
        ),
        owns=("exact_energy_path_to_plan_conversion",),
        must_not=("candidate_selection", "segment_reinterpretation", "vendor_translation"),
    ),
    "execution_plan_projection": ArchitectureOwnership(
        layer="execution_plan_projection",
        module="picot.v2.execution_plan_projection",
        adr_paths=(
            "docs/architecture/ADR-016-execution-plan-architecture.md",
            "docs/architecture/ADR-033-winning-energy-path-to-execution-plans.md",
            "docs/rebuild/V2ADR-052-persistent-plan-commitment-and-material-replanning.md",
        ),
        owns=("legacy_execution_plan_projection", "admitted_plan_identity_projection"),
        must_not=("plan_construction", "candidate_selection", "commitment_evaluation"),
    ),
    "plan_store": ArchitectureOwnership(
        layer="plan_store",
        module="picot.v2.plan_commitment_store",
        adr_paths=(
            "docs/architecture/ADR-027-execution-plan-commitment.md",
            "docs/rebuild/V2ADR-052-persistent-plan-commitment-and-material-replanning.md",
            "docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
        ),
        owns=("commitment_persistence", "restart_restoration"),
        must_not=("candidate_evaluation", "economic_selection", "vendor_dispatch"),
    ),
    "pipeline_composition": ArchitectureOwnership(
        layer="pipeline_composition",
        module="picot.v2.mep_canonical_pipeline",
        adr_paths=(
            "docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md",
            "docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md",
            "docs/rebuild/V2ADR-055-mep-sole-canonical-planner.md",
        ),
        owns=("canonical_stage_composition", "lineage_preservation"),
        must_not=(
            "private_winner_selection",
            "private_commitment_policy",
            "private_plan_construction",
        ),
    ),
    "execution_engine": ArchitectureOwnership(
        layer="execution_engine",
        module="picot.v2.canonical_execution_runtime",
        adr_paths=(
            "docs/architecture/ADR-015-execution-primitives.md",
            "docs/architecture/ADR-016-execution-plan-architecture.md",
            "docs/architecture/ADR-027-execution-plan-commitment.md",
            "docs/architecture/decisions/V2ADR-061-committed-segment-clock-boundary-execution.md",
        ),
        owns=("due_segment_validation", "primitive_request", "retry_signal"),
        must_not=("candidate_selection", "economic_reranking", "plan_replacement"),
    ),
}


def architecture_ownership(layer: str, module: str) -> ArchitectureOwnership:
    """Return and validate the declared ownership for one module."""

    ownership = OWNERSHIP_BY_LAYER[layer]
    if ownership.module != module:
        raise ValueError(
            f"architecture layer {layer!r} belongs to {ownership.module!r}, not {module!r}"
        )
    return ownership
