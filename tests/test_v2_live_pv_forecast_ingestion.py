import json
from itertools import pairwise
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
    assert first.forecast_lower_energy_wh == pytest.approx(1187.05)
    assert first.forecast_central_energy_wh == pytest.approx(1382.3)
    assert first.forecast_upper_energy_wh == pytest.approx(1382.3)
    assert first.forecast_range_status == "available"
    assert first.forecast_range_source_fields == (
        "pv_estimate10",
        "pv_estimate",
        "pv_estimate90",
    )
    assert (
        first.forecast_range_method_version
        == "solcast-pv-estimate-range-average-kw-30m:v1"
    )
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
    assert second.forecast_lower_energy_wh == pytest.approx(1183.85)
    assert second.forecast_central_energy_wh == pytest.approx(1393.75)
    assert second.forecast_upper_energy_wh == pytest.approx(1393.75)
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


def _forecast_source_evidence(
    binding: planning_input.SourceBinding,
    *,
    observed_at: datetime,
) -> planning_input.SourceEvidence:
    source_dates = {
        "pv_forecast": "2026-08-15",
        "pv_forecast_tomorrow": "2026-08-16",
        "pv_forecast_day_3": "2026-08-17",
    }
    if binding.entity_id is None:
        return planning_input.SourceEvidence(
            evidence_id=f"evidence-{binding.semantic_role}",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=None,
            raw_state=None,
            raw_unit=None,
            observed_at=None,
            availability="unconfigured",
            mapping_version=f"mapping-{binding.semantic_role}",
        )

    source_date = source_dates[binding.semantic_role]
    starts_at = datetime.fromisoformat(
        f"{source_date}T00:00:00+02:00"
    )
    evidence_id = f"evidence-{binding.semantic_role}"
    intervals = tuple(
        PVEnergyTimelineInterval(
            interval_id=(
                f"interval-{binding.semantic_role}-{index:02d}"
            ),
            starts_at=starts_at + timedelta(minutes=30 * index),
            ends_at=starts_at + timedelta(minutes=30 * (index + 1)),
            pv_energy_wh=float(index),
            evidence_type="FORECAST",
            confidence=0.5,
            actual_evidence_ids=(),
            forecast_evidence_ids=(evidence_id,),
            conversion_method_version=(
                "solcast-detailed-forecast-average-kw-30m:v1"
            ),
        )
        for index in range(48)
    )
    return planning_input.SourceEvidence(
        evidence_id=evidence_id,
        category=binding.category,
        semantic_role=binding.semantic_role,
        entity_id=binding.entity_id,
        raw_state="1.0",
        raw_unit="kWh",
        observed_at=observed_at,
        availability="available",
        mapping_version=f"mapping-{binding.semantic_role}",
        pv_energy_intervals=intervals,
    )


def test_load_bindings_exposes_three_explicit_solcast_day_sources(
    tmp_path: object,
) -> None:
    options_path = tmp_path / "options.json"  # type: ignore[operator]
    options_path.write_text(
        json.dumps(
            {
                "solcast_forecast_entity": (
                    "sensor.solcast_pv_forecast_voorspelling_vandaag"
                ),
                "solcast_forecast_tomorrow_entity": (
                    "sensor.solcast_pv_forecast_voorspelling_morgen"
                ),
                "solcast_forecast_day_3_entity": (
                    "sensor.solcast_pv_forecast_voorspelling_dag_3"
                ),
            }
        ),
        encoding="utf-8",
    )

    bindings = planning_input.load_bindings(str(options_path))
    solcast_bindings = tuple(
        (
            binding.semantic_role,
            binding.entity_id,
        )
        for binding in bindings
        if binding.category == "solcast"
    )

    assert solcast_bindings == (
        (
            "pv_forecast",
            "sensor.solcast_pv_forecast_voorspelling_vandaag",
        ),
        (
            "pv_forecast_tomorrow",
            "sensor.solcast_pv_forecast_voorspelling_morgen",
        ),
        (
            "pv_forecast_day_3",
            "sensor.solcast_pv_forecast_voorspelling_dag_3",
        ),
    )


