from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from legacy_cp_pipeline import CanonicalPipeline

import picot.v2.live_runtime as live_runtime
from picot.v2 import (
    ARCHITECTURE_BASELINE_COMMIT,
    PIPELINE_CONTRACT_VERSION,
    __version__,
)
from picot.v2.contracts import (
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.live_pv_actual import (
    LivePVActualCache,
    LivePVActualDiagnostics,
    apply_latest_closed_actual_pv,
)
from picot.v2.live_runtime import _with_planning_input_diagnostics
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import project
from picot.v2.pv_actual_history import PVHistoryReadResult
from picot.v2.pv_actual_intervals import PVPowerObservation
from picot.v2.pv_deviation import evaluate_pv_energy_deviation
from picot.v2.pv_sunset_source import SunsetReadResult

CAPTURED_AT = datetime(2026, 8, 15, 9, 5, tzinfo=UTC)
CLOSED_START = datetime(2026, 8, 15, 8, 30, tzinfo=UTC)
CLOSED_END = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
FUTURE_END = datetime(2026, 8, 15, 9, 30, tzinfo=UTC)
ENTITY_ID = "sensor.inverter_54200dsn211r0265_vermogen"


def _forecast_interval(
    *,
    interval_id: str,
    starts_at: datetime,
    ends_at: datetime,
    energy_wh: float,
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=energy_wh,
        evidence_type="FORECAST",
        confidence=0.42,
        actual_evidence_ids=(),
        forecast_evidence_ids=(f"evidence-{interval_id}",),
        conversion_method_version=(
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
        forecast_lower_energy_wh=energy_wh * 0.8,
        forecast_central_energy_wh=energy_wh,
        forecast_upper_energy_wh=energy_wh * 1.3,
        forecast_range_status="available",
        forecast_range_source_fields=(
            "pv_estimate10",
            "pv_estimate",
            "pv_estimate90",
        ),
        forecast_range_method_version=(
            "solcast-pv-estimate-range-average-kw-30m:v1"
        ),
    )


def _bundle(*, captured_at: datetime) -> PlanningInputBundle:
    run_id = f"run-{captured_at.isoformat()}"
    snapshot_id = f"snapshot-{captured_at.isoformat()}"
    timeline = PVEnergyTimeline(
        timeline_id=f"timeline-{snapshot_id}",
        run_id=run_id,
        snapshot_id=snapshot_id,
        intervals=(
            _forecast_interval(
                interval_id="solcast-0830",
                starts_at=CLOSED_START,
                ends_at=CLOSED_END,
                energy_wh=500.0,
            ),
            _forecast_interval(
                interval_id="solcast-0900",
                starts_at=CLOSED_END,
                ends_at=FUTURE_END,
                energy_wh=750.0,
            ),
        ),
    )
    snapshot = PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
        horizon_end=FUTURE_END,
        pv_energy_timeline=timeline,
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at,
    )


def test_latest_closed_pv_interval_is_fetched_once_and_replaces_forecast(
) -> None:
    requested_windows: list[tuple[datetime, datetime]] = []

    def read_history(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        assert entity_id == ENTITY_ID
        requested_windows.append((starts_at, ends_at))
        observations = (
            PVPowerObservation(
                power_w=600.0,
                sampled_at=CLOSED_START - timedelta(seconds=5),
                evidence_id="goodwe-anchor",
            ),
            *(
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=(
                        CLOSED_START + timedelta(seconds=seconds)
                    ),
                    evidence_id=f"goodwe-{seconds:04d}",
                )
                for seconds in range(0, 1801, 30)
            ),
        )
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=observations,
        )

    cache = LivePVActualCache()
    original = _bundle(captured_at=CAPTURED_AT)

    enriched, first_diagnostics = apply_latest_closed_actual_pv(
        original,
        entity_id=ENTITY_ID,
        history_reader=read_history,
        cache=cache,
        telemetry_interval_seconds=5,
    )

    fresh = replace(
        original,
        snapshot=replace(
            original.snapshot,
            run_id="run-next",
            snapshot_id="snapshot-next",
            pv_energy_timeline=replace(
                original.snapshot.pv_energy_timeline,
                run_id="run-next",
                snapshot_id="snapshot-next",
            ),
        ),
    )
    cached, second_diagnostics = apply_latest_closed_actual_pv(
        fresh,
        entity_id=ENTITY_ID,
        history_reader=read_history,
        cache=cache,
        telemetry_interval_seconds=5,
    )

    assert requested_windows == [
        (CLOSED_START - timedelta(seconds=30), CLOSED_END)
    ]

    assert enriched.snapshot.pv_energy_timeline is not None
    actual, future = enriched.snapshot.pv_energy_timeline.intervals
    assert actual.starts_at == CLOSED_START
    assert actual.ends_at == CLOSED_END
    assert actual.pv_energy_wh == pytest.approx(300.0)
    assert actual.evidence_type == "ACTUAL"
    assert len(actual.actual_evidence_ids) == 61
    assert actual.forecast_evidence_ids == (
        "evidence-solcast-0830",
    )
    assert actual.actual_evidence_ids[0] == "goodwe-0000"
    assert actual.actual_evidence_ids[-1] == "goodwe-1800"
    assert (
        actual.conversion_method_version
        == "goodwe-state-transition-step-hold-energy:v1"
    )
    assert future == original.snapshot.pv_energy_timeline.intervals[1]

    assert cached.snapshot.pv_energy_timeline is not None
    assert cached.snapshot.pv_energy_timeline.intervals[0] == actual
    assert first_diagnostics.history_status == "available"
    assert first_diagnostics.cache_hit is False
    assert first_diagnostics.interval_status == "actual"
    assert first_diagnostics.deviation_result is not None
    assert (
        first_diagnostics.deviation_result.forecast_energy_wh
        == 500.0
    )
    assert first_diagnostics.deviation_result.actual_energy_wh == 300.0
    assert (
        first_diagnostics.deviation_result.deviation_energy_wh
        == -200.0
    )
    assert first_diagnostics.deviation_result.deviation_percent == (
        pytest.approx(-40.0)
    )
    assert first_diagnostics.processing_ms >= 0.0
    assert second_diagnostics.history_status == "cached"
    assert second_diagnostics.cache_hit is True
    assert second_diagnostics.interval_status == "actual"


