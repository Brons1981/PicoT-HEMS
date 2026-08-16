from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
import json
from pathlib import Path

from test_v2_delegated_storage_pipeline_integration import (
    CAPABILITY_ID,
    _snapshot,
)

from picot.v2.planning_input import PlanningInputBundle
from picot.v2.zendure_mode_capabilities import (
    derive_zendure_mode_capability_evidence,
)

BASE = datetime(2026, 8, 16, 13, 0, tzinfo=UTC)
MODE_ENTITY = "input_select.zendure_2400_ac_modus_selecteren"
NORMAL_MODES = (
    "Standby",
    "Handmatig",
    "Nul op de meter",
    "Alleen slim ontladen",
    "Alleen slim opladen",
    "Snel opladen",
    "Snel ontladen",
)


def _module() -> object:
    return import_module("picot.v2.live_storage_mode_provenance")


def _runtime(path: Path) -> object:
    module = _module()
    return module.LiveStorageModeProvenanceRuntime(
        module.StorageModeProvenanceStore(path)
    )


def _bundle(*, mode: str, captured_at: datetime = BASE) -> PlanningInputBundle:
    evidence = derive_zendure_mode_capability_evidence(
        {
            "state": mode,
            "attributes": {"options": list(NORMAL_MODES)},
        },
        captured_at=captured_at,
        source_entity_id=MODE_ENTITY,
        capability_id=CAPABILITY_ID,
        execution_scope_id="home-battery",
    )
    snapshot = replace(
        _snapshot(),
        captured_at=captured_at,
        storage_mode_capability_evidence=evidence,
        storage_mode_control_provenance=None,
    )
    return PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at,
    )


def test_store_round_trips_versioned_provenance_atomically(
    tmp_path: Path,
) -> None:
    module = _module()
    path = tmp_path / "storage-mode-provenance.json"
    store = module.StorageModeProvenanceStore(path)
    provenance = import_module(
        "picot.v2.storage_mode_provenance"
    ).initial_storage_mode_provenance(
        observed_vendor_mode="Standby",
        observed_at=BASE,
    )

    store.save(provenance)

    assert store.load() == provenance
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert persisted["provenance"]["status"] == "unverified"
    assert list(tmp_path.glob("*.tmp")) == []


def test_manual_override_survives_runtime_restart(tmp_path: Path) -> None:
    path = tmp_path / "storage-mode-provenance.json"
    first_runtime = _runtime(path)
    first_runtime.observe_vendor_mode("Standby", observed_at=BASE)
    first_runtime.record_planner_application(
        "Alleen slim opladen",
        applied_at=BASE + timedelta(seconds=1),
        application_id="application-live-1",
    )
    overridden = first_runtime.observe_vendor_mode(
        "Standby",
        observed_at=BASE + timedelta(seconds=2),
    )

    restarted_runtime = _runtime(path)
    restored = restarted_runtime.observe_vendor_mode(
        "Standby",
        observed_at=BASE + timedelta(minutes=1),
    )

    assert overridden.status == "manual_override"
    assert restored.status == "manual_override"
    assert restored.manual_override_active is True
    assert restored.last_planner_application_id == "application-live-1"


def test_corrupt_persistence_fails_closed_as_unverified(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storage-mode-provenance.json"
    path.write_text("{not-json", encoding="utf-8")

    provenance = _runtime(path).observe_vendor_mode(
        "Standby",
        observed_at=BASE,
    )

    assert provenance.status == "unverified"
    assert provenance.manual_override_active is False
    assert provenance.transition_reason == "persisted_provenance_invalid"


def test_explicit_reset_is_persisted_and_survives_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "storage-mode-provenance.json"
    runtime = _runtime(path)
    runtime.observe_vendor_mode("Standby", observed_at=BASE)
    runtime.record_planner_application(
        "Alleen slim opladen",
        applied_at=BASE + timedelta(seconds=1),
        application_id="application-live-2",
    )
    runtime.observe_vendor_mode(
        "Standby",
        observed_at=BASE + timedelta(seconds=2),
    )

    released = runtime.reset_manual_override(
        observed_vendor_mode="Standby",
        reset_at=BASE + timedelta(seconds=3),
        reset_id="reset-live-1",
    )
    restored = _runtime(path).observe_vendor_mode(
        "Standby",
        observed_at=BASE + timedelta(minutes=1),
    )

    assert released.status == "released"
    assert released.reset_id == "reset-live-1"
    assert restored.status == "released"
    assert restored.manual_override_active is False
    assert restored.transition_reason == "explicit_user_reset"


def test_live_bundle_receives_restored_provenance_before_pipeline(
    tmp_path: Path,
) -> None:
    module = _module()
    path = tmp_path / "storage-mode-provenance.json"
    runtime = _runtime(path)
    runtime.observe_vendor_mode("Standby", observed_at=BASE)
    runtime.record_planner_application(
        "Alleen slim opladen",
        applied_at=BASE + timedelta(seconds=1),
        application_id="application-live-3",
    )

    enriched = module.attach_storage_mode_provenance(
        _bundle(
            mode="Standby",
            captured_at=BASE + timedelta(seconds=2),
        ),
        runtime,
    )

    provenance = enriched.snapshot.storage_mode_control_provenance
    assert provenance is not None
    assert provenance.status == "manual_override"
    assert provenance.manual_override_active is True


def test_live_attachment_without_mode_evidence_remains_fail_closed(
    tmp_path: Path,
) -> None:
    module = _module()
    bundle = _bundle(mode="Standby")
    without_mode_evidence = replace(
        bundle,
        snapshot=replace(
            bundle.snapshot,
            storage_mode_capability_evidence=None,
        ),
    )

    enriched = module.attach_storage_mode_provenance(
        without_mode_evidence,
        _runtime(tmp_path / "storage-mode-provenance.json"),
    )

    assert enriched.snapshot.storage_mode_control_provenance is None
    assert not (tmp_path / "storage-mode-provenance.json").exists()
