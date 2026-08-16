from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from test_v2_delegated_storage_pipeline_integration import BASE, _snapshot

from picot.v2.live_pv_canary_runtime import (
    LivePVCanaryResult,
    LivePVRuntimeEvidence,
    build_live_pv_mode_input,
    live_pv_runtime_evidence,
    project_live_pv_canary_result,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.web_ui import pipeline_result_nl


def test_runtime_input_combines_winning_plan_and_fresh_live_evidence() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())
    evidence = LivePVRuntimeEvidence(
        current_vendor_mode="Alleen slim ontladen",
        battery_power_w=240.0,
        observed_at=BASE - timedelta(seconds=5),
        manual_override_active=False,
    )

    value = build_live_pv_mode_input(
        run,
        evidence=evidence,
        at=BASE,
        live_enabled=True,
    )

    assert value.charge_window_active is True
    assert value.current_vendor_mode == "Alleen slim ontladen"
    assert value.battery_power_w == 240.0
    assert value.evidence_age_seconds == 5.0
    assert value.manual_override_active is False
    assert value.live_enabled is True


def test_stale_runtime_evidence_is_preserved_for_fail_closed_strategy() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())
    evidence = LivePVRuntimeEvidence(
        current_vendor_mode="Alleen slim ontladen",
        battery_power_w=0.0,
        observed_at=BASE - timedelta(seconds=61),
        manual_override_active=False,
    )

    value = build_live_pv_mode_input(
        run,
        evidence=evidence,
        at=BASE,
        live_enabled=True,
    )

    assert value.evidence_age_seconds == 61.0


def test_successful_live_read_uses_sample_time_not_unchanged_state_time() -> None:
    source_observed_at = BASE - timedelta(hours=2)
    provenance = SimpleNamespace(
        observed_vendor_mode="Nul op de meter",
        observed_at=BASE,
        manual_override_active=False,
    )
    power_fact = SimpleNamespace(
        semantic_role="storage_power_signed",
        availability="available",
        value=0.0,
        observed_at=source_observed_at,
    )
    bundle = SimpleNamespace(
        snapshot=SimpleNamespace(storage_mode_control_provenance=provenance),
        facts=(power_fact,),
    )

    evidence = live_pv_runtime_evidence(bundle, sampled_at=BASE)

    assert evidence is not None
    assert evidence.observed_at == BASE
    assert power_fact.observed_at == source_observed_at


def test_canary_result_projects_normal_dutch_dashboard_card() -> None:
    result = LivePVCanaryResult(
        status="dispatched",
        requested_vendor_mode="Nul op de meter",
        reason="favourable_pv_charge_window_started",
        normal_result=(
            "PicoT heeft Zendure naar Nul op de meter geschakeld "
            "voor het actieve PV-laadvenster."
        ),
    )

    card = project_live_pv_canary_result(
        result,
        captured_at=datetime(2026, 8, 16, 14, 0, tzinfo=UTC),
        live_enabled=True,
    )

    assert card.entity_id == "sensor.picot_v2_live_pv_canary"
    assert card.state == "dispatched"
    assert card.attributes["normal_result"] == result.normal_result
    assert card.attributes["requested_vendor_mode"] == "Nul op de meter"
    assert card.attributes["control_change_allowed"] is True
    assert card.attributes["observer_only"] is False


def test_observer_projection_never_claims_control_authority() -> None:
    result = LivePVCanaryResult(
        status="observer_only",
        requested_vendor_mode="Nul op de meter",
        reason="favourable_pv_charge_window_started",
        normal_result="PicoT zou Zendure naar Nul op de meter schakelen.",
    )

    card = project_live_pv_canary_result(
        result,
        captured_at=BASE,
        live_enabled=False,
    )

    assert card.attributes["control_change_allowed"] is False
    assert card.attributes["observer_only"] is True


def test_live_canary_pipeline_card_uses_normal_dutch_result() -> None:
    result = pipeline_result_nl(
        stage=10,
        state="dispatched",
        attributes={"normal_result": "Zendure is naar NOM geschakeld."},
    )

    assert result == "Zendure is naar NOM geschakeld."