def test_planning_input_card_exposes_actual_pv_runtime_diagnostics(
) -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)
    forecast = bundle.snapshot.pv_energy_timeline
    assert forecast is not None
    actual = PVEnergyTimelineInterval(
        interval_id="pv-actual-0830",
        starts_at=CLOSED_START,
        ends_at=CLOSED_END,
        pv_energy_wh=300.0,
        evidence_type="ACTUAL",
        confidence=1.0,
        actual_evidence_ids=(
            "goodwe-0000",
            "goodwe-0030",
            "goodwe-1800",
        ),
        forecast_evidence_ids=("evidence-solcast-0830",),
        conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
        ),
    )
    deviation = evaluate_pv_energy_deviation(
        forecast=forecast.intervals[0],
        actual=actual,
        evaluated_at=CAPTURED_AT,
    )
    diagnostics = LivePVActualDiagnostics(
        history_status="available",
        interval_status="actual",
        cache_hit=False,
        entity_id=ENTITY_ID,
        starts_at=CLOSED_START,
        ends_at=CLOSED_END,
        lookup_starts_at=(
            CLOSED_START - timedelta(seconds=30)
        ),
        error=None,
        conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
        ),
        actual_evidence_ids=(
            "goodwe-0000",
            "goodwe-0030",
            "goodwe-1800",
        ),
        processing_ms=2.345,
        deviation_result=deviation,
    )
    run = CanonicalPipeline().run(
        planning_input=bundle.snapshot,
    )

    projection = _with_planning_input_diagnostics(
        project(run),
        bundle,
        pv_actual_diagnostics=diagnostics,
    )

    attributes = projection.cards[0].attributes
    assert attributes["pv_actual_history_status"] == "available"
    assert attributes["pv_actual_interval_status"] == "actual"
    assert attributes["pv_actual_cache_hit"] is False
    assert attributes["pv_actual_entity_id"] == ENTITY_ID
    assert (
        attributes["pv_actual_starts_at"]
        == CLOSED_START.isoformat()
    )
    assert (
        attributes["pv_actual_ends_at"]
        == CLOSED_END.isoformat()
    )
    assert (
        attributes["pv_actual_lookup_starts_at"]
        == (
            CLOSED_START - timedelta(seconds=30)
        ).isoformat()
    )
    assert attributes["pv_actual_error"] is None
    assert (
        attributes["pv_actual_conversion_method_version"]
        == "goodwe-state-transition-step-hold-energy:v1"
    )
    assert attributes["pv_actual_evidence_ids"] == [
        "goodwe-0000",
        "goodwe-0030",
        "goodwe-1800",
    ]
    assert attributes["pv_actual_processing_ms"] == 2.345
    assert attributes["pv_deviation_status"] == "evaluated"
    assert attributes["pv_deviation_id"] == deviation.deviation_id
    assert attributes["pv_deviation_starts_at"] == (
        CLOSED_START.isoformat()
    )
    assert attributes["pv_deviation_ends_at"] == CLOSED_END.isoformat()
    assert attributes["pv_deviation_evaluated_at"] == (
        CAPTURED_AT.isoformat()
    )
    assert attributes["pv_deviation_forecast_energy_wh"] == 500.0
    assert attributes["pv_deviation_forecast_lower_energy_wh"] == 400.0
    assert attributes["pv_deviation_forecast_central_energy_wh"] == 500.0
    assert attributes["pv_deviation_forecast_upper_energy_wh"] == 650.0
    assert attributes["pv_deviation_forecast_range_status"] == "available"
    assert attributes["pv_deviation_forecast_range_source_fields"] == [
        "pv_estimate10",
        "pv_estimate",
        "pv_estimate90",
    ]
    assert attributes["pv_deviation_forecast_range_method_version"] == (
        "solcast-pv-estimate-range-average-kw-30m:v1"
    )
    assert attributes["pv_deviation_range_assessment"] == "below_range"
    assert attributes["pv_deviation_range_distance_wh"] == 100.0
    assert attributes["pv_deviation_range_assessment_method_version"] == (
        "pv-forecast-range-assessment:v1"
    )
    assert attributes["pv_deviation_actual_energy_wh"] == 300.0
    assert attributes["pv_deviation_energy_wh"] == -200.0
    assert attributes["pv_deviation_absolute_energy_wh"] == 200.0
    assert attributes["pv_deviation_percent"] == pytest.approx(-40.0)
    assert attributes["pv_deviation_percentage_status"] == "available"
    assert attributes["pv_deviation_direction"] == "below_forecast"
    assert attributes["pv_deviation_forecast_confidence"] == 0.42
    assert attributes["pv_deviation_actual_confidence"] == 1.0
    assert attributes["pv_deviation_forecast_evidence_ids"] == [
        "evidence-solcast-0830"
    ]
    assert attributes["pv_deviation_actual_evidence_ids"] == [
        "goodwe-0000",
        "goodwe-0030",
        "goodwe-1800",
    ]
    assert (
        attributes["pv_deviation_forecast_conversion_method_version"]
        == "solcast-detailed-forecast-average-kw-30m:v1"
    )
    assert (
        attributes["pv_deviation_actual_conversion_method_version"]
        == "goodwe-state-transition-step-hold-energy:v1"
    )
    assert (
        attributes["pv_deviation_evaluation_method_version"]
        == "pv-energy-deviation:v1"
    )


