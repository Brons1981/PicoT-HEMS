import json
from copy import deepcopy

import pytest

from picot.v2.soc_projection_cache import SOCProjectionCache
from picot.v2.web_ui import WebViewStore


def projection():
    return {
        "captured_at": "2026-09-09T17:59:00+00:00",
        "soc_projection_captured_at": "2026-09-09T17:59:00+00:00",
        "chosen_plan": {
            "plan_id": "plan-1", "candidate_id": "candidate-1", "energy_path_id": "path-1",
            "valid_from": "2026-09-09T17:59:00+00:00",
            "valid_until": "2026-09-10T22:00:00+00:00",
        },
        "decision": {"status": "winner_selected"},
        "soc_timeline": [
            {"at": "2026-09-09T17:59:00+00:00", "soc_percent": 79, "primitive": "actual"},
            {"at": "2026-09-10T12:00:00+00:00", "soc_percent": 100,
             "primitive": "balance_bidirectional"},
        ],
    }


def retained():
    result = projection()
    result.update(captured_at="2026-09-09T19:18:00+00:00", soc_timeline=[],
                  soc_projection_captured_at=None, decision={"status": "plan_retained"})
    return result


def test_persistent_curve_survives_restart_without_changing_current_plan(tmp_path):
    path = tmp_path / "soc.json"
    first = WebViewStore(soc_cache=SOCProjectionCache(path))
    first.publish({"planning_status": projection()})
    original = path.read_bytes()
    current = retained()
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({"planning_status": current})
    shown = json.loads(web.latest_json())["planning_status"]
    assert shown["soc_timeline"] == projection()["soc_timeline"]
    assert shown["chosen_plan"] == current["chosen_plan"]
    assert shown["captured_at"] == current["captured_at"]
    assert shown["soc_projection_captured_at"] == projection()["captured_at"]
    assert shown["soc_projection_retained"] is True
    assert current["soc_timeline"] == []
    saved = json.loads(path.read_bytes())
    previous = json.loads(original)
    saved.pop("display_history")
    previous.pop("display_history")
    assert saved == previous


@pytest.mark.parametrize("changed", ["plan_id", "candidate_id", "energy_path_id", "valid_until"])
def test_wrong_identity_never_gets_saved_curve(tmp_path, changed):
    path = tmp_path / "soc.json"
    SOCProjectionCache(path).remember(projection())
    current = retained()
    current["chosen_plan"][changed] = (
        "2026-09-11T22:00:00+00:00" if changed == "valid_until" else "different"
    )
    assert SOCProjectionCache(path).restore(current) is None


def test_corruption_expiry_and_fallback_do_not_restore(tmp_path):
    path = tmp_path / "soc.json"
    path.write_text("broken")
    assert SOCProjectionCache(path).restore(retained()) is None
    SOCProjectionCache(path).remember(projection())
    expired = retained()
    expired["captured_at"] = "2026-09-11T00:00:00+00:00"
    assert SOCProjectionCache(path).restore(expired) is None
    fallback = retained()
    fallback["decision"] = {"status": "fallback_active"}
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({"planning_status": fallback})
    assert not json.loads(web.latest_json())["planning_status"]["soc_timeline"]


def test_unwritable_cache_never_blocks_web_publication(tmp_path):
    path = tmp_path / "directory"
    path.mkdir()
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({"planning_status": projection()})
    shown = json.loads(web.latest_json())["planning_status"]
    assert shown["soc_timeline"] == projection()["soc_timeline"]
    assert shown["soc_projection_cache_status"] == "cache_unavailable"


def test_history_recovers_only_exact_canonical_winner_once(tmp_path):
    status = projection()
    plan = status["chosen_plan"]
    poll = {
        "captured_at_utc": status["captured_at"], "run_id": "run-1", "snapshot_id": "snap-1",
        "evaluation": {"status": "winner_selected", "winning_candidate_id": "candidate-1",
                       "winning_energy_path_id": "path-1"},
        "execution_plan_set": {"plans": [{
            "plan_id": plan["plan_id"], "winning_candidate_id": plan["candidate_id"],
            "winning_energy_path_id": plan["energy_path_id"],
            "valid_from": plan["valid_from"], "valid_until": plan["valid_until"],
        }]},
        "candidate_set": {"energy_paths": [{
            "path_id": "path-1", "snapshot_id": "snap-1", "run_id": "run-1",
            "projected_states": [{"at": p["at"], "battery_soc": p["soc_percent"] / 100}
                                 for p in status["soc_timeline"]],
            "segments": [{"starts_at": plan["valid_from"], "ends_at": plan["valid_until"],
                          "primitive": "balance_bidirectional"}],
        }]},
    }
    history = tmp_path / "history.jsonl"
    wrong = deepcopy(poll)
    wrong["candidate_set"]["energy_paths"][0]["snapshot_id"] = "other"
    history.write_text(json.dumps({"poll": wrong}) + "\n")
    cache = SOCProjectionCache(tmp_path / "no-match.json", history_path=history)
    assert cache.restore(retained()) is None
    history.write_text(json.dumps({"poll": poll}) + "\nbroken\n")
    # No repeated history reads during regular polling.
    assert cache.restore(retained()) is None
    path = tmp_path / "soc.json"
    shown = SOCProjectionCache(path, history_path=history).restore(retained())
    assert shown["soc_timeline"] == status["soc_timeline"]
    history.unlink()
    assert SOCProjectionCache(path).restore(retained())["soc_timeline"] == status["soc_timeline"]


