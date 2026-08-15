from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import PVEnergyTimelineInterval
from picot.v2.pv_deviation import evaluate_pv_energy_deviation

START = datetime(2026, 8, 15, 16, 30, tzinfo=UTC)
END = START + timedelta(minutes=30)
EVALUATED_AT = END + timedelta(minutes=5)


def interval(
    *,
    energy_wh: float,
    evidence_type: str,
    confidence: float,
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id=f"pv-{evidence_type.lower()}",
        starts_at=START,
        ends_at=END,
        pv_energy_wh=energy_wh,
        evidence_type=evidence_type,
        confidence=confidence,
        actual_evidence_ids=(
            ("actual-1", "actual-2")
            if evidence_type == "ACTUAL"
            else ()
        ),
        forecast_evidence_ids=(
            ("forecast-1",)
            if evidence_type == "FORECAST"
            else ()
        ),
        conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
            if evidence_type == "ACTUAL"
            else "solcast-interval-energy:v1"
        ),
    )


def test_pv_deviation_preserves_both_energy_lineages() -> None:
    result = evaluate_pv_energy_deviation(
        evaluated_at=EVALUATED_AT,
        forecast=interval(
            energy_wh=500.0,
            evidence_type="FORECAST",
            confidence=0.42,
        ),
        actual=interval(
            energy_wh=300.0,
            evidence_type="ACTUAL",
            confidence=1.0,
        ),
    )

    assert result.starts_at == START
    assert result.ends_at == END
    assert result.evaluated_at == EVALUATED_AT
    assert result.forecast_energy_wh == 500.0
    assert result.actual_energy_wh == 300.0
    assert result.deviation_energy_wh == -200.0
    assert result.absolute_deviation_energy_wh == 200.0
    assert result.deviation_percent == pytest.approx(-40.0)
    assert result.percentage_status == "available"
    assert result.direction == "below_forecast"
    assert result.forecast_confidence == pytest.approx(0.42)
    assert result.actual_confidence == pytest.approx(1.0)
    assert result.forecast_evidence_ids == ("forecast-1",)
    assert result.actual_evidence_ids == ("actual-1", "actual-2")
    assert (
        result.forecast_conversion_method_version
        == "solcast-interval-energy:v1"
    )
    assert (
        result.actual_conversion_method_version
        == "goodwe-state-transition-step-hold-energy:v1"
    )
    assert result.evaluation_method_version == "pv-energy-deviation:v1"


def test_nonzero_actual_against_zero_forecast_has_no_hidden_percent() -> None:
    result = evaluate_pv_energy_deviation(
        evaluated_at=EVALUATED_AT,
        forecast=interval(
            energy_wh=0.0,
            evidence_type="FORECAST",
            confidence=0.3,
        ),
        actual=interval(
            energy_wh=100.0,
            evidence_type="ACTUAL",
            confidence=1.0,
        ),
    )

    assert result.deviation_energy_wh == 100.0
    assert result.deviation_percent is None
    assert result.percentage_status == "undefined_zero_forecast"
    assert result.direction == "above_forecast"


def test_pv_deviation_requires_exactly_aligned_intervals() -> None:
    forecast = interval(
        energy_wh=500.0,
        evidence_type="FORECAST",
        confidence=0.42,
    )
    actual = interval(
        energy_wh=300.0,
        evidence_type="ACTUAL",
        confidence=1.0,
    )

    with pytest.raises(ValueError, match="interval boundaries must match"):
        evaluate_pv_energy_deviation(
            evaluated_at=EVALUATED_AT,
            forecast=forecast,
            actual=PVEnergyTimelineInterval(
                interval_id=actual.interval_id,
                starts_at=actual.starts_at + timedelta(minutes=15),
                ends_at=actual.ends_at + timedelta(minutes=15),
                pv_energy_wh=actual.pv_energy_wh,
                evidence_type=actual.evidence_type,
                confidence=actual.confidence,
                actual_evidence_ids=actual.actual_evidence_ids,
                forecast_evidence_ids=actual.forecast_evidence_ids,
                conversion_method_version=(
                    actual.conversion_method_version
                ),
            ),
        )