def test_main_wires_goodwe_actual_pv_into_executed_planning_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)
    requested_windows: list[tuple[datetime, datetime]] = []
    executed: list[
        tuple[PlanningInputBundle, LivePVActualDiagnostics]
    ] = []
    power_history_timings: list[float] = []
    incident_histories: list[object] = []

    class StopLoop(Exception):
        pass

    class FakeHistoryReader:
        def __init__(self, token: str) -> None:
            assert token == "supervisor-token"

        def read(
            self,
            *,
            entity_id: str,
            starts_at: datetime,
            ends_at: datetime,
        ) -> PVHistoryReadResult:
            assert entity_id == ENTITY_ID
            requested_windows.append((starts_at, ends_at))
            return PVHistoryReadResult(
                entity_id=entity_id,
                starts_at=starts_at,
                ends_at=ends_at,
                status="available",
                error=None,
                observations=(
                    PVPowerObservation(
                        power_w=600.0,
                        sampled_at=(
                            CLOSED_START
                            - timedelta(seconds=5)
                        ),
                        evidence_id="goodwe-anchor",
                    ),
                    *(
                        PVPowerObservation(
                            power_w=600.0,
                            sampled_at=(
                                CLOSED_START
                                + timedelta(seconds=seconds)
                            ),
                            evidence_id=f"goodwe-{seconds:04d}",
                        )
                        for seconds in range(0, 1801, 30)
                    ),
                ),
            )

    def capture_execution(
        *,
        token: str,
        canonical_pipeline: object,
        price_config: object,
            bundle: PlanningInputBundle,
            web_view_store: object,
            power_history: object,
            power_history_read_ms: float,
            pv_actual_diagnostics: LivePVActualDiagnostics,
        pv_attenuated_ranges: tuple[object, ...],
        pv_sunset_source: SunsetReadResult,
        pv_sunset_local_timezone: str,
        pv_sunset_offsets: dict[str, float],
        pv_attenuation_learning_result: object,
        storage_mode_provenance_runtime: object,
        storage_mode_transition_history: object,
        canonical_execution_runtime: object,
        execution_enabled: bool,
            planning_fallback_notifier: object,
        planning_incident_history: object,
        daily_pv_basis_decision: object,
        financial_result_ledger: object,
        ) -> None:
        del (
            canonical_pipeline,
            price_config,
            web_view_store,
            power_history,
            pv_attenuated_ranges,
            pv_sunset_source,
            pv_sunset_local_timezone,
            pv_sunset_offsets,
            pv_attenuation_learning_result,
            storage_mode_provenance_runtime,
            storage_mode_transition_history,
            canonical_execution_runtime,
            execution_enabled,
            planning_fallback_notifier,
            daily_pv_basis_decision,
            financial_result_ledger,
        )
        assert token == "supervisor-token"
        executed.append((bundle, pv_actual_diagnostics))
        power_history_timings.append(power_history_read_ms)
        incident_histories.append(planning_incident_history)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
    monkeypatch.setattr(
        live_runtime,
        "load_options",
        lambda: {
            "price_low_margin_eur_per_kwh": 0.02,
            "price_high_margin_eur_per_kwh": 0.02,
            "live_poll_interval_seconds": 60,
            "pv_power_entity": ENTITY_ID,
            "pv_power_telemetry_interval_seconds": 5,
        },
    )
    monkeypatch.setattr(
        live_runtime,
        "_load_live_planning_input",
        lambda token, options, household_load_history: bundle,
    )
    monkeypatch.setattr(
        live_runtime,
        "HomeAssistantPVHistoryReader",
        FakeHistoryReader,
        raising=False,
    )
    monkeypatch.setattr(
        live_runtime,
        "_start_web_server",
        lambda store: (object(), object()),
    )
    monkeypatch.setattr(
        live_runtime,
        "_execute_planning_bundle",
        capture_execution,
    )
    monkeypatch.setattr(
        live_runtime.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(StopLoop()),
    )

    with pytest.raises(StopLoop):
        live_runtime.main()

    assert requested_windows == [
        (CLOSED_START - timedelta(seconds=30), CLOSED_END)
    ]
    assert len(executed) == 1
    assert len(power_history_timings) == 1
    assert power_history_timings[0] >= 0.0
    assert len(incident_histories) == 1
    assert isinstance(
        incident_histories[0],
        live_runtime.PlanningIncidentHistory,
    )
    executed_bundle, diagnostics = executed[0]
    assert executed_bundle.snapshot.pv_energy_timeline is not None
    actual, future = (
        executed_bundle.snapshot.pv_energy_timeline.intervals
    )
    assert actual.evidence_type == "ACTUAL"
    assert actual.pv_energy_wh == pytest.approx(300.0)
    assert future == replace(
        bundle.snapshot.pv_energy_timeline.intervals[1],
        forecast_lower_energy_wh=675.0,
    )
    assert diagnostics.history_status == "available"
    assert diagnostics.interval_status == "actual"
    assert diagnostics.entity_id == ENTITY_ID
    assert diagnostics.cache_hit is False


