import json

import pytest

from picot.v2.startup_progress import StartupProgress


def test_milestones_do_not_fake_time_based_progress_and_finish_once(capsys):
    now = [10.0]
    progress = StartupProgress(clock=lambda: now[0])
    progress.enter("input", "Gegevens ophalen", 15)
    now[0] = 130.0
    assert progress.snapshot()["percent"] == 15
    assert progress.snapshot()["phase_elapsed_seconds"] == 120
    progress.enter("planning", "Planning berekenen", 55)
    now[0] = 140.0
    progress.complete()
    progress.enter("input", "Gegevens ophalen", 15)
    progress.fail()
    now[0] = 999.0
    assert progress.snapshot()["state"] == "ready"
    assert progress.snapshot()["percent"] == 100
    assert progress.snapshot()["elapsed_seconds"] == 130
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["duration_ms"] for row in logs] == [0, 120000, 10000]


def test_nested_checkpoints_restore_phase_and_do_not_move_bar_backwards():
    progress = StartupProgress()
    progress.enter("planning", "Planning berekenen", 55)
    with progress.stage("input", "Actuele gegevens ophalen", 15):
        assert progress.snapshot()["phase"] == "input"
        assert progress.snapshot()["percent"] == 55
    assert progress.snapshot()["phase"] == "planning"
    assert progress.snapshot()["percent"] == 55


def test_failed_phase_preserves_failure_and_can_retry():
    progress = StartupProgress()
    with pytest.raises(ValueError), progress.stage("input", "Gegevens ophalen", 15):
        raise ValueError("test")
    assert progress.snapshot()["state"] == "failed"
    assert progress.snapshot()["phase"] == "input"
    progress.enter("input", "Gegevens ophalen", 15)
    assert progress.snapshot()["state"] == "starting"
