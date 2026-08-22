import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

CAPTURED_AT = datetime(2026, 8, 16, 12, 30, tzinfo=UTC)
MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"


def _config(module: object) -> object:
    return module.StorageModeCapabilityConfig(
        source_entity_id=MODE_ENTITY,
        capability_id="storage-capability-home-battery",
        execution_scope_id="home-battery",
    )


def test_mode_capability_config_is_loaded_from_explicit_options(tmp_path: Path) -> None:
    planning_input = import_module("picot.v2.planning_input")
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "zendure_mode_entity": MODE_ENTITY,
                "storage_capability_id": "storage-capability-home-battery",
                "storage_execution_scope_id": "home-battery",
            }
        ),
        encoding="utf-8",
    )

    config = planning_input.load_storage_mode_capability_config(str(options_path))

    assert config.source_entity_id == MODE_ENTITY
    assert config.capability_id == "storage-capability-home-battery"
    assert config.execution_scope_id == "home-battery"


def test_home_assistant_mode_reader_uses_full_selector_payload(monkeypatch: object) -> None:
    module = import_module("picot.v2.zendure_mode_capabilities")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "state": "Nul op de meter",
                    "attributes": {
                        "options": [
                            "Standby",
                            "Nul op de meter",
                            "Dynamisch NOM",
                        ]
                    },
                }
            ).encode()

    requests: list[object] = []

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        requests.append(request)
        assert timeout == 5
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    evidence = module.HomeAssistantZendureModeCapabilityReader("token").read(
        _config(module),
        captured_at=CAPTURED_AT,
    )

    assert len(requests) == 1
    assert requests[0].full_url.endswith(MODE_ENTITY)
    assert evidence.captured_at == CAPTURED_AT
    assert evidence.current_vendor_mode == "Nul op de meter"
    assert evidence.usable_vendor_modes == ("Standby", "Nul op de meter")
    assert evidence.excluded_dynamic_vendor_modes == ("Dynamisch NOM",)


def test_mode_capability_evidence_is_atomic_planning_input(monkeypatch: object) -> None:
    planning_input = import_module("picot.v2.planning_input")
    mode_module = import_module("picot.v2.zendure_mode_capabilities")
    config = _config(mode_module)
    expected = mode_module.derive_zendure_mode_capability_evidence(
        {
            "state": "Alleen slim opladen",
            "attributes": {"options": ["Standby", "Alleen slim opladen"]},
        },
        captured_at=CAPTURED_AT,
        source_entity_id=MODE_ENTITY,
        capability_id="storage-capability-home-battery",
        execution_scope_id="home-battery",
    )

    def fake_read(self: object, read_config: object, *, captured_at: datetime) -> object:
        del self
        assert read_config == config
        assert captured_at == CAPTURED_AT
        return expected

    monkeypatch.setattr(
        mode_module.HomeAssistantZendureModeCapabilityReader,
        "read",
        fake_read,
    )
    bundle = planning_input.assemble_planning_input(
        "token",
        bindings=(),
        captured_at=CAPTURED_AT,
        storage_state_config=planning_input.StorageStateConfig(
            execution_scope_id="home-battery",
            capability_id="storage-capability-home-battery",
            usable_capacity_wh=8160.0,
            minimum_soc=0.10,
        ),
        storage_mode_capability_config=config,
    )

    assert bundle.snapshot.storage_mode_capability_evidence is expected
    assert bundle.snapshot.storage_mode_capability_evidence.captured_at == (
        bundle.snapshot.captured_at
    )
    assert bundle.snapshot.capability_snapshot_set is not None
    assert bundle.snapshot.capability_snapshot_set.snapshot_id == bundle.snapshot.snapshot_id
    assert bundle.snapshot.capability_snapshot_set.captured_at == bundle.snapshot.captured_at
    assert bundle.snapshot.capability_snapshot_set.capabilities[0].minimum_soc == 0.10