def test_live_actual_pv_accepts_sparse_state_changes() -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)

    def read_sparse_history(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=(
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=(
                        CLOSED_START - timedelta(seconds=5)
                    ),
                    evidence_id="goodwe-anchor",
                ),
                PVPowerObservation(
                    power_w=620.0,
                    sampled_at=(
                        CLOSED_START + timedelta(seconds=60)
                    ),
                    evidence_id="goodwe-0060",
                ),
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=CLOSED_END,
                    evidence_id="goodwe-1800",
                ),
            ),
        )

    enriched, diagnostics = apply_latest_closed_actual_pv(
        bundle,
        entity_id=ENTITY_ID,
        history_reader=read_sparse_history,
        cache=LivePVActualCache(),
        telemetry_interval_seconds=5,
    )

    assert enriched is not bundle
    assert diagnostics.interval_status == "actual"
    assert diagnostics.gap_reason is None
    assert diagnostics.observation_count == 3
    assert (
        diagnostics.first_observed_at
        == CLOSED_START - timedelta(seconds=5)
    )
    assert diagnostics.last_observed_at == CLOSED_END
    assert diagnostics.maximum_observed_gap_seconds == 1740.0
    assert diagnostics.allowed_gap_seconds is None
    assert (
        diagnostics.history_semantics
        == "home_assistant_state_changes"
    )


