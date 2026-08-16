import json
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_v2_delegated_storage_pipeline_integration import BASE, _snapshot

from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.web_ui import WebViewStore, build_web_view, create_web_server


def _web_ui_module() -> object:
    return import_module("picot.v2.web_ui")


def test_every_pipeline_card_exposes_plain_dutch_result() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    view = build_web_view(run, project(run))

    pipeline = view["pipeline"]
    assert len(pipeline) == 9
    assert all(
        isinstance(item["result_nl"], str)
        and item["result_nl"].strip()
        and "_" not in item["result_nl"]
        for item in pipeline
    )


@pytest.mark.parametrize(
    ("stage", "state", "attributes", "expected"),
    (
        (
            1,
            "ready",
            {},
            "De planningsgegevens zijn compleet en klaar voor beoordeling.",
        ),
        (
            2,
            "detected",
            {"opportunity_count": 3},
            "Er zijn 3 mogelijke energiekansen gevonden.",
        ),
        (
            3,
            "constructed",
            {"candidate_count": 2},
            "Er zijn 2 mogelijke plannen opgebouwd.",
        ),
        (
            4,
            "evaluated",
            {"winning_candidate_id": "reserve-first"},
            "Het beste plan is reserve-first.",
        ),
        (
            5,
            "constructed",
            {"execution_plan_count": 1},
            "Er is 1 uitvoeringsplan voorbereid.",
        ),
        (
            6,
            "observer_only",
            {},
            "Uitvoering is niet gestart; PicoT kijkt alleen mee.",
        ),
        (
            7,
            "blocked",
            {"blockers": ["manual_override_active"]},
            "Uitvoering is geblokkeerd omdat een handmatige instelling actief is.",
        ),
        (
            8,
            "not_invoked",
            {},
            "De apparaatkoppeling is niet aangeroepen.",
        ),
        (
            9,
            "not_attempted",
            {},
            "Er is geen opdracht naar Zendure verstuurd.",
        ),
    ),
)
def test_pipeline_result_translation_is_explicit_and_deterministic(
    stage: int,
    state: str,
    attributes: dict[str, object],
    expected: str,
) -> None:
    module = _web_ui_module()

    result = module.pipeline_result_nl(
        stage=stage,
        state=state,
        attributes=attributes,
    )

    assert result == expected


def test_pipeline_cards_are_compact_collapsible_and_preserve_open_state() -> None:
    html = _web_ui_module().DASHBOARD_HTML

    assert 'details.className = "stage-card"' in html
    assert 'summary.className = "stage-summary"' in html
    assert 'result.className = "stage-result"' in html
    assert "result.textContent = item.result_nl" in html
    assert 'document.querySelectorAll("details.stage-card")' in html
    assert "details.open = state.openStageCards[index] ?? false" in html
    assert 'const card = document.createElement("article")' not in (
        html[
            html.index("function renderPipeline") :
            html.index("function renderStorageEnergySourceNeeds")
        ]
    )


def test_reset_button_is_only_shown_for_active_manual_override() -> None:
    html = _web_ui_module().DASHBOARD_HTML

    assert 'id="storage-mode-override"' in html
    assert 'id="reset-storage-mode-override"' in html
    assert "manual_override_active === true" in html
    assert "resetButton.hidden = !manualOverrideActive" in html
    assert 'fetch("api/storage-mode-override/reset"' in html
    assert 'method: "POST"' in html
    assert 'typeof globalThis.crypto.randomUUID === "function"' in html
    assert "return globalThis.crypto.randomUUID()" in html
    assert 'typeof globalThis.crypto.getRandomValues === "function"' in html
    assert "Math.random()" in html
    assert "reset_id: storageModeResetId()" in html
    assert "reset_id: crypto.randomUUID()" not in html


def test_reset_endpoint_accepts_only_explicit_reset_request() -> None:
    calls: list[str] = []

    def reset(reset_id: str) -> dict[str, object]:
        calls.append(reset_id)
        return {
            "status": "released",
            "reset_id": reset_id,
            "manual_override_active": False,
        }

    server = create_web_server(
        WebViewStore(),
        host="127.0.0.1",
        port=0,
        reset_storage_mode_override=reset,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        request = Request(
            base_url + "/api/storage-mode-override/reset",
            data=json.dumps({"reset_id": "reset-dashboard-1"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())

        assert response.status == 200
        assert payload == {
            "status": "released",
            "reset_id": "reset-dashboard-1",
            "manual_override_active": False,
        }
        assert calls == ["reset-dashboard-1"]

        invalid = Request(
            base_url + "/api/storage-mode-override/reset",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(invalid, timeout=2)
        assert rejected.value.code == 400
        assert json.loads(rejected.value.read()) == {
            "status": "invalid_reset_request"
        }
        rejected.value.close()
        assert calls == ["reset-dashboard-1"]

        forbidden = Request(
            base_url + "/api/view",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as rejected_write:
            urlopen(forbidden, timeout=2)
        assert rejected_write.value.code == 405
        rejected_write.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_reset_endpoint_fails_closed_when_reset_is_rejected() -> None:
    def reject_reset(reset_id: str) -> dict[str, object]:
        raise ValueError(f"reset rejected: {reset_id}")

    server = create_web_server(
        WebViewStore(),
        host="127.0.0.1",
        port=0,
        reset_storage_mode_override=reject_reset,
    )
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        request = Request(
            (
                f"http://127.0.0.1:{server.server_port}"
                "/api/storage-mode-override/reset"
            ),
            data=json.dumps({"reset_id": "duplicate-reset"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as rejected:
            urlopen(request, timeout=2)

        assert rejected.value.code == 409
        assert json.loads(rejected.value.read()) == {
            "status": "reset_rejected"
        }
        rejected.value.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_persisted_runtime_rejects_duplicate_or_stale_reset(
    tmp_path: Path,
) -> None:
    module = import_module("picot.v2.live_storage_mode_provenance")
    runtime = module.LiveStorageModeProvenanceRuntime(
        module.StorageModeProvenanceStore(tmp_path / "provenance.json")
    )
    runtime.observe_vendor_mode("Standby", observed_at=BASE)
    runtime.record_planner_application(
        "Alleen slim opladen",
        applied_at=BASE + timedelta(seconds=1),
        application_id="application-dashboard-reset",
    )
    runtime.observe_vendor_mode(
        "Standby",
        observed_at=BASE + timedelta(seconds=2),
    )
    runtime.reset_current_manual_override(
        reset_at=BASE + timedelta(seconds=3),
        reset_id="reset-dashboard-once",
    )

    with pytest.raises(ValueError, match="no manual override is active"):
        runtime.reset_current_manual_override(
            reset_at=BASE + timedelta(seconds=4),
            reset_id="reset-dashboard-stale",
        )
