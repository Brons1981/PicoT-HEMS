from datetime import UTC, datetime, timedelta

from picot.v2.contracts import HouseholdLoadForecastInterval, PriceForecastPoint
from picot.v2.live_runtime import _price_opportunity_config
from picot.v2.planning_input import (
    EnergyContractConfig,
    HomeAssistantStateReader,
    SourceBinding,
    SourceEvidence,
    StorageConversionConfig,
    _energy_contract_from_price_points,
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


def test_contract_tariff_is_weighted_to_the_canonical_interval() -> None:
    quarter = timedelta(minutes=15)
    points = (
        PriceForecastPoint(
            "price-1", BASE, BASE + quarter, 0.10, 0.9, "evidence-1"
        ),
        PriceForecastPoint(
            "price-2",
            BASE + quarter,
            BASE + quarter * 2,
            0.30,
            0.8,
            "evidence-2",
        ),
    )
    settlement = HouseholdLoadForecastInterval(
        interval_id="load-1",
        starts_at=BASE,
        ends_at=BASE + quarter * 2,
        expected_energy_wh=100.0,
        confidence=0.9,
        source_reference="history",
        method_version="test:v1",
    )

    contract = _energy_contract_from_price_points(
        snapshot_id="snapshot-1",
        captured_at=BASE,
        price_points=points,
        settlement_intervals=(settlement,),
        config=EnergyContractConfig(
            settlement_timezone="Europe/Amsterdam",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
        ),
    )

    assert contract is not None
    assert contract.intervals[0].commodity_import_eur_per_kwh == 0.20
    assert contract.intervals[0].commodity_export_eur_per_kwh == 0.20
    assert contract.intervals[0].confidence == 0.8
    assert contract.intervals[0].evidence_ids == ("evidence-1", "evidence-2")


def test_contract_is_absent_when_price_evidence_has_a_gap() -> None:
    settlement = HouseholdLoadForecastInterval(
        interval_id="load-1",
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=30),
        expected_energy_wh=100.0,
        confidence=0.9,
        source_reference="history",
        method_version="test:v1",
    )
    point = PriceForecastPoint(
        "price-1",
        BASE,
        BASE + timedelta(minutes=15),
        0.10,
        1.0,
        "evidence-1",
    )

    assert _energy_contract_from_price_points(
        snapshot_id="snapshot-1",
        captured_at=BASE,
        price_points=(point,),
        settlement_intervals=(settlement,),
        config=EnergyContractConfig(
            settlement_timezone="Europe/Amsterdam",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
        ),
    ) is None


def test_live_snapshot_carries_configured_conversion_evidence(
    monkeypatch: object,
) -> None:
    horizon_end = BASE + timedelta(hours=36)
    point = PriceForecastPoint(
        "price-all",
        BASE,
        horizon_end,
        0.20,
        1.0,
        "evidence-price",
    )

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return SourceEvidence(
            evidence_id="evidence-price",
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
        household_load_fallback_power_w=500.0,
        energy_contract_config=EnergyContractConfig(
            settlement_timezone="Europe/Amsterdam",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
        ),
        storage_conversion_config=StorageConversionConfig(0.91, 0.89),
    )

    assert bundle.snapshot.energy_contract_snapshot is not None
    assert len(bundle.snapshot.energy_contract_snapshot.intervals) == 144
    assert bundle.snapshot.storage_conversion_model is not None
    assert bundle.snapshot.storage_conversion_model.charge_efficiency == 0.91
    assert bundle.snapshot.storage_conversion_model.discharge_efficiency == 0.89


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
