import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot.v2.planning_input import (
    HomeAssistantStateReader,
    SourceBinding,
    SourceEvidence,
    StorageStateConfig,
    assemble_planning_input,
    load_bindings,
    load_storage_state_config,
)

BASE = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def test_legacy_single_battery_soc_binding_is_migrated_to_stack_soc(
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps({
            "zendure_soc_entity": (
                "sensor.zendure_2400_ac_batterij_1_laadpercentage"
            ),
        }),
        encoding="utf-8",
    )

    bindings = {
        binding.semantic_role: binding.entity_id
        for binding in load_bindings(str(options_path))
    }

    assert bindings["storage_soc"] == (
        "sensor.zendure_2400_ac_laadpercentage"
    )


def test_storage_power_bindings_are_loaded_from_explicit_options(
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "zendure_signed_power_entity": (
                    "sensor.zendure_2400_ac_vermogen_aansturing"
                ),
                "zendure_power_to_house_entity": (
                    "sensor.zendure_2400_ac_vermogen_naar_huis"
                ),
                "zendure_power_from_house_entity": (
                    "sensor.zendure_2400_ac_vermogen_van_huis"
                ),
                "market_daily_rte_entity": "sensor.zendure_2400_ac_rte_totaal",
            }
        ),
        encoding="utf-8",
    )

    bindings = {
        (binding.category, binding.semantic_role): binding.entity_id
        for binding in load_bindings(str(options_path))
    }

    assert bindings[("zendure", "storage_power_signed")] == (
        "sensor.zendure_2400_ac_vermogen_aansturing"
    )
    assert bindings[("zendure", "storage_power_to_house")] == (
        "sensor.zendure_2400_ac_vermogen_naar_huis"
    )
    assert bindings[("zendure", "storage_power_from_house")] == (
        "sensor.zendure_2400_ac_vermogen_van_huis"
    )
    assert bindings[("zendure", "storage_round_trip_efficiency")] == (
        "sensor.zendure_2400_ac_rte_totaal"
    )


def test_available_zendure_soc_becomes_current_storage_state(
    monkeypatch: object,
) -> None:
    observed_at = BASE - timedelta(seconds=5)

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return SourceEvidence(
            evidence_id="evidence-zendure-soc",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state="40",
            raw_unit="%",
            observed_at=observed_at,
            availability="available",
            mapping_version="mapping-zendure-soc",
        )

    monkeypatch.setattr(HomeAssistantStateReader, "read", fake_read)  # type: ignore[attr-defined]
    bundle = assemble_planning_input(
        "token",
        bindings=(
            SourceBinding(
                "zendure",
                "storage_soc",
                "sensor.zendure_battery_soc",
            ),
        ),
        storage_state_config=StorageStateConfig(
            execution_scope_id="home-battery",
            capability_id="storage-capability-home-battery",
            usable_capacity_wh=8160.0,
        ),
        captured_at=BASE,
    )

    assert len(bundle.snapshot.current_storage_states) == 1
    state = bundle.snapshot.current_storage_states[0]
    assert state.execution_scope_id == "home-battery"
    assert state.capability_id == "storage-capability-home-battery"
    assert state.current_soc == pytest.approx(0.40)
    assert state.usable_capacity_wh == pytest.approx(8160.0)
    assert state.current_stored_energy_wh == pytest.approx(3264.0)
    assert state.measured_at == observed_at
    assert state.confidence == pytest.approx(1.0)
    assert state.evidence_ids == ("evidence-zendure-soc",)


def test_available_zendure_total_rte_enters_planning_input(
    monkeypatch: object,
) -> None:
    observed_at = BASE - timedelta(seconds=5)

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return SourceEvidence(
            evidence_id="evidence-zendure-rte",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state="83",
            raw_unit="%",
            observed_at=observed_at,
            availability="available",
            mapping_version="mapping-zendure-rte",
        )

    monkeypatch.setattr(HomeAssistantStateReader, "read", fake_read)  # type: ignore[attr-defined]
    bundle = assemble_planning_input(
        "token",
        bindings=(
            SourceBinding(
                "zendure",
                "storage_round_trip_efficiency",
                "sensor.zendure_2400_ac_rte_totaal",
            ),
        ),
        captured_at=BASE,
    )

    evidence = bundle.snapshot.storage_round_trip_efficiency
    assert evidence is not None
    assert evidence.status == "available"
    assert evidence.round_trip_efficiency == 0.83
    assert evidence.source_entity_id == "sensor.zendure_2400_ac_rte_totaal"


def test_storage_state_config_is_loaded_from_explicit_options(
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "storage_execution_scope_id": "home-battery",
                "storage_capability_id": "storage-capability-home-battery",
                "storage_usable_capacity_wh": 8160.0,
                "storage_minimum_soc_percent": 10.0,
                "storage_maximum_soc_percent": 100.0,
                "storage_maximum_charge_power_w": 2400.0,
                "storage_maximum_discharge_power_w": 2400.0,
            }
        ),
        encoding="utf-8",
    )

    assert load_storage_state_config(str(options_path)) == StorageStateConfig(
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        usable_capacity_wh=8160.0,
        minimum_soc=0.10,
        maximum_soc=1.0,
        maximum_charge_power_w=2400.0,
        maximum_discharge_power_w=2400.0,
    )


