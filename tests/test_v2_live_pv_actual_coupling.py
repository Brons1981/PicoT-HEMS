from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

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
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import project
from picot.v2.pv_actual_history import PVHistoryReadResult
from picot.v2.pv_actual_intervals import PVPowerObservation

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
    assert first_diagnostics.processing_ms >= 0.0
    assert second_diagnostics.history_status == "cached"
    assert second_diagnostics.cache_hit is True
    assert second_diagnostics.interval_status == "actual"


def test_planning_input_card_exposes_actual_pv_runtime_diagnostics(
) -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)
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


def test_main_wires_goodwe_actual_pv_into_executed_planning_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(captured_at=CAPTURED_AT)
    requested_windows: list[tuple[datetime, datetime]] = []
    executed: list[
        tuple[PlanningInputBundle, LivePVActualDiagnostics]
    ] = []

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
        price_config: object,
        bundle: PlanningInputBundle,
        web_view_store: object,
        pv_actual_diagnostics: LivePVActualDiagnostics,
    ) -> None:
        del price_config, web_view_store
        assert token == "supervisor-token"
        executed.append((bundle, pv_actual_diagnostics))

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
    executed_bundle, diagnostics = executed[0]
    assert executed_bundle.snapshot.pv_energy_timeline is not None
    actual, future = (
        executed_bundle.snapshot.pv_energy_timeline.intervals
    )
    assert actual.evidence_type == "ACTUAL"
    assert actual.pv_energy_wh == pytest.approx(300.0)
    assert future == bundle.snapshot.pv_energy_timeline.intervals[1]
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
