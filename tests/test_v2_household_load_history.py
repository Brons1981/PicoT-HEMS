from datetime import UTC, datetime
from pathlib import Path

from picot.v2.household_load_history import HouseholdLoadHistoryStore

from picot.v2.planning_input import HouseholdLoadObservation

BASE = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)


def observation() -> HouseholdLoadObservation:
    return HouseholdLoadObservation(
        power_w=900.0,
        sampled_at=BASE,
        evidence_ids=(
            "evidence-grid",
            "evidence-pv",
            "evidence-storage-signed",
            "evidence-storage-to-house",
            "evidence-storage-from-house",
        ),
        method_version="complete-power-balance:v1",
    )


def test_household_load_observation_survives_store_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "household-load-history.jsonl"
    expected = observation()

    HouseholdLoadHistoryStore(path).append(expected)

    restored = HouseholdLoadHistoryStore(path).load()

    assert restored == (expected,)


def test_corrupt_history_does_not_block_valid_observations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "household-load-history.jsonl"
    path.write_text("{not-valid-json}\n", encoding="utf-8")

    store = HouseholdLoadHistoryStore(path)

    assert store.load() == ()

    expected = observation()
    store.append(expected)

    restored = HouseholdLoadHistoryStore(path).load()

    assert restored == (expected,)
