from datetime import UTC, datetime, timedelta

from picot.v2.contracts import PriceForecastPoint
from picot.v2.live_runtime import _price_opportunity_config
from picot.v2.planning_input import (
    HomeAssistantStateReader,
    SourceBinding,
    SourceEvidence,
    _price_points_from_attributes,
    assemble_planning_input,
)

BASE = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_nordpool_attributes_become_canonical_price_points() -> None:
    points = _price_points_from_attributes(
        {
            "raw_today": [
                {
                    "start": "2026-08-13T12:00:00+00:00",
                    "end": "2026-08-13T13:00:00+00:00",
                    "value": 0.12,
                }
            ],
            "raw_tomorrow": [
                {
                    "start": "2026-08-14T00:00:00+00:00",
                    "end": "2026-08-14T01:00:00+00:00",
                    "price": -0.01,
                }
            ],
        },
        evidence_id="evidence-price",
    )

    assert len(points) == 2
    assert points[0].value_eur_per_kwh == 0.12
    assert points[1].value_eur_per_kwh == -0.01
    assert all(point.evidence_id == "evidence-price" for point in points)
    assert points[0].point_id != points[1].point_id


def test_snapshot_horizon_is_derived_from_future_price_evidence(monkeypatch: object) -> None:
    future_end = BASE + timedelta(hours=2)
    point = PriceForecastPoint(
        point_id="price-1",
        starts_at=BASE + timedelta(hours=1),
        ends_at=future_end,
        value_eur_per_kwh=0.2,
        confidence=1.0,
        evidence_id="evidence-1",
    )

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return SourceEvidence(
            evidence_id="evidence-1",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state="0.2",
            raw_unit="EUR/kWh",
            observed_at=BASE,
            availability="available",
            mapping_version="mapping-1",
            price_points=(point,),
        )

    monkeypatch.setattr(HomeAssistantStateReader, "read", fake_read)  # type: ignore[attr-defined]
    bundle = assemble_planning_input(
        "token",
        bindings=(SourceBinding("nordpool", "energy_price", "sensor.price"),),
        captured_at=BASE,
    )

    assert bundle.snapshot.price_points == (point,)
    assert bundle.snapshot.horizon_end == future_end


def test_live_price_detection_config_is_explicit_and_versioned() -> None:
    config = _price_opportunity_config(
        {
            "price_low_margin_eur_per_kwh": 0.04,
            "price_high_margin_eur_per_kwh": 0.03,
        }
    )

    assert config.low_price_margin_eur_per_kwh == 0.04
    assert config.high_price_margin_eur_per_kwh == 0.03
    assert config.config_version == "price-opportunity-v1:low=0.040000:high=0.030000"
