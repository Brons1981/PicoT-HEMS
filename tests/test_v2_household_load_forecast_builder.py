from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    PVEnergyTimelineInterval,
    PriceForecastPoint,
)
from picot.v2.household_load_forecast import (
    build_fallback_household_load_forecast,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_input import (
    HomeAssistantStateReader,
    SourceBinding,
    SourceEvidence,
    StorageStateConfig,
    assemble_planning_input,
)

BASE = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
HORIZON_END = BASE + timedelta(hours=36)


def build(
    *,
    starts_at: datetime = BASE,
    horizon_end: datetime = HORIZON_END,
    fallback_power_w: float = 500.0,
):
    return build_fallback_household_load_forecast(
        run_id="run-household-load-builder",
        snapshot_id="snapshot-household-load-builder",
        starts_at=starts_at,
        horizon_end=horizon_end,
        fallback_power_w=fallback_power_w,
    )


def test_fallback_forecast_covers_the_36_hour_horizon() -> None:
    result = build()

    assert result.run_id == "run-household-load-builder"
    assert result.snapshot_id == "snapshot-household-load-builder"
    assert result.fallback_active is True
    assert result.fallback_reason == "insufficient_history"
    assert len(result.intervals) == 144

    first = result.intervals[0]
    last = result.intervals[-1]

    assert first.starts_at == BASE
    assert first.ends_at == BASE + timedelta(minutes=15)
    assert last.ends_at == HORIZON_END


def test_fallback_intervals_are_contiguous_and_explicit() -> None:
    result = build()

    for previous, current in zip(
        result.intervals,
        result.intervals[1:],
        strict=False,
    ):
        assert previous.ends_at == current.starts_at

    assert all(
        interval.ends_at - interval.starts_at
        == timedelta(minutes=15)
        for interval in result.intervals
    )
    assert all(
        interval.expected_energy_wh == pytest.approx(125.0)
        for interval in result.intervals
    )
    assert all(
        interval.confidence == pytest.approx(0.0)
        for interval in result.intervals
    )
    assert all(
        interval.source_reference == "fallback:configured-power"
        for interval in result.intervals
    )
    assert all(
        interval.method_version
        == "constant-power-conservative-fallback:v1"
        for interval in result.intervals
    )


def test_fallback_forecast_is_deterministic() -> None:
    first = build()
    second = build()

    assert first == second


@pytest.mark.parametrize(
    "fallback_power_w",
    (0.0, -0.01),
)
def test_fallback_requires_positive_power(
    fallback_power_w: float,
) -> None:
    with pytest.raises(
        ValueError,
        match="fallback_power_w must be positive",
    ):
        build(fallback_power_w=fallback_power_w)


def test_fallback_requires_a_positive_horizon() -> None:
    with pytest.raises(
        ValueError,
        match="starts_at must be before horizon_end",
    ):
        build(horizon_end=BASE)
def test_planning_input_reuses_fallback_and_preserves_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    price_point = PriceForecastPoint(
        point_id="price-household-load",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=1),
        value_eur_per_kwh=0.20,
        confidence=1.0,
        evidence_id="evidence-price",
    )
    pv_interval = PVEnergyTimelineInterval(
        interval_id="pv-household-load",
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=30),
        pv_energy_wh=750.0,
        evidence_type="FORECAST",
        confidence=0.8,
        actual_evidence_ids=(),
        forecast_evidence_ids=("evidence-pv",),
        conversion_method_version="forecast-energy-v1",
    )
    evidence_by_category = {
        "nordpool": SourceEvidence(
            evidence_id="evidence-price",
            category="nordpool",
            semantic_role="energy_price",
            entity_id="sensor.price",
            raw_state="0.20",
            raw_unit="EUR/kWh",
            observed_at=BASE,
            availability="available",
            mapping_version="mapping-price",
            price_points=(price_point,),
        ),
        "solcast": SourceEvidence(
            evidence_id="evidence-pv",
            category="solcast",
            semantic_role="pv_forecast",
            entity_id="sensor.pv_forecast",
            raw_state="12.0",
            raw_unit="kWh",
            observed_at=BASE,
            availability="available",
            mapping_version="mapping-pv",
            pv_energy_intervals=(pv_interval,),
        ),
        "zendure": SourceEvidence(
            evidence_id="evidence-storage",
            category="zendure",
            semantic_role="storage_soc",
            entity_id="sensor.storage_soc",
            raw_state="50",
            raw_unit="%",
            observed_at=BASE,
            availability="available",
            mapping_version="mapping-storage",
        ),
    }

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return evidence_by_category[binding.category]

    monkeypatch.setattr(
        HomeAssistantStateReader,
        "read",
        fake_read,
    )
    bundle = assemble_planning_input(
        "token",
        bindings=(
            SourceBinding(
                "nordpool",
                "energy_price",
                "sensor.price",
            ),
            SourceBinding(
                "solcast",
                "pv_forecast",
                "sensor.pv_forecast",
            ),
            SourceBinding(
                "zendure",
                "storage_soc",
                "sensor.storage_soc",
            ),
        ),
        storage_state_config=StorageStateConfig(
            execution_scope_id="home-battery",
            capability_id="storage-capability-home-battery",
            usable_capacity_wh=8000.0,
        ),
        captured_at=BASE,
        household_load_fallback_power_w=500.0,
    )

    snapshot = bundle.snapshot
    forecast = snapshot.household_load_forecast

    assert snapshot.horizon_end == HORIZON_END
    assert forecast is not None
    assert forecast.run_id == snapshot.run_id
    assert forecast.snapshot_id == snapshot.snapshot_id
    assert len(forecast.intervals) == 144
    assert forecast.intervals[0].starts_at == BASE
    assert forecast.intervals[-1].ends_at == HORIZON_END

    assert snapshot.price_points == (price_point,)
    assert len(snapshot.current_storage_states) == 1
    assert (
        snapshot.current_storage_states[0].current_soc
        == pytest.approx(0.5)
    )
    assert snapshot.pv_energy_timeline is not None
    assert snapshot.pv_energy_timeline.intervals == (
        pv_interval,
    )

    pipeline_run = CanonicalPipeline().run(
        planning_input=snapshot,
    )

    assert pipeline_run.planning_input is snapshot
    assert (
        pipeline_run.candidate_set.candidates[0].family
        == "reserve_first"
    )
    assert pipeline_run.execution_record.status == "no_due_segment"
    assert pipeline_run.primitive_boundary.status == "not_emitted"