def test_planning_input_card_exposes_actual_pv_gap_diagnostics(
) -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)
    diagnostics = LivePVActualDiagnostics(
        history_status="available",
        interval_status="gap",
        cache_hit=False,
        entity_id=ENTITY_ID,
        starts_at=CLOSED_START,
        ends_at=CLOSED_END,
        lookup_starts_at=(
            CLOSED_START - timedelta(seconds=30)
        ),
        error=None,
        conversion_method_version=None,
        actual_evidence_ids=(),
        processing_ms=21.68,
        gap_reason="source_state_unavailable",
        observation_count=3,
        first_observed_at=(
            CLOSED_START - timedelta(seconds=5)
        ),
        last_observed_at=CLOSED_END,
        maximum_observed_gap_seconds=1740.0,
        allowed_gap_seconds=None,
        history_semantics="home_assistant_state_changes",
        interruption_state="unavailable",
        interrupted_at=CLOSED_START + timedelta(minutes=10),
    )
    run = CanonicalPipeline().run(
        planning_input=bundle.snapshot,
    )

    projection = _with_planning_input_diagnostics(
        project(run),
        bundle,
        pv_actual_diagnostics=diagnostics,
    )

    attributes = projection.cards[0].attributes
    assert (
        attributes["pv_actual_gap_reason"]
        == "source_state_unavailable"
    )
    assert attributes["pv_actual_observation_count"] == 3
    assert (
        attributes["pv_actual_first_observed_at"]
        == (
            CLOSED_START - timedelta(seconds=5)
        ).isoformat()
    )
    assert (
        attributes["pv_actual_last_observed_at"]
        == CLOSED_END.isoformat()
    )
    assert (
        attributes["pv_actual_maximum_observed_gap_seconds"]
        == 1740.0
    )
    assert attributes["pv_actual_allowed_gap_seconds"] is None
    assert (
        attributes["pv_actual_history_semantics"]
        == "home_assistant_state_changes"
    )
    assert attributes["pv_actual_interruption_state"] == (
        "unavailable"
    )
    assert attributes["pv_actual_interrupted_at"] == (
        CLOSED_START + timedelta(minutes=10)
    ).isoformat()


def test_one_bounded_history_read_actualises_all_closed_forecasts() -> None:
    captured_at = datetime(2026, 8, 15, 9, 5, tzinfo=UTC)
    first_start = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
    first_end = first_start + timedelta(minutes=30)
    second_end = first_end + timedelta(minutes=30)
    future_end = second_end + timedelta(minutes=30)
    base = _bundle(captured_at=captured_at)
    timeline = base.snapshot.pv_energy_timeline
    assert timeline is not None
    bundle = replace(
        base,
        snapshot=replace(
            base.snapshot,
            pv_energy_timeline=replace(
                timeline,
                intervals=(
                    _forecast_interval(
                        interval_id="solcast-0800",
                        starts_at=first_start,
                        ends_at=first_end,
                        energy_wh=400.0,
                    ),
                    _forecast_interval(
                        interval_id="solcast-0830",
                        starts_at=first_end,
                        ends_at=second_end,
                        energy_wh=500.0,
                    ),
                    _forecast_interval(
                        interval_id="solcast-0900",
                        starts_at=second_end,
                        ends_at=future_end,
                        energy_wh=600.0,
                    ),
                ),
            ),
        ),
    )
    read_windows: list[tuple[datetime, datetime]] = []

    def history_reader(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        assert entity_id == ENTITY_ID
        read_windows.append((starts_at, ends_at))
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=(
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=first_start - timedelta(seconds=5),
                    evidence_id="goodwe-before-0800",
                ),
                PVPowerObservation(
                    power_w=400.0,
                    sampled_at=first_end,
                    evidence_id="goodwe-0830",
                ),
                PVPowerObservation(
                    power_w=200.0,
                    sampled_at=second_end,
                    evidence_id="goodwe-0900",
                ),
            ),
        )

    enriched, diagnostics = apply_latest_closed_actual_pv(
        bundle,
        entity_id=ENTITY_ID,
        history_reader=history_reader,
        cache=LivePVActualCache(),
        telemetry_interval_seconds=5,
    )

    assert read_windows == [
        (first_start - timedelta(seconds=30), second_end)
    ]
    actualised = enriched.snapshot.pv_energy_timeline
    assert actualised is not None
    assert [
        interval.evidence_type for interval in actualised.intervals
    ] == ["ACTUAL", "ACTUAL", "FORECAST"]
    assert [
        interval.pv_energy_wh for interval in actualised.intervals
    ] == pytest.approx([300.0, 200.0, 600.0])
    assert diagnostics.closed_forecast_count == 2
    assert diagnostics.actual_interval_count == 2
    assert diagnostics.gap_interval_count == 0
    assert diagnostics.starts_at == first_start
    assert diagnostics.ends_at == second_end
    assert len(diagnostics.deviation_results) == 2
    assert [
        result.forecast_interval_id
        for result in diagnostics.deviation_results
    ] == ["solcast-0800", "solcast-0830"]
    assert diagnostics.deviation_result == diagnostics.deviation_results[-1]

    run = CanonicalPipeline().run(
        planning_input=enriched.snapshot,
    )
    projection = _with_planning_input_diagnostics(
        project(run),
        enriched,
        pv_actual_diagnostics=diagnostics,
    )
    attributes = projection.cards[0].attributes
    assert attributes["pv_actual_closed_forecast_count"] == 2
    assert attributes["pv_actual_interval_count"] == 2
    assert attributes["pv_actual_gap_interval_count"] == 0
    assert attributes["pv_deviation_result_count"] == 2