def test_storage_state_config_is_absent_without_positive_capacity(
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "storage_execution_scope_id": "home-battery",
                "storage_capability_id": "storage-capability-home-battery",
                "storage_usable_capacity_wh": 0.0,
            }
        ),
        encoding="utf-8",
    )

    assert load_storage_state_config(str(options_path)) is None


def test_default_assembly_loads_storage_config_from_same_options(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "zendure_soc_entity": "sensor.zendure_battery_soc",
                "storage_execution_scope_id": "home-battery",
                "storage_capability_id": "storage-capability-home-battery",
                "storage_usable_capacity_wh": 8160.0,
                "storage_minimum_soc_percent": 10.0,
                "storage_maximum_soc_percent": 100.0,
                "storage_maximum_charge_power_w": 2400.0,
                "storage_maximum_discharge_power_w": 2400.0,
            }
        ),
        encoding="utf-8",
    )
    observed_at = BASE - timedelta(seconds=5)

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        if binding.category == "zendure":
            return SourceEvidence(
                evidence_id="evidence-zendure-live",
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=binding.entity_id,
                raw_state="40",
                raw_unit="%",
                observed_at=observed_at,
                availability="available",
                mapping_version="mapping-zendure-live",
            )
        return SourceEvidence(
            evidence_id=f"evidence-{binding.category}-unconfigured",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=None,
            raw_state=None,
            raw_unit=None,
            observed_at=None,
            availability="unconfigured",
            mapping_version=f"mapping-{binding.category}-unconfigured",
        )

    monkeypatch.setattr(HomeAssistantStateReader, "read", fake_read)  # type: ignore[attr-defined]
    bundle = assemble_planning_input(
        "token",
        options_path=str(options_path),
        captured_at=BASE,
    )

    assert len(bundle.snapshot.current_storage_states) == 1
    state = bundle.snapshot.current_storage_states[0]
    assert state.current_soc == pytest.approx(0.40)
    assert state.usable_capacity_wh == pytest.approx(8160.0)
    assert state.current_stored_energy_wh == pytest.approx(3264.0)
    assert state.confidence == pytest.approx(1.0)
    assert state.evidence_ids == ("evidence-zendure-live",)
    assert len(bundle.snapshot.storage_physical_limits) == 1
    limits = bundle.snapshot.storage_physical_limits[0]
    assert limits.execution_scope_id == "home-battery"
    assert limits.capability_id == "storage-capability-home-battery"
    assert limits.minimum_soc == pytest.approx(0.10)
    assert limits.maximum_soc == pytest.approx(1.0)
    assert limits.maximum_charge_input_power_w == pytest.approx(2400.0)
    assert limits.maximum_discharge_output_power_w == pytest.approx(2400.0)
    assert limits.evidence_ids == ("addon-configuration:storage-physical-limits",)


def test_existing_options_gain_daily_reference_physical_defaults(
    tmp_path: Path,
) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps({
            "storage_execution_scope_id": "home-battery",
            "storage_capability_id": "storage-capability-home-battery",
            "storage_usable_capacity_wh": 8160.0,
            "storage_minimum_soc_percent": 10.0,
        }),
        encoding="utf-8",
    )

    config = load_storage_state_config(str(options_path))

    assert config is not None
    assert config.maximum_soc == 1.0
    assert config.maximum_charge_power_w == 2400.0
    assert config.maximum_discharge_power_w == 2400.0


def test_live_power_evidence_becomes_household_load_observation(
    monkeypatch: object,
) -> None:
    source_observed_at = BASE - timedelta(seconds=5)
    values = {
        "grid_power": "200",
        "pv_power": "1000",
        "storage_power_signed": "300",
        "storage_power_to_house": "0",
        "storage_power_from_house": "300",
    }

    def fake_read(
        self: HomeAssistantStateReader,
        binding: SourceBinding,
    ) -> SourceEvidence:
        del self
        return SourceEvidence(
            evidence_id=f"evidence-{binding.semantic_role}",
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state=values[binding.semantic_role],
            raw_unit="W",
            observed_at=source_observed_at,
            availability="available",
            mapping_version=f"mapping-{binding.semantic_role}",
        )

    monkeypatch.setattr(HomeAssistantStateReader, "read", fake_read)
    bundle = assemble_planning_input(
        "token",
        bindings=(
            SourceBinding("p1", "grid_power", "sensor.grid"),
            SourceBinding("pv", "pv_power", "sensor.pv"),
            SourceBinding(
                "zendure",
                "storage_power_signed",
                "sensor.storage_signed",
            ),
            SourceBinding(
                "zendure",
                "storage_power_to_house",
                "sensor.storage_to_house",
            ),
            SourceBinding(
                "zendure",
                "storage_power_from_house",
                "sensor.storage_from_house",
            ),
        ),
        captured_at=BASE,
    )

    assert bundle.household_load_observation is not None
    observation = bundle.household_load_observation
    assert observation.power_w == pytest.approx(900.0)
    assert observation.sampled_at == BASE
    assert observation.evidence_ids == (
        "evidence-grid_power",
        "evidence-pv_power",
        "evidence-storage_power_signed",
        "evidence-storage_power_to_house",
        "evidence-storage_power_from_house",
    )
    assert observation.method_version == "complete-power-balance:v1"
