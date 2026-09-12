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
    assert path.read_bytes() == original


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
    assert [(p['at'], p['soc_percent']) for p in display] == [
        ('2026-09-09T17:59:00+00:00', 79),
        ('2026-09-09T19:00:00+00:00', 60),
        ('2026-09-09T19:18:00+00:00', 55),
        ('2026-09-10T12:00:00+00:00', 90),
    ]
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
    assert [p['at'] for p in display] == ['2026-09-09T17:59:00+00:00']


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
    assert [(p['at'], p['soc_percent']) for p in shown['soc_display_timeline']] == [
        (p['at'], p['soc_percent']) for p in projection()['soc_timeline']
    ]


def test_repeated_updates_freeze_forecast_not_previous_measured_start(tmp_path):
    web = WebViewStore(soc_cache=SOCProjectionCache(tmp_path / 'soc.json'))
    first = projection()
    first['soc_timeline'].insert(1, {
        'at': '2026-09-09T19:00:00+00:00', 'soc_percent': 60,
        'primitive': 'support_household',
    })
    web.publish({'planning_status': first})
    for minute in ['18', '19', '20']:
        current = retained()
        current['captured_at'] = f'2026-09-09T19:{minute}:00+00:00'
        current['soc_projection_captured_at'] = current['captured_at']
        current['soc_timeline'] = [
            {'at': current['captured_at'], 'soc_percent': 55, 'primitive': 'actual'},
            first['soc_timeline'][-1],
        ]
        web.publish({'planning_status': current})
    shown = json.loads(web.latest_json())['planning_status']['soc_display_timeline']
    assert [p['at'] for p in shown] == [
        '2026-09-09T17:59:00+00:00', '2026-09-09T19:00:00+00:00',
        '2026-09-09T19:20:00+00:00', '2026-09-10T12:00:00+00:00',
    ]
