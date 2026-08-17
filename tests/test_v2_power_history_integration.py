from datetime import UTC, datetime, timedelta

from picot.v2.live_runtime import (
    _attach_household_power_history,
    _dashboard_power_history_specs,
)
from picot.v2.planning_input import HouseholdLoadObservation
from picot.v2.power_history import PowerHistorySnapshot

START = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
END = START + timedelta(hours=12)


def test_runtime_maps_configured_sources_to_explicit_canonical_roles() -> None:
    specs = _dashboard_power_history_specs({
        "pv_power_entity": "sensor.pv",
        "p1_power_entity": "sensor.p1",
        "zendure_power_to_house_entity": "sensor.battery_to_house",
        "zendure_power_from_house_entity": "sensor.battery_from_house",
    })

    assert [(item.role, item.entity_id, item.transform) for item in specs] == [
        ("pv_generation", "sensor.pv", "identity"),
        ("grid_import", "sensor.p1", "positive"),
        ("grid_export", "sensor.p1", "negative_magnitude"),
        ("battery_discharge", "sensor.battery_to_house", "identity"),
        ("battery_charge", "sensor.battery_from_house", "identity"),
    ]


def test_runtime_adds_only_bounded_canonical_household_observations() -> None:
    snapshot = PowerHistorySnapshot(
        starts_at=START,
        ends_at=END,
        status="empty",
        error=None,
        series=(),
    )
    observations = (
        HouseholdLoadObservation(
            power_w=400.0,
            sampled_at=START - timedelta(minutes=1),
            evidence_ids=("outside",),
            method_version="household-load:v1",
        ),
        HouseholdLoadObservation(
            power_w=650.0,
            sampled_at=START + timedelta(hours=8),
            evidence_ids=("inside",),
            method_version="household-load:v1",
        ),
    )

    enriched = _attach_household_power_history(snapshot, observations)

    assert enriched.status == "available"
    assert len(enriched.series) == 1
    assert enriched.series[0].role == "household_load"
    assert enriched.series[0].history_semantics == "sampled_linear"
    assert [point.power_w for point in enriched.series[0].points] == [650.0]
    assert [point.evidence_id for point in enriched.series[0].points] == [
        "inside"
    ]