def test_unavailable_day_history_remains_explicit_closed_interval_gaps() -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)

    def history_reader(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="unavailable",
            error="history unavailable",
            observations=(),
        )

    enriched, diagnostics = apply_latest_closed_actual_pv(
        bundle,
        entity_id=ENTITY_ID,
        history_reader=history_reader,
        cache=LivePVActualCache(),
        telemetry_interval_seconds=5,
    )

    timeline = enriched.snapshot.pv_energy_timeline
    assert timeline is not None
    assert [
        interval.evidence_type for interval in timeline.intervals
    ] == ["FORECAST", "FORECAST"]
    assert diagnostics.history_status == "unavailable"
    assert diagnostics.interval_status == "gap"
    assert diagnostics.closed_forecast_count == 1
    assert diagnostics.actual_interval_count == 0
    assert diagnostics.gap_interval_count == 1
    assert diagnostics.deviation_results == ()
    assert diagnostics.deviation_result is None


def test_live_actualisation_builds_cumulative_closed_interval_evidence() -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)

    def history_reader(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=(
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=CLOSED_START - timedelta(seconds=5),
                    evidence_id="goodwe-anchor",
                ),
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=CLOSED_END,
                    evidence_id="goodwe-end",
                ),
            ),
        )

    _, diagnostics = apply_latest_closed_actual_pv(
        bundle,
        entity_id=ENTITY_ID,
        history_reader=history_reader,
        cache=LivePVActualCache(),
        telemetry_interval_seconds=5,
    )

    cumulative = diagnostics.cumulative_evidence
    assert cumulative is not None
    assert cumulative.coverage_status == "complete"
    assert cumulative.closed_interval_count == 1
    assert cumulative.assessed_interval_count == 1
    assert cumulative.gap_interval_count == 0
    assert cumulative.coverage_ratio == 1.0
    assert cumulative.forecast_central_energy_wh == 500.0
    assert cumulative.actual_energy_wh == 300.0
    assert cumulative.net_deviation_energy_wh == -200.0
    assert cumulative.forecast_lower_energy_wh == 400.0
    assert cumulative.forecast_upper_energy_wh == 650.0
    assert cumulative.range_assessment == "below_range"
    assert cumulative.below_range_interval_count == 1
    assert cumulative.interval_deviation_ids == (
        diagnostics.deviation_results[0].deviation_id,
    )


