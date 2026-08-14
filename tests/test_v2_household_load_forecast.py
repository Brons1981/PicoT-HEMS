from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2 import (
    ARCHITECTURE_BASELINE_COMMIT,
    PIPELINE_CONTRACT_VERSION,
    __version__,
)
from picot.v2.contracts import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
)

BASE = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


def interval(
    *,
    interval_id: str = "household-load-interval-1",
    starts_at: datetime = BASE,
    ends_at: datetime = BASE + timedelta(minutes=15),
    expected_energy_wh: float = 125.0,
    confidence: float = 0.75,
    source_reference: str = "history:comparable-period:v1",
    method_version: str = "weighted-history-profile:v1",
) -> HouseholdLoadForecastInterval:
    return HouseholdLoadForecastInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        expected_energy_wh=expected_energy_wh,
        confidence=confidence,
        source_reference=source_reference,
        method_version=method_version,
    )


def forecast(
    *,
    run_id: str = "run-household-load",
    snapshot_id: str = "snapshot-household-load",
    intervals: tuple[HouseholdLoadForecastInterval, ...] | None = None,
    fallback_active: bool = False,
    fallback_reason: str | None = None,
) -> HouseholdLoadForecast:
    return HouseholdLoadForecast(
        forecast_id="household-load-forecast-1",
        run_id=run_id,
        snapshot_id=snapshot_id,
        intervals=intervals or (interval(),),
        fallback_active=fallback_active,
        fallback_reason=fallback_reason,
    )


def planning_input(
    household_load_forecast: HouseholdLoadForecast,
) -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        run_id="run-household-load",
        snapshot_id="snapshot-household-load",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=BASE + timedelta(hours=36),
        household_load_forecast=household_load_forecast,
    )


def test_household_load_forecast_is_immutable_and_traceable() -> None:
    item = interval()
    result = forecast(intervals=(item,))

    assert item.expected_energy_wh == pytest.approx(125.0)
    assert item.confidence == pytest.approx(0.75)
    assert item.source_reference == "history:comparable-period:v1"
    assert item.method_version == "weighted-history-profile:v1"
    assert result.intervals == (item,)
    assert result.fallback_active is False
    assert result.fallback_reason is None

    with pytest.raises(FrozenInstanceError):
        item.expected_energy_wh = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        (
            {"ends_at": BASE},
            "starts_at must be before ends_at",
        ),
        (
            {"expected_energy_wh": -0.01},
            "expected_energy_wh must not be negative",
        ),
        (
            {"confidence": -0.01},
            "confidence must be between 0 and 1",
        ),
        (
            {"confidence": 1.01},
            "confidence must be between 0 and 1",
        ),
        (
            {"source_reference": ""},
            "source_reference must be explicit",
        ),
        (
            {"method_version": ""},
            "method_version must be explicit",
        ),
    ),
)
def test_household_load_interval_rejects_invalid_values(
    changes: dict[str, object],
    message: str,
) -> None:
    values = {
        "interval_id": "household-load-invalid",
        "starts_at": BASE,
        "ends_at": BASE + timedelta(minutes=15),
        "expected_energy_wh": 125.0,
        "confidence": 0.75,
        "source_reference": "history:comparable-period:v1",
        "method_version": "weighted-history-profile:v1",
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        HouseholdLoadForecastInterval(**values)


def test_household_load_forecast_rejects_overlapping_intervals() -> None:
    first = interval()
    overlapping = interval(
        interval_id="household-load-overlap",
        starts_at=BASE + timedelta(minutes=10),
        ends_at=BASE + timedelta(minutes=25),
    )

    with pytest.raises(ValueError, match="intervals must not overlap"):
        forecast(intervals=(first, overlapping))


def test_household_load_forecast_makes_fallback_explicit() -> None:
    result = forecast(
        fallback_active=True,
        fallback_reason="insufficient_history",
    )

    assert result.fallback_active is True
    assert result.fallback_reason == "insufficient_history"

    with pytest.raises(
        ValueError,
        match="fallback_reason is required when fallback is active",
    ):
        forecast(fallback_active=True)


def test_planning_input_reuses_one_household_load_forecast() -> None:
    result = forecast()
    snapshot = planning_input(result)

    assert snapshot.household_load_forecast is result


@pytest.mark.parametrize(
    ("run_id", "snapshot_id"),
    (
        ("different-run", "snapshot-household-load"),
        ("run-household-load", "different-snapshot"),
    ),
)
def test_planning_input_rejects_household_load_lineage_mismatch(
    run_id: str,
    snapshot_id: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Household load forecast lineage must match planning input",
    ):
        planning_input(
            forecast(
                run_id=run_id,
                snapshot_id=snapshot_id,
            )
        )
