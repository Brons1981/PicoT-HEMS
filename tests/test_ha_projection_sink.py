"""Recorder-sized HA transport without losing canonical dashboard detail."""

import json
from copy import deepcopy
from unittest.mock import MagicMock, patch

from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.projection import Card


def _published(card: Card) -> dict[str, object]:
    response = MagicMock()
    with patch("picot.v2.ha_projection_sink.urlopen", return_value=response) as request:
        HomeAssistantProjectionSink("test-token").publish(card)
    return json.loads(request.call_args.args[0].data)


def test_small_attributes_are_unchanged() -> None:
    attributes = {"status": "ready", "count": 3, "labels": ["zon", "huis"]}
    card = Card("sensor.picot_v2_pipeline_01_planning_input", "ready", attributes)
    assert _published(card) == {"state": "ready", "attributes": attributes}


def test_large_timeline_is_summarized_only_on_ha_transport() -> None:
    attributes = {
        "status": "ready",
        "captured_at": "2026-09-13T13:46:00+00:00",
        "pv_intervals": [{"time": index, "energy_wh": 350} for index in range(1000)],
        "small_details": {"available": True},
    }
    original = deepcopy(attributes)
    card = Card("sensor.picot_v2_pipeline_01_planning_input", "ready", attributes)
    sent = _published(card)["attributes"]
    assert isinstance(sent, dict)
    assert len(json.dumps(sent).encode("utf-8")) < 16_384
    assert sent["status"] == "ready"
    assert sent["captured_at"] == attributes["captured_at"]
    assert sent["small_details"] == {"available": True}
    assert "pv_intervals" not in sent
    assert sent["_picot_ha_summary"]["omitted_fields"] == [
        {"field": "pv_intervals", "item_count": 1000}
    ]
    assert card.attributes == original


def test_unicode_and_omission_metadata_also_fit_recorder_budget() -> None:
    attributes: dict[str, object] = {
        f"{index}-" + "🌞" * 100: "🌞" * 500 for index in range(100)
    }
    attributes["status"] = "ready"
    sent = _published(Card("sensor.test", "ready", attributes))["attributes"]
    assert isinstance(sent, dict)
    assert len(json.dumps(sent).encode("utf-8")) < 16_384
    assert len(json.dumps(sent, ensure_ascii=False).encode("utf-8")) < 16_384
    assert sent["status"] == "ready"
    summary = sent["_picot_ha_summary"]
    assert summary["omitted_field_count"] > len(summary["omitted_fields"])
    assert len(attributes) == 101


def test_compaction_covers_multiple_large_fields() -> None:
    attributes = {"a": "a" * 20_000, "b": list(range(5000)), "status": "ready"}
    sent = _published(Card("sensor.test", "ready", attributes))["attributes"]
    assert isinstance(sent, dict)
    assert len(json.dumps(sent).encode("utf-8")) < 16_384
    assert sent["_picot_ha_summary"]["omitted_field_count"] == 2
    assert sent["status"] == "ready"