def test_equivalent_timezones_match_the_same_plan(tmp_path):
    path = tmp_path / "soc.json"
    SOCProjectionCache(path).remember(projection())
    current = retained()
    current["chosen_plan"]["valid_until"] = "2026-09-11T00:00:00+02:00"
    assert SOCProjectionCache(path).restore(current)["soc_timeline"] == projection()["soc_timeline"]


def test_new_forecast_preserves_elapsed_points_and_replaces_only_future(tmp_path):
    first = projection()
    first['soc_timeline'].insert(1, {
        'at': '2026-09-09T19:00:00+00:00', 'soc_percent': 60,
        'primitive': 'support_household',
    })
    path = tmp_path / 'soc.json'
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({'planning_status': first})
    current = retained()
    current['soc_timeline'] = [
        {'at': current['captured_at'], 'soc_percent': 55, 'primitive': 'actual'},
        {'at': '2026-09-10T12:00:00+00:00', 'soc_percent': 90,
         'primitive': 'balance_bidirectional'},
    ]
    current['soc_projection_captured_at'] = current['captured_at']
    original = deepcopy(current)
    web.publish({'planning_status': current})
    shown = json.loads(web.latest_json())['planning_status']
    assert current == original
    assert shown['soc_timeline'] == current['soc_timeline']
    display = shown['soc_display_timeline']
    assert [(p['at'], p['soc_percent']) for p in display[:2]] == [
        ('2026-09-09T17:59:00+00:00', 79),
        ('2026-09-09T19:00:00+00:00', 60),
    ]
    assert [(p['at'], p['soc_percent']) for p in display[-2:]] == [
        ('2026-09-09T19:18:00+00:00', 55),
        ('2026-09-10T12:00:00+00:00', 90),
    ]
    assert display[-2]['break_before'] is True
    # A different plan replaces the future without erasing the elapsed record.
    revised = deepcopy(current)
    revised['chosen_plan']['plan_id'] = 'plan-2'
    revised['decision']['status'] = 'winner_selected'
    revised['soc_timeline'][-1]['soc_percent'] = 95
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({'planning_status': revised})
    shown = json.loads(web.latest_json())['planning_status']
    assert shown['soc_display_timeline'][1] == display[1]
    assert shown['soc_display_timeline'][1]['source_identity']['plan_id'] == 'plan-1'
    assert shown['soc_display_timeline'][-1]['source_identity']['plan_id'] == 'plan-2'
    assert shown['soc_display_timeline'][-1]['soc_percent'] == 95
    assert shown['chosen_plan'] == revised['chosen_plan']


def test_fallback_keeps_history_but_never_the_old_future(tmp_path):
    web = WebViewStore(soc_cache=SOCProjectionCache(tmp_path / 'soc.json'))
    web.publish({'planning_status': projection()})
    status = retained()
    status['decision']['status'] = 'fallback_active'
    web.publish({'planning_status': status})
    display = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    assert [p['at'] for p in display] == [
        '2026-09-09T17:59:00+00:00', status['captured_at'],
    ]


def test_display_history_is_bounded_and_corruption_does_not_break_canonical_cache(tmp_path):
    path = tmp_path / 'soc.json'
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({'planning_status': projection()})
    raw = json.loads(path.read_text())
    raw['display_history'] = {'updated_at': 'broken', 'points': []}
    path.write_text(json.dumps(raw))
    cache = SOCProjectionCache(path)
    assert cache.restore(retained())['soc_timeline'] == projection()['soc_timeline']
    web = WebViewStore(soc_cache=cache)
    status = retained()
    status['captured_at'] = '2026-09-13T12:00:00+00:00'
    status['decision']['status'] = 'fallback_active'
    web.publish({'planning_status': status})
    assert json.loads(web.latest_json())['planning_status']['soc_display_timeline'] == []