def test_three_solcast_sources_form_one_traceable_bounded_timeline(
    monkeypatch: object,
    tmp_path: object,
) -> None:
    captured_at = datetime.fromisoformat(
        "2026-08-15T19:45:00+02:00"
    )
    options_path = tmp_path / "options.json"  # type: ignore[operator]
    options_path.write_text(
        json.dumps(
            {
                "solcast_forecast_entity": "sensor.solcast.today",
                "solcast_forecast_tomorrow_entity": (
                    "sensor.solcast.tomorrow"
                ),
                "solcast_forecast_day_3_entity": "sensor.solcast.day_3",
            }
        ),
        encoding="utf-8",
    )

    def fake_read(
        self: planning_input.HomeAssistantStateReader,
        binding: planning_input.SourceBinding,
    ) -> planning_input.SourceEvidence:
        del self
        if binding.category != "solcast":
            return planning_input.SourceEvidence(
                evidence_id=f"evidence-{binding.semantic_role}",
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=binding.entity_id,
                raw_state=None,
                raw_unit=None,
                observed_at=None,
                availability="unconfigured",
                mapping_version=f"mapping-{binding.semantic_role}",
            )
        return _forecast_source_evidence(
            binding,
            observed_at=captured_at,
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        planning_input.HomeAssistantStateReader,
        "read",
        fake_read,
    )
    bundle = planning_input.assemble_planning_input(
        "token",
        options_path=str(options_path),
        captured_at=captured_at,
        household_load_fallback_power_w=500.0,
    )

    solcast_evidence = tuple(
        item
        for item in bundle.evidence
        if item.category == "solcast"
    )
    assert len(solcast_evidence) == 3
    assert all(
        len(item.pv_energy_intervals) == 48
        for item in solcast_evidence
    )

    timeline = bundle.snapshot.pv_energy_timeline
    assert timeline is not None
    assert bundle.snapshot.horizon_end == (
        captured_at + timedelta(hours=36)
    )
    assert len(timeline.intervals) == 111
    assert timeline.intervals[0].starts_at == datetime.fromisoformat(
        "2026-08-15T00:00:00+02:00"
    )
    assert timeline.intervals[-1].ends_at == datetime.fromisoformat(
        "2026-08-17T07:30:00+02:00"
    )
    assert all(
        interval.ends_at <= bundle.snapshot.horizon_end
        for interval in timeline.intervals
    )
    assert {
        interval.forecast_evidence_ids[0]
        for interval in timeline.intervals
    } == {
        "evidence-pv_forecast",
        "evidence-pv_forecast_tomorrow",
        "evidence-pv_forecast_day_3",
    }
    assert all(
        left.ends_at == right.starts_at
        for left, right in pairwise(timeline.intervals)
    )


def test_missing_day_3_stays_visible_and_is_not_synthesized(
    monkeypatch: object,
) -> None:
    captured_at = datetime.fromisoformat(
        "2026-08-15T19:45:00+02:00"
    )
    bindings = (
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast",
            "sensor.solcast.today",
        ),
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast_tomorrow",
            "sensor.solcast.tomorrow",
        ),
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast_day_3",
            None,
        ),
    )

    def fake_read(
        self: planning_input.HomeAssistantStateReader,
        binding: planning_input.SourceBinding,
    ) -> planning_input.SourceEvidence:
        del self
        return _forecast_source_evidence(
            binding,
            observed_at=captured_at,
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        planning_input.HomeAssistantStateReader,
        "read",
        fake_read,
    )
    bundle = planning_input.assemble_planning_input(
        "token",
        bindings=bindings,
        captured_at=captured_at,
        household_load_fallback_power_w=500.0,
    )

    day_3_evidence = next(
        item
        for item in bundle.evidence
        if item.semantic_role == "pv_forecast_day_3"
    )
    assert day_3_evidence.availability == "unconfigured"
    assert day_3_evidence.pv_energy_intervals == ()

    timeline = bundle.snapshot.pv_energy_timeline
    assert timeline is not None
    assert len(timeline.intervals) == 96
    assert timeline.intervals[-1].ends_at == datetime.fromisoformat(
        "2026-08-17T00:00:00+02:00"
    )
    assert timeline.intervals[-1].ends_at < bundle.snapshot.horizon_end


def test_overlapping_solcast_sources_are_rejected_explicitly(
    monkeypatch: object,
) -> None:
    captured_at = datetime.fromisoformat(
        "2026-08-15T19:45:00+02:00"
    )
    starts_at = datetime.fromisoformat(
        "2026-08-16T00:00:00+02:00"
    )
    bindings = (
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast",
            "sensor.solcast.today",
        ),
        planning_input.SourceBinding(
            "solcast",
            "pv_forecast_tomorrow",
            "sensor.solcast.tomorrow",
        ),
    )

    def fake_read(
        self: planning_input.HomeAssistantStateReader,
        binding: planning_input.SourceBinding,
    ) -> planning_input.SourceEvidence:
        del self
        evidence_id = f"evidence-{binding.semantic_role}"
        interval = PVEnergyTimelineInterval(
            interval_id=f"interval-{binding.semantic_role}",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            pv_energy_wh=100.0,
            evidence_type="FORECAST",
            confidence=0.5,
            actual_evidence_ids=(),
            forecast_evidence_ids=(evidence_id,),
            conversion_method_version=(
                "solcast-detailed-forecast-average-kw-30m:v1"
            ),
        )
        return planning_input.SourceEvidence(
            evidence_id=evidence_id,
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state="1.0",
            raw_unit="kWh",
            observed_at=captured_at,
            availability="available",
            mapping_version=f"mapping-{binding.semantic_role}",
            pv_energy_intervals=(interval,),
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        planning_input.HomeAssistantStateReader,
        "read",
        fake_read,
    )

    with pytest.raises(ValueError):
        planning_input.assemble_planning_input(
            "token",
            bindings=bindings,
            captured_at=captured_at,
        )