def test_planning_card_projects_cumulative_and_all_interval_evidence() -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)

    def history_reader(
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=(
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=CLOSED_START - timedelta(seconds=5),
                    evidence_id="goodwe-anchor",
                ),
                PVPowerObservation(
                    power_w=600.0,
                    sampled_at=CLOSED_END,
                    evidence_id="goodwe-end",
                ),
            ),
        )

    enriched, diagnostics = apply_latest_closed_actual_pv(
        bundle,
        entity_id=ENTITY_ID,
        history_reader=history_reader,
        cache=LivePVActualCache(),
        telemetry_interval_seconds=5,
    )
    projection = _with_planning_input_diagnostics(
        project(
            CanonicalPipeline().run(
                planning_input=enriched.snapshot,
            )
        ),
        enriched,
        pv_actual_diagnostics=diagnostics,
    )

    attributes = projection.cards[0].attributes
    cumulative = diagnostics.cumulative_evidence
    assert cumulative is not None
    assert attributes["pv_cumulative_evidence_status"] == "available"
    assert attributes["pv_cumulative_evidence_id"] == cumulative.evidence_id
    assert attributes["pv_cumulative_coverage_status"] == "complete"
    assert attributes["pv_cumulative_starts_at"] == CLOSED_START.isoformat()
    assert attributes["pv_cumulative_ends_at"] == CLOSED_END.isoformat()
    assert attributes["pv_cumulative_evaluated_at"] == (
        CAPTURED_AT.isoformat()
    )
    assert attributes["pv_cumulative_closed_interval_count"] == 1
    assert attributes["pv_cumulative_assessed_interval_count"] == 1
    assert attributes["pv_cumulative_gap_interval_count"] == 0
    assert attributes["pv_cumulative_coverage_ratio"] == 1.0
    assert attributes["pv_cumulative_forecast_central_energy_wh"] == 500.0
    assert attributes["pv_cumulative_actual_energy_wh"] == 300.0
    assert attributes["pv_cumulative_net_deviation_energy_wh"] == -200.0
    assert (
        attributes["pv_cumulative_absolute_net_deviation_energy_wh"]
        == 200.0
    )
    assert (
        attributes[
            "pv_cumulative_total_absolute_interval_deviation_energy_wh"
        ]
        == 200.0
    )
    assert attributes["pv_cumulative_deviation_percent"] == -40.0
    assert attributes["pv_cumulative_percentage_status"] == "available"
    assert attributes["pv_cumulative_forecast_lower_energy_wh"] == 400.0
    assert attributes["pv_cumulative_forecast_upper_energy_wh"] == 650.0
    assert attributes["pv_cumulative_forecast_range_status"] == "available"
    assert attributes["pv_cumulative_range_assessment"] == "below_range"
    assert attributes["pv_cumulative_range_distance_wh"] == 100.0
    assert attributes["pv_cumulative_range_assessed_interval_count"] == 1
    assert attributes["pv_cumulative_below_range_interval_count"] == 1
    assert attributes["pv_cumulative_within_range_interval_count"] == 0
    assert attributes["pv_cumulative_above_range_interval_count"] == 0
    assert attributes["pv_cumulative_unavailable_range_interval_count"] == 0
    assert attributes["pv_cumulative_interval_deviation_ids"] == [
        diagnostics.deviation_results[0].deviation_id
    ]
    assert attributes["pv_cumulative_method_version"] == (
        "pv-cumulative-deviation:aligned-closed-intervals:v1"
    )

    interval_evidence = attributes["pv_interval_deviations"]
    assert len(interval_evidence) == 1
    assert interval_evidence[0] == {
        "deviation_id": diagnostics.deviation_results[0].deviation_id,
        "starts_at": CLOSED_START.isoformat(),
        "ends_at": CLOSED_END.isoformat(),
        "forecast_interval_id": "solcast-0830",
        "actual_interval_id": (
            f"pv-actual-{CLOSED_START.isoformat()}"
        ),
        "forecast_central_energy_wh": 500.0,
        "forecast_lower_energy_wh": 400.0,
        "forecast_upper_energy_wh": 650.0,
        "actual_energy_wh": 300.0,
        "deviation_energy_wh": -200.0,
        "absolute_deviation_energy_wh": 200.0,
        "deviation_percent": -40.0,
        "percentage_status": "available",
        "direction": "below_forecast",
        "range_assessment": "below_range",
        "range_distance_wh": 100.0,
        "forecast_confidence": 0.42,
        "actual_confidence": 1.0,
        "forecast_evidence_ids": ["evidence-solcast-0830"],
        "actual_evidence_ids": ["goodwe-anchor", "goodwe-end"],
        "forecast_conversion_method_version": (
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
        "actual_conversion_method_version": (
            "goodwe-state-transition-step-hold-energy:v1"
        ),
        "range_assessment_method_version": (
            "pv-forecast-range-assessment:v1"
        ),
        "evaluation_method_version": "pv-energy-deviation:v1",
    }


def test_main_feeds_visible_sunset_evidence_into_attenuation_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(captured_at=CLOSED_END)
    diagnostics = LivePVActualDiagnostics(
        history_status="unavailable",
        interval_status="not_available",
        cache_hit=False,
        entity_id=ENTITY_ID,
        starts_at=None,
        ends_at=None,
        lookup_starts_at=None,
        error=None,
        conversion_method_version=None,
        actual_evidence_ids=(),
        processing_ms=0.0,
    )
    executed: list[dict[str, object]] = []
    read_timezones: list[object] = []
    sunset_at = datetime(
        2026,
        8,
        15,
        20,
        55,
        tzinfo=ZoneInfo("Europe/Amsterdam"),
    )
    source = SunsetReadResult(
        source_entity_id="sun.sun",
        status="available",
        error=None,
        source_updated_at=datetime(
            2026,
            8,
            15,
            9,
            0,
            tzinfo=UTC,
        ),
        sunsets_by_local_date=((date(2026, 8, 15), sunset_at),),
        method_version="home-assistant-sun-next-setting:v1",
    )

    class StopLoop(Exception):
        pass

    class FakeSunsetReader:
        def __init__(self, token: str) -> None:
            assert token == "supervisor-token"

        def read(self, *, local_timezone: object) -> SunsetReadResult:
            read_timezones.append(local_timezone)
            return source

    def capture_execution(**kwargs: object) -> None:
        executed.append(kwargs)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
    monkeypatch.setattr(
        live_runtime,
        "load_options",
        lambda: {
            "price_low_margin_eur_per_kwh": 0.02,
            "price_high_margin_eur_per_kwh": 0.02,
            "live_poll_interval_seconds": 60,
            "pv_power_entity": ENTITY_ID,
            "pv_power_telemetry_interval_seconds": 5,
            "pv_local_timezone": "Europe/Amsterdam",
        },
    )
    monkeypatch.setattr(
        live_runtime,
        "_load_live_planning_input",
        lambda token, options, household_load_history: bundle,
    )
    monkeypatch.setattr(
        live_runtime,
        "apply_latest_closed_actual_pv",
        lambda *args, **kwargs: (bundle, diagnostics),
    )
    monkeypatch.setattr(
        live_runtime,
        "HomeAssistantSunsetReader",
        FakeSunsetReader,
        raising=False,
    )
    monkeypatch.setattr(
        live_runtime,
        "_start_web_server",
        lambda store: (object(), object()),
    )
    monkeypatch.setattr(
        live_runtime,
        "_execute_planning_bundle",
        capture_execution,
    )
    monkeypatch.setattr(
        live_runtime.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(StopLoop()),
    )

    with pytest.raises(StopLoop):
        live_runtime.main()

    assert [str(value) for value in read_timezones] == [
        "Europe/Amsterdam"
    ]
    assert len(executed) == 1
    call = executed[0]
    assert call["pv_sunset_source"] == source
    assert call["pv_sunset_local_timezone"] == "Europe/Amsterdam"
    offsets = call["pv_sunset_offsets"]
    assert isinstance(offsets, dict)
    assert offsets == {
        "solcast-0900": pytest.approx(-580.0),
    }
    ranges = call["pv_attenuated_ranges"]
    assert isinstance(ranges, tuple)
    assert len(ranges) == 1
    derived = ranges[0]
    assert derived.source_interval_id == "solcast-0900"
    assert derived.minutes_from_sunset == pytest.approx(-580.0)
    assert derived.status == "unavailable"
    assert derived.unavailable_reason == "profile_unavailable"


def test_regime_duration_window_is_not_reset_by_one_positive_interval() -> None:
    starts_at = datetime(2026, 8, 17, 9, 30, tzinfo=UTC)
    deviations = (
        SimpleNamespace(
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            direction="below_forecast",
        ),
        SimpleNamespace(
            starts_at=starts_at + timedelta(minutes=30),
            ends_at=starts_at + timedelta(minutes=60),
            direction="above_forecast",
        ),
    )

    assert live_runtime._rolling_pv_direction_seconds(
        deviations,
        direction="below_forecast",
    ) == 1800
    assert live_runtime._rolling_pv_recovery_seconds(deviations) == 1800
    assert live_runtime._rolling_pv_direction_seconds(
        deviations,
        direction="above_forecast",
    ) == 1800
