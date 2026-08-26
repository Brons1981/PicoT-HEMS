from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import picot.v2.planner_comparison_ledger as comparison_ledger
from picot.v2.planner_comparison_ledger import PlannerComparisonLedger
from picot.v2.planner_comparison_ledger import (
    MAX_ACTIVE_DOSSIERS,
)


def _dossier(*, start: datetime | None = None) -> dict:
    start = start or datetime(2026, 8, 24, 10, tzinfo=UTC)
    end = start + timedelta(hours=2)
    points = {
        f"p-{role}-{index}": {
            "at": (start + timedelta(minutes=15 * index)).isoformat(),
            "power_w": power,
            "semantics": "state_hold",
        }
        for role, power in (
            ("pv_generation", 2000.0),
            ("household_load", 500.0),
            ("grid_import", 0.0),
            ("grid_export", 1000.0),
            ("battery_charge", 500.0),
            ("battery_discharge", 0.0),
        )
        for index in range(9)
    }
    measurements = {
        role: {key: value for key, value in points.items() if f"-{role}-" in key}
        for role in (
            "pv_generation",
            "household_load",
            "grid_import",
            "grid_export",
            "battery_charge",
            "battery_discharge",
        )
    }
    return {
        "comparison_id": "comparison",
        "snapshot_id": "snapshot",
        "captured_at": start.isoformat(),
        "horizon_end": end.isoformat(),
        "status": "measuring",
        "canonical": {
            "charge_window_starts_at": start.isoformat(),
            "charge_window_ends_at": (start + timedelta(hours=1)).isoformat(),
        },
        "observer": {
            "intent_intervals": [
                {
                    "starts_at": start.isoformat(),
                    "ends_at": end.isoformat(),
                    "intent": "nom",
                }
            ],
        },
        "physical": {
            "initial_energy_wh": 1000.0,
            "capacity_wh": 4000.0,
            "minimum_energy_wh": 400.0,
            "target_energy_wh": 4000.0,
            "maximum_charge_power_w": 2400.0,
            "maximum_discharge_power_w": 2400.0,
            "charge_efficiency": 1.0,
            "discharge_efficiency": 1.0,
        },
        "prices": [
            {
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
            "import_eur_per_kwh": 0.25,
            "export_eur_per_kwh": 0.25,
            }
        ],
        "measurements": measurements,
        "storage_samples": [],
        "stress_markers": [],
        "result": None,
        "observer_only": True,
        "selection_permitted": False,
        "commitment_permitted": False,
    }


def test_closes_both_planners_against_same_measurements(tmp_path) -> None:
    ledger = PlannerComparisonLedger(
        state_path=tmp_path / "state.json", history_path=tmp_path / "history.jsonl"
    )
    dossier = _dossier()
    ledger._close(dossier)

    assert dossier["status"] == "completed"
    assert dossier["result"]["same_measured_reality"] is True
    assert dossier["result"]["planners"]["canonical"]["status"] == "complete"
    assert dossier["result"]["planners"]["daily_observer"]["status"] == "complete"
    assert (
        json.loads((tmp_path / "history.jsonl").read_text().splitlines()[0])["snapshot_id"]
        == "snapshot"
    )
    assert "measurements" not in dossier
    assert "prices" not in dossier
    assert "physical" not in dossier
    assert "storage_samples" not in dossier


def test_oversized_state_is_quarantined_before_json_parse(
    tmp_path, monkeypatch, capsys
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("not-json-and-deliberately-oversized", encoding="utf-8")
    monkeypatch.setattr(comparison_ledger, "MAX_STATE_BYTES", 8)

    ledger = PlannerComparisonLedger(
        state_path=state_path,
        history_path=tmp_path / "history.jsonl",
    )

    assert ledger._state["dossiers"] == {}
    assert ledger._state["recovery"]["status"] == (
        "oversized_state_quarantined"
    )
    assert not state_path.exists()
    quarantine_files = list(tmp_path.glob("state.oversized-*.json"))
    assert len(quarantine_files) == 1
    assert quarantine_files[0].read_text(encoding="utf-8") == (
        "not-json-and-deliberately-oversized"
    )
    assert "picot_v2_planner_comparison_state_quarantined" in capsys.readouterr().out


def test_save_keeps_only_latest_active_dossiers(tmp_path) -> None:
    ledger = PlannerComparisonLedger(
        state_path=tmp_path / "state.json",
        history_path=tmp_path / "history.jsonl",
    )
    start = datetime(2026, 8, 24, 10, tzinfo=UTC)
    ledger._state["dossiers"] = {
        f"snapshot-{index}": {
            "snapshot_id": f"snapshot-{index}",
            "captured_at": (start + timedelta(minutes=index)).isoformat(),
        }
        for index in range(MAX_ACTIVE_DOSSIERS + 3)
    }

    ledger._save()

    persisted = json.loads(ledger.state_path.read_text(encoding="utf-8"))
    assert len(persisted["dossiers"]) == MAX_ACTIVE_DOSSIERS
    assert "snapshot-0" not in persisted["dossiers"]
    assert f"snapshot-{MAX_ACTIVE_DOSSIERS + 2}" in persisted["dossiers"]


def test_incomplete_measurement_coverage_never_names_winner(tmp_path) -> None:
    ledger = PlannerComparisonLedger(
        state_path=tmp_path / "state.json", history_path=tmp_path / "history.jsonl"
    )
    dossier = _dossier()
    dossier["measurements"].pop("household_load")
    ledger._close(dossier)

    assert dossier["status"] == "insufficient_data"
    assert "winner" not in dossier["result"]


def test_explicit_stress_marker_survives_restart_and_is_passive(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    ledger = PlannerComparisonLedger(state_path=state_path, history_path=tmp_path / "history.jsonl")
    occurred_at = datetime.now(UTC)
    ledger._state["dossiers"] = {
        "snapshot": _dossier(start=occurred_at - timedelta(hours=1))
    }
    result = ledger.mark_stress(
        marker_id="manual-1", occurred_at=occurred_at, note="handmatig ontladen"
    )

    assert result["observer_only"] is True
    restarted = PlannerComparisonLedger(
        state_path=state_path, history_path=tmp_path / "history.jsonl"
    )
    view = restarted.dashboard_view()
    assert view["selection_permitted"] is False
    assert view["dossiers"][0]["stress_markers"][0]["marker_id"] == "manual-1"
    assert (
        view["dossiers"][0]["projection_state"]
        == "superseded_by_manual_stress"
    )
