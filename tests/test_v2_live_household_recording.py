from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_v2_live_replan_poll_cycle import BASE, _bundle

import picot.v2.live_runtime as runtime
from picot.v2.household_load_history import HouseholdLoadHistoryStore


def test_live_loader_records_poll_and_in_planning_refresh_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Fresh input acquired outside the poll cycle must also reach history."""
    for name, value in vars(runtime).copy().items():
        if name.endswith("_PATH") and isinstance(value, Path):
            monkeypatch.setattr(runtime, name, tmp_path / value.name)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(runtime, "load_options", lambda: {
        "price_low_margin_eur_per_kwh": 0.02,
        "price_high_margin_eur_per_kwh": 0.02,
        "health_notifications_enabled": False,
        "pv_power_entity": "sensor.test_pv",
    })
    monkeypatch.setattr(runtime, "_start_web_server", lambda store: (None, None))
    monkeypatch.setattr(runtime, "start_calendar_observer", lambda *a, **kw: None)
    monkeypatch.setattr(runtime, "_start_energy_device_catalog_observer", lambda **kw: None)
    first = _bundle(captured_at=BASE, price=0.20)
    fresh = _bundle(captured_at=BASE + timedelta(minutes=3), price=0.20)
    missing = replace(
        _bundle(captured_at=BASE + timedelta(minutes=4), price=0.20),
        household_load_observation=None,
    )
    bundles = iter((first, fresh, missing))
    monkeypatch.setattr(runtime, "_load_live_planning_input", lambda *a, **kw: next(bundles))
    rejected = []
    monkeypatch.setattr(runtime.HouseholdLoadRejectionStore, "append",
                        lambda self, bundle: rejected.append(bundle))
    original_poll = runtime._poll_live_cycle

    class StopLoop(Exception):
        pass

    def exercise_loads(**kwargs: Any) -> None:
        loader = kwargs["load_bundle"]
        assert callable(loader)
        # Run a normal poll using the production persistence configuration.
        original_poll(
            previous_signature=None, load_bundle=loader, execute=lambda bundle: True,
            persist_observation=kwargs.get("persist_observation"),
            persist_rejection=kwargs.get("persist_rejection"),
        )
        # The planning execution service uses this same loader between polls.
        assert loader() is fresh
        assert loader() is missing
        raise StopLoop

    monkeypatch.setattr(runtime, "_poll_live_cycle", exercise_loads)
    with pytest.raises(StopLoop):
        runtime.main()

    observations = HouseholdLoadHistoryStore(runtime.HOUSEHOLD_LOAD_HISTORY_PATH).load()
    assert observations == (first.household_load_observation, fresh.household_load_observation)
    assert rejected == [missing]


@pytest.mark.parametrize("has_observation", [True, False])
def test_household_recording_failure_is_reported_without_blocking_refresh(
    has_observation: bool, capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _bundle(captured_at=BASE, price=0.20)
    if not has_observation:
        bundle = replace(bundle, household_load_observation=None)

    def unavailable(value: object) -> None:
        raise OSError("storage unavailable")

    runtime._persist_household_input(
        bundle, persist_observation=unavailable, persist_rejection=unavailable,
    )
    output = capsys.readouterr().out
    expected = (
        "picot_v2_household_load_history_unavailable" if has_observation
        else "picot_v2_household_load_rejection_history_unavailable"
    )
    assert expected in output
    assert '"error":"OSError"' in output
