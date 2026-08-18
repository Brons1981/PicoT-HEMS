import pytest

import picot.v2.live_runtime as live_runtime
from picot.v2.web_ui import WebViewStore


def test_start_web_server_uses_ingress_binding_and_daemon_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    created: dict[str, object] = {}

    class FakeServer:
        def serve_forever(self) -> None:
            events.append("serve")

    class FakeThread:
        def __init__(
            self,
            *,
            target: object,
            name: str,
            daemon: bool,
        ) -> None:
            created["target"] = target
            created["name"] = name
            created["daemon"] = daemon

        def start(self) -> None:
            events.append("start")
            target = created["target"]
            assert callable(target)
            target()

    server = FakeServer()
    store = WebViewStore()

    def fake_create_web_server(
        current_store: WebViewStore,
        *,
        host: str,
        port: int,
    ) -> FakeServer:
        assert current_store is store
        assert host == "0.0.0.0"
        assert port == 8099
        return server

    monkeypatch.setattr(
        live_runtime,
        "create_web_server",
        fake_create_web_server,
    )
    monkeypatch.setattr(live_runtime, "Thread", FakeThread)

    returned_server, returned_thread = live_runtime._start_web_server(store)

    assert returned_server is server
    assert isinstance(returned_thread, FakeThread)
    assert created["name"] == "picot-v2-web-ui"
    assert created["daemon"] is True
    assert events == ["start", "serve"]


def test_main_starts_one_web_server_before_pipeline_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopLoop(Exception):
        pass

    events: list[str] = []
    stores: list[WebViewStore] = []

    def fake_start(store: WebViewStore) -> tuple[object, object]:
        events.append("start")
        stores.append(store)
        return object(), object()

    def stop_poll(**kwargs: object) -> str:
        events.append("poll")
        raise StopLoop

    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(
        live_runtime,
        "load_options",
        lambda: {
            "price_low_margin_eur_per_kwh": 0.02,
            "price_high_margin_eur_per_kwh": 0.02,
            "live_poll_interval_seconds": 60.0,
            "pv_power_entity": "sensor.test_pv",
        },
    )
    monkeypatch.setattr(live_runtime, "_start_web_server", fake_start)
    monkeypatch.setattr(live_runtime, "_poll_live_cycle", stop_poll)

    with pytest.raises(StopLoop):
        live_runtime.main()

    assert events == ["start", "poll"]
    assert len(stores) == 1
    assert [path.name for path in stores[0].diagnostic_paths()] == [
        "picot_v2_planning_incident_history.jsonl",
        "picot_v2_household_load_history.jsonl",
        "picot_v2_pv_forecast_basis.jsonl",
        "picot_v2_pv_attenuation_evidence.jsonl",
        "picot_v2_storage_mode_provenance.json",
        "picot_v2_storage_mode_transition_history.jsonl",
    ]
    assert stores[0].incident_history_path() == (
        live_runtime.PLANNING_INCIDENT_HISTORY_PATH
    )
