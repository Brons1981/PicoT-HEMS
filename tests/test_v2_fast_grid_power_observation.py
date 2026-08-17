from datetime import UTC, datetime, timedelta

from picot.v2.fast_grid_power_observation import FastGridPowerObserver
from picot.v2.planning_input import SourceBinding, SourceEvidence

BASE = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)
BINDING = SourceBinding(
    category="p1",
    semantic_role="grid_power",
    entity_id="sensor.ct_shelly_pro_3em_api",
)


def _source(
    *,
    raw_state: str,
    observed_at: datetime,
) -> SourceEvidence:
    return SourceEvidence(
        evidence_id="evidence-grid-power",
        category="p1",
        semantic_role="grid_power",
        entity_id=BINDING.entity_id,
        raw_state=raw_state,
        raw_unit="W",
        observed_at=observed_at,
        availability="available",
        mapping_version="ha-state:grid_power:v1",
    )


def test_fast_observer_publishes_new_source_samples_only() -> None:
    sources = [
        _source(raw_state="8.345", observed_at=BASE),
        _source(raw_state="8.345", observed_at=BASE),
        _source(
            raw_state="8.345",
            observed_at=BASE + timedelta(seconds=1),
        ),
    ]
    published: list[dict[str, object]] = []
    observer = FastGridPowerObserver(
        binding=BINDING,
        read_source=lambda binding: sources.pop(0),
        publish=published.append,
    )

    assert observer.poll_once(polled_at=BASE) is True
    assert observer.poll_once(
        polled_at=BASE + timedelta(seconds=1)
    ) is False
    assert observer.poll_once(
        polled_at=BASE + timedelta(seconds=2)
    ) is True

    assert sources == []
    assert len(published) == 2
    assert published[0]["raw_state"] == "8.345"
    assert published[0]["raw_unit"] == "W"
    assert published[0]["observed_at"] == BASE.isoformat()
    assert published[0]["fast_observer_polled_at"] == BASE.isoformat()
    assert published[1]["observed_at"] == (
        BASE + timedelta(seconds=1)
    ).isoformat()


def test_fast_observer_does_not_treat_poll_time_as_physical_sample() -> None:
    source = _source(raw_state="8345", observed_at=BASE)
    published: list[dict[str, object]] = []
    observer = FastGridPowerObserver(
        binding=BINDING,
        read_source=lambda binding: source,
        publish=published.append,
    )

    assert observer.poll_once(polled_at=BASE) is True
    assert observer.poll_once(
        polled_at=BASE + timedelta(seconds=10)
    ) is False
    assert len(published) == 1
