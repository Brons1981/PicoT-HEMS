from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot.v2 import live_runtime, planning_input
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.planning_input import HouseholdLoadObservation

BASE = datetime(2026, 8, 14, 20, 0, tzinfo=UTC)


def historical_observations() -> tuple[HouseholdLoadObservation, ...]:
    return tuple(
        HouseholdLoadObservation(
            power_w=800.0,
            sampled_at=(
                BASE
                - timedelta(days=3)
                + timedelta(minutes=minute)
            ),
            evidence_ids=(f"evidence-history-{minute}",),
            method_version="complete-power-balance:v1",
        )
        for minute in range(0, 3 * 24 * 60, 5)
    )


@pytest.mark.parametrize(
    ("options", "expected_power_w", "expected_confidence"),
    (
        ({}, 500.0, 0.5),
        ({"household_load_fallback_power_w": 750.0}, 750.0, 0.5),
        (
            {
                "household_load_fallback_power_w": "625.5",
                "household_load_fallback_confidence": "0.6",
            },
            625.5,
            0.6,
        ),
    ),
)
def test_live_planning_input_passes_household_load_fallback_to_assembly(
    monkeypatch: object,
    options: dict[str, object],
    expected_power_w: float,
    expected_confidence: float,
) -> None:
    sentinel = object()
    calls: list[tuple[str, float, float]] = []

    def fake_assemble_planning_input(
        token: str,
        *,
        household_load_fallback_power_w: float,
        household_load_fallback_confidence: float,
    ) -> object:
        calls.append(
            (
                token,
                household_load_fallback_power_w,
                household_load_fallback_confidence,
            )
        )
        return sentinel

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        fake_assemble_planning_input,
    )

    result = live_runtime._load_live_planning_input("token", options)

    assert result is sentinel
    assert calls == [("token", expected_power_w, expected_confidence)]


def test_live_planning_input_loads_persisted_household_history(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    expected = historical_observations()[:1]
    history = HouseholdLoadHistoryStore(
        tmp_path / "household-load-history.jsonl"
    )
    history.append(expected[0])
    sentinel = object()
    calls: list[
        tuple[
            str,
            float,
            float,
            tuple[HouseholdLoadObservation, ...],
        ]
    ] = []

    def fake_assemble_planning_input(
        token: str,
        *,
        household_load_fallback_power_w: float,
        household_load_fallback_confidence: float,
        household_load_observations: tuple[
            HouseholdLoadObservation,
            ...,
        ],
    ) -> object:
        calls.append(
            (
                token,
                household_load_fallback_power_w,
                household_load_fallback_confidence,
                household_load_observations,
            )
        )
        return sentinel

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        fake_assemble_planning_input,
    )

    result = live_runtime._load_live_planning_input(
        "token",
        {},
        household_load_history=history,
    )

    assert result is sentinel
    assert calls == [("token", 500.0, 0.5, expected)]


def test_planning_input_prefers_history_and_preserves_fallback() -> None:
    history = historical_observations()

    historical_bundle = planning_input.assemble_planning_input(
        "token",
        bindings=(),
        captured_at=BASE,
        household_load_fallback_power_w=500.0,
        household_load_observations=history,
    )

    historical_forecast = (
        historical_bundle.snapshot.household_load_forecast
    )
    assert historical_forecast is not None
    assert historical_forecast.fallback_active is False
    assert historical_forecast.fallback_reason is None
    assert len(historical_forecast.intervals) == 144
    assert all(
        interval.expected_energy_wh == pytest.approx(200.0)
        for interval in historical_forecast.intervals
    )
    assert all(
        interval.method_version
        == "weighted-rolling-24h-periods:v1"
        for interval in historical_forecast.intervals
    )

    insufficient_bundle = planning_input.assemble_planning_input(
        "token",
        bindings=(),
        captured_at=BASE,
        household_load_fallback_power_w=500.0,
        household_load_observations=history[-(24 * 60 // 5):],
    )

    fallback_forecast = (
        insufficient_bundle.snapshot.household_load_forecast
    )
    assert fallback_forecast is not None
    assert fallback_forecast.fallback_active is True
    assert fallback_forecast.fallback_reason == "insufficient_history"
    assert fallback_forecast.intervals[0].expected_energy_wh == (
        pytest.approx(125.0)
    )
    assert fallback_forecast.intervals[0].confidence == pytest.approx(0.5)


@pytest.mark.parametrize(
    "invalid_power_w",
    (
        None,
        "not-a-number",
        0,
        -1,
        float("nan"),
        float("inf"),
    ),
)
def test_live_planning_input_rejects_invalid_household_load_fallback(
    monkeypatch: object,
    invalid_power_w: object,
) -> None:
    def unexpected_assembly(*args: object, **kwargs: object) -> None:
        pytest.fail("assemble_planning_input must not run with invalid configuration")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        unexpected_assembly,
    )

    with pytest.raises(
        ValueError,
        match="household_load_fallback_power_w must be a finite positive number",
    ):
        live_runtime._load_live_planning_input(
            "token",
            {"household_load_fallback_power_w": invalid_power_w},
        )



@pytest.mark.parametrize(
    "invalid_confidence",
    (None, "not-a-number", 0, -0.1, 1.1, float("nan"), float("inf")),
)
def test_live_planning_input_rejects_invalid_household_fallback_confidence(
    monkeypatch: object,
    invalid_confidence: object,
) -> None:
    def unexpected_assembly(*args: object, **kwargs: object) -> None:
        pytest.fail("assemble_planning_input must not run with invalid configuration")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        unexpected_assembly,
    )

    with pytest.raises(
        ValueError,
        match=(
            "household_load_fallback_confidence must be greater than 0 "
            "and at most 1"
        ),
    ):
        live_runtime._load_live_planning_input(
            "token",
            {"household_load_fallback_confidence": invalid_confidence},
        )
