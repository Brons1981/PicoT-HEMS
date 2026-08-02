from __future__ import annotations

from datetime import UTC, datetime

import pytest

from picot.adapters.home_assistant_zendure import (
    ZendureSnapshotError,
    zendure_snapshot_from_entities,
)

OBSERVED_AT = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)


def _states() -> dict[str, dict[str, object]]:
    return {
        "sensor.zendure_2400_ac_laadpercentage": {"state": "73"},
        "sensor.zendure_2400_ac_modus": {"state": "Ontladen"},
        "input_select.zendure_2400_ac_modus_selecteren": {
            "state": "Alleen slim ontladen"
        },
        "sensor.zendure_2400_ac_vermogen_aansturing": {"state": "-86"},
        "sensor.zendure_2400_ac_vermogen_naar_huis": {"state": "86"},
        "sensor.zendure_2400_ac_vermogen_van_huis": {"state": "0"},
        "sensor.zendure_2400_ac_soc_limiet_status": {"state": "Binnen limiet"},
        "sensor.zendure_2400_ac_error": {"state": "Geen fout"},
    }


def test_zendure_snapshot_normalizes_signed_discharge_power() -> None:
    snapshot = zendure_snapshot_from_entities(_states(), observed_at=OBSERVED_AT)

    assert snapshot.status == "available"
    assert snapshot.soc_percent == 73.0
    assert snapshot.actual_mode == "Ontladen"
    assert snapshot.requested_mode == "Alleen slim ontladen"
    assert snapshot.signed_power_w == -86.0
    assert snapshot.charge_power_w == 0.0
    assert snapshot.discharge_power_w == 86.0
    assert snapshot.power_to_house_w == 86.0
    assert snapshot.power_from_house_w == 0.0
    assert snapshot.power_consistent is True


def test_zendure_snapshot_normalizes_signed_charge_power() -> None:
    states = _states()
    states["sensor.zendure_2400_ac_vermogen_aansturing"] = {"state": "1200"}
    states["sensor.zendure_2400_ac_vermogen_naar_huis"] = {"state": "0"}
    states["sensor.zendure_2400_ac_vermogen_van_huis"] = {"state": "1190"}

    snapshot = zendure_snapshot_from_entities(states, observed_at=OBSERVED_AT)

    assert snapshot.charge_power_w == 1200.0
    assert snapshot.discharge_power_w == 0.0
    assert snapshot.power_consistent is True


def test_zendure_snapshot_marks_power_mismatch_without_failing() -> None:
    states = _states()
    states["sensor.zendure_2400_ac_vermogen_naar_huis"] = {"state": "400"}

    snapshot = zendure_snapshot_from_entities(states, observed_at=OBSERVED_AT)

    assert snapshot.power_consistent is False


def test_zendure_snapshot_rejects_unavailable_entity() -> None:
    states = _states()
    states["sensor.zendure_2400_ac_modus"] = {"state": "unavailable"}

    with pytest.raises(ZendureSnapshotError, match="unavailable"):
        zendure_snapshot_from_entities(states, observed_at=OBSERVED_AT)


def test_zendure_snapshot_rejects_out_of_range_soc() -> None:
    states = _states()
    states["sensor.zendure_2400_ac_laadpercentage"] = {"state": "101"}

    with pytest.raises(ZendureSnapshotError, match="between 0 and 100"):
        zendure_snapshot_from_entities(states, observed_at=OBSERVED_AT)


def test_zendure_snapshot_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ZendureSnapshotError, match="timezone-aware"):
        zendure_snapshot_from_entities(
            _states(),
            observed_at=datetime(2026, 8, 2, 18, 0),
        )