def test_old_cache_migrates_elapsed_forecast_on_restart(tmp_path):
    path = tmp_path / 'soc.json'
    SOCProjectionCache(path).remember(projection())
    raw = json.loads(path.read_text())
    raw.pop('display_history')
    path.write_text(json.dumps(raw))
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({'planning_status': retained()})
    shown = json.loads(web.latest_json())['planning_status']
    assert shown['soc_display_timeline'][0]['soc_percent'] == 79
    assert shown['soc_display_timeline'][-1]['soc_percent'] == 100
    assert shown['soc_timeline'] == projection()['soc_timeline']


def _status_at(minute, soc, end_soc=60):
    status = projection()
    at = f"2026-09-09T18:{minute:02d}:00+00:00"
    status.update(captured_at=at, soc_projection_captured_at=at)
    status['soc_timeline'] = [
        {'at': at, 'soc_percent': soc, 'primitive': 'actual'},
        {'at': '2026-09-09T18:15:00+00:00', 'soc_percent': end_soc,
         'primitive': 'balance_bidirectional'},
    ]
    return status


def _drawn_soc(points, minute):
    from datetime import datetime

    at = datetime.fromisoformat(f"2026-09-09T18:{minute:02d}:00+00:00")
    for left, right in zip(points, points[1:]):
        start, end = datetime.fromisoformat(left['at']), datetime.fromisoformat(right['at'])
        if not right.get('break_before') and start <= at < end:
            return left['soc_percent'] + (right['soc_percent'] - left['soc_percent']) * (
                (at - start).total_seconds() / (end - start).total_seconds()
            )
    return None


def test_elapsed_line_geometry_survives_updates_and_restart(tmp_path):
    path = tmp_path / 'soc.json'
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    web.publish({'planning_status': _status_at(0, 50)})
    initial = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    original = deepcopy(initial)
    current = _status_at(10, 40, 50)
    web.publish({'planning_status': current})
    shown = json.loads(web.latest_json())['planning_status']
    assert abs(_drawn_soc(shown['soc_display_timeline'], 5) - (50 + 10 / 3)) < 1e-10
    assert _drawn_soc(shown['soc_display_timeline'], 11) == 42
    assert shown['soc_timeline'] == current['soc_timeline']
    assert initial == original
    # The previous current-SOC anchor is now the start of an elapsed forecast
    # stroke; dropping it would reshape that stroke on the next refresh.
    web = WebViewStore(soc_cache=SOCProjectionCache(path))
    current = _status_at(12, 35, 45)
    current['chosen_plan']['plan_id'] = 'new-plan'
    web.publish({'planning_status': current})
    shown = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    assert abs(_drawn_soc(shown, 5) - _drawn_soc(initial, 5)) < 1e-10
    assert _drawn_soc(shown, 11) == 42
    assert abs(_drawn_soc(shown, 13) - (35 + 10 / 3)) < 1e-10


def test_fallback_gap_is_not_connected_to_a_new_forecast(tmp_path):
    web = WebViewStore(soc_cache=SOCProjectionCache(tmp_path / 'soc.json'))
    web.publish({'planning_status': _status_at(0, 50)})
    fallback = _status_at(10, 40)
    fallback.update(decision={'status': 'fallback_active'}, soc_timeline=[])
    web.publish({'planning_status': fallback})
    shown = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    assert abs(_drawn_soc(shown, 5) - (50 + 10 / 3)) < 1e-10
    assert _drawn_soc(shown, 11) is None
    web.publish({'planning_status': _status_at(12, 35, 45)})
    shown = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    assert _drawn_soc(shown, 11) is None
    assert abs(_drawn_soc(shown, 13) - (35 + 10 / 3)) < 1e-10


def test_bounded_dense_display_history_survives_save_and_restart(tmp_path):
    from datetime import datetime, timedelta

    from picot.v2.soc_projection_cache import MAX_POINTS

    path = tmp_path / 'soc.json'
    cache = SOCProjectionCache(path)
    cache.remember(projection())
    start = datetime.fromisoformat('2026-09-09T17:59:00+00:00')
    identity = {key: value + '-provenance-' * 8
                for key, value in projection()['chosen_plan'].items()}
    points = [{
        'at': (start + timedelta(seconds=15 * i)).isoformat(),
        'soc_percent': 50, 'primitive': 'balance_bidirectional',
        'source_identity': identity, 'source_captured_at': start.isoformat(),
    } for i in range(MAX_POINTS)]
    cache.display_history.load({'updated_at': start.isoformat(), 'points': points})
    status = retained()
    status['captured_at'] = points[-2]['at']
    status['decision']['status'] = 'fallback_active'
    cache.display(status)
    assert cache.status == 'saved'
    restored = SOCProjectionCache(path)
    assert restored.display_history.value == cache.display_history.value
    assert len(restored.display_history.value['points']) <= MAX_POINTS
