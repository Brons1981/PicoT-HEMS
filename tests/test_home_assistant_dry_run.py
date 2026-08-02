from __future__ import annotations

from datetime import UTC, datetime

from picot.adapters.home_assistant_dry_run import (
    build_zendure_manual_power_dry_run,
)
from picot.domain.home_assistant import (
    HomeAssistantDispatchMode,
    HomeAssistantDispatchStatus,
)

NOW = datetime(2026, 8, 2, 8, 4, tzinfo=UTC)


def test_first_capability_dry_run_is_exact_and_network_free() -> None:
    preview = build_zendure_manual_power_dry_run(
        base_url="http://192.168.6.26:8123/",
        requested_power_w=1200.0,
        created_at=NOW,
    )

    assert preview.endpoint == (
        "http://192.168.6.26:8123/api/services/input_number/set_value"
    )
    assert preview.payload_json == (
        '{"entity_id":"input_number.zendure_2400_ac_handmatig_vermogen",'
        '"value":1200.0}'
    )
    assert preview.service_call.dispatch_mode is HomeAssistantDispatchMode.DRY_RUN
    assert preview.dispatch_result.status is HomeAssistantDispatchStatus.DRY_RUN_ONLY
    assert preview.dispatch_result.response_status is None


def test_first_capability_dry_run_rejects_power_above_mapping_limit() -> None:
    try:
        build_zendure_manual_power_dry_run(
            base_url="http://192.168.6.26:8123",
            requested_power_w=2500.0,
            created_at=NOW,
        )
    except ValueError as error:
        assert "maximum" in str(error)
    else:
        raise AssertionError("Expected dry-run power limit validation to fail.")
