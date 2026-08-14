import json
from datetime import datetime, timedelta

import pytest

from picot.v2 import planning_input
from picot.v2.contracts import PVEnergyTimelineInterval


def test_solcast_half_hour_power_forecast_becomes_pv_energy() -> None:
    attributes = {
        "dataCorrect": True,
        "analysis": {
            "intervals": [
                {
                    "period_start": "2026-08-14T12:00:00+02:00",
                    "confidence": 0.8587,
                },
                {
                    "period_start": "2026-08-14T12:30:00+02:00",
                    "confidence": 0.8494,
                },
            ],
        },
        "detailedForecast": [
            {
                "period_start": "2026-08-14T12:00:00+02:00",
                "pv_estimate": 2.7646,
                "pv_estimate10": 2.3741,
                "pv_estimate90": 2.7646,
            },
            {
                "period_start": "2026-08-14T12:30:00+02:00",
                "pv_estimate": 2.7875,
                "pv_estimate10": 2.3677,
                "pv_estimate90": 2.7875,
            },
        ],
    }
    converter_name = "_pv_forecast_intervals_from_attributes"

    assert converter_name in planning_input.__dict__, (
        "Solcast PV forecast conversion is not implemented"
    )
    convert = planning_input.__dict__[converter_name]
    intervals = convert(
        attributes,
        evidence_id="evidence-solcast-today",
    )

    assert len(intervals) == 2
    first, second = intervals
    first_start = datetime.fromisoformat(
        "2026-08-14T12:00:00+02:00"
    )

    assert first.starts_at == first_start
    assert first.ends_at == first_start + timedelta(minutes=30)
    assert first.pv_energy_wh == pytest.approx(1382.3)
    assert first.evidence_type == "FORECAST"
    assert first.confidence == pytest.approx(0.8587)
    assert first.actual_evidence_ids == ()
    assert first.forecast_evidence_ids == (
        "evidence-solcast-today",
    )
    assert (
        first.conversion_method_version
        == "solcast-detailed-forecast-average-kw-30m:v1"
    )

    assert second.starts_at == first.ends_at
    assert second.ends_at == second.starts_at + timedelta(minutes=30)
    assert second.pv_energy_wh == pytest.approx(1393.75)
    assert second.confidence == pytest.approx(0.8494)


def test_solcast_reader_preserves_converted_intervals_in_source_evidence(
    monkeypatch: object,
) -> None:
    payload = {
        "state": "23.9977",
        "last_updated": "2026-08-14T10:00:00+02:00",
        "attributes": {
            "unit_of_measurement": "kWh",
            "dataCorrect": True,
            "analysis": {
                "intervals": [
                    {
                        "period_start": "2026-08-14T12:00:00+02:00",
                        "confidence": 0.8587,
                    }
                ],
            },
            "detailedForecast": [
                {
                    "period_start": "2026-08-14T12:00:00+02:00",
                    "pv_estimate": 2.7646,
                    "pv_estimate10": 2.3741,
                    "pv_estimate90": 2.7646,
                }
            ],
        },
    }

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(
        request: object,
        timeout: int,
    ) -> FakeResponse:
        del request, timeout
        return FakeResponse()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        planning_input,
        "urlopen",
        fake_urlopen,
    )
    evidence = planning_input.HomeAssistantStateReader("token").read(
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast",
            "sensor.solcast_pv_forecast_voorspelling_vandaag",
        )
    )

    assert evidence.availability == "available"
    assert len(evidence.pv_energy_intervals) == 1
    interval = evidence.pv_energy_intervals[0]
    assert interval.pv_energy_wh == pytest.approx(1382.3)
    assert interval.confidence == pytest.approx(0.8587)
    assert interval.evidence_type == "FORECAST"
    assert interval.forecast_evidence_ids == (evidence.evidence_id,)


def test_planning_input_snapshot_reuses_solcast_evidence_as_one_timeline(
    monkeypatch: object,
) -> None:
    captured_at = datetime.fromisoformat(
        "2026-08-14T10:00:00+02:00"
    )
    starts_at = datetime.fromisoformat(
        "2026-08-14T12:00:00+02:00"
    )
    interval = PVEnergyTimelineInterval(
        interval_id="pv-energy-interval-solcast",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=1382.3,
        evidence_type="FORECAST",
        confidence=0.8587,
        actual_evidence_ids=(),
        forecast_evidence_ids=("evidence-solcast-today",),
        conversion_method_version=(
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
    )

    def fake_read(
        self: planning_input.HomeAssistantStateReader,
        binding: planning_input.SourceBinding,
    ) -> planning_input.SourceEvidence:
        del self
        return planning_input.SourceEvidence(
            evidence_id="evidence-solcast-today",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state="23.9977",
            raw_unit="kWh",
            observed_at=captured_at,
            availability="available",
            mapping_version="mapping-solcast-today",
            pv_energy_intervals=(interval,),
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        planning_input.HomeAssistantStateReader,
        "read",
        fake_read,
    )
    bundle = planning_input.assemble_planning_input(
        "token",
        bindings=(
            planning_input.SourceBinding(
                "solcast",
                "pv_forecast",
                "sensor.solcast_pv_forecast_voorspelling_vandaag",
            ),
        ),
        captured_at=captured_at,
    )

    timeline = bundle.snapshot.pv_energy_timeline
    assert timeline is not None
    assert timeline.run_id == bundle.snapshot.run_id
    assert timeline.snapshot_id == bundle.snapshot.snapshot_id
    assert timeline.intervals == (interval,)
