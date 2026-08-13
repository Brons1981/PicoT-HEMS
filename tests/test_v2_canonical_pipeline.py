from datetime import UTC, datetime

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, __version__
from picot.v2.pipeline import CanonicalPipeline


def test_v2_bootstrap_pipeline_keeps_one_run_and_snapshot() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    )

    expected_run_id = run.planning_input.run_id
    expected_snapshot_id = run.planning_input.snapshot_id
    records = (
        run.opportunities,
        run.candidate_set,
        run.outcomes,
        run.evaluation,
        run.execution_plan_set,
        run.execution_record,
        run.primitive_boundary,
        run.adapter_boundary,
        run.vendor_result,
    )

    assert run.planning_input.picot_version == __version__
    assert run.planning_input.architecture_baseline_commit == ARCHITECTURE_BASELINE_COMMIT
    assert all(record.run_id == expected_run_id for record in records)
    assert all(record.snapshot_id == expected_snapshot_id for record in records)
    assert run.evaluation.winning_candidate_id == run.candidate_set.candidates[0].candidate_id
    assert run.evaluation.winning_energy_path_id == run.candidate_set.energy_paths[0].path_id
    assert run.execution_plan_set.plan_ids == ()
    assert run.primitive_boundary.request_id is None
    assert run.adapter_boundary.translation_id is None
    assert run.vendor_result.command_id is None


def test_v2_timed_pipeline_reports_all_canonical_stage_timings() -> None:
    run, timings = CanonicalPipeline().run_timed(
        captured_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    )

    assert run.planning_input.picot_version == __version__
    values = (
        timings.opportunity_engine_ms,
        timings.candidate_engine_ms,
        timings.evaluation_engine_ms,
        timings.execution_plan_builder_ms,
        timings.execution_engine_ms,
        timings.execution_primitive_ms,
        timings.device_adapter_ms,
        timings.vendor_result_ms,
        timings.canonical_total_ms,
    )
    assert all(value >= 0.0 for value in values)
    assert timings.canonical_total_ms >= timings.opportunity_engine_ms
