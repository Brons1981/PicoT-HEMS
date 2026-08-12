"""ADR-039 actual-PV energy integration from PicoT-owned GoodWe evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.addon.history_store import HistoryStore
from picot.domain.pv_energy_timeline import PVEnergyEvidenceType, PVEnergyTimelineInterval

ACTUAL_PV_METHOD_VERSION = "goodwe-sample-hold-quarter-energy-v1"


@dataclass(frozen=True, slots=True)
class ActualPVSample:
    observed_at: datetime
    power_w: float


def _quarter_start(moment: datetime) -> datetime:
    return moment.replace(minute=(moment.minute // 15) * 15, second=0, microsecond=0)


def _sample_from_event(event: dict[str, object]) -> ActualPVSample | None:
    if event.get("status") != "available":
        return None
    raw_time = event.get("observed_at")
    raw_power = event.get("solar_power_w")
    if (
        not isinstance(raw_time, str)
        or isinstance(raw_power, bool)
        or not isinstance(raw_power, (int, float))
    ):
        return None
    observed_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return None
    return ActualPVSample(observed_at=observed_at, power_w=max(0.0, float(raw_power)))


def _current_sample(event: dict[str, object], captured_at: datetime) -> ActualPVSample | None:
    if event.get("goodwe_status") != "available":
        return None
    raw_power = event.get("goodwe_solar_power_w")
    if isinstance(raw_power, bool) or not isinstance(raw_power, (int, float)):
        return None
    return ActualPVSample(observed_at=captured_at, power_w=max(0.0, float(raw_power)))


def actual_pv_interval_from_history(
    *,
    history: HistoryStore,
    event: dict[str, object],
    captured_at: datetime,
    sequence: int,
) -> PVEnergyTimelineInterval | None:
    """Integrate reliable current-quarter PV samples using versioned sample-and-hold.

    The integration is deliberately fail-closed. A sample at/before the quarter
    boundary is required and no gap may exceed three telemetry periods (with a
    30-second minimum tolerance). Long source outages are never interpolated.
    """

    starts_at = _quarter_start(captured_at)
    if starts_at == captured_at:
        return None

    raw_interval = event.get("telemetry_interval_seconds", 5)
    cadence_s = (
        int(raw_interval)
        if isinstance(raw_interval, int) and not isinstance(raw_interval, bool) and raw_interval > 0
        else 5
    )
    max_gap_s = max(30, cadence_s * 3)
    lookup_start = starts_at - timedelta(seconds=max_gap_s)

    samples: list[ActualPVSample] = []
    for record in history.iter_range(lookup_start, captured_at):
        if record.get("event") != "picot_goodwe_snapshot":
            continue
        sample = _sample_from_event(record)
        if sample is not None:
            samples.append(sample)
    current = _current_sample(event, captured_at)
    if current is not None:
        samples.append(current)
    if not samples:
        return None

    samples.sort(key=lambda sample: sample.observed_at)
    deduplicated: list[ActualPVSample] = []
    for sample in samples:
        if deduplicated and deduplicated[-1].observed_at == sample.observed_at:
            deduplicated[-1] = sample
        else:
            deduplicated.append(sample)

    anchor_index: int | None = None
    for index, sample in enumerate(deduplicated):
        if sample.observed_at <= starts_at:
            anchor_index = index
        else:
            break
    if anchor_index is None:
        return None
    anchor = deduplicated[anchor_index]
    if (starts_at - anchor.observed_at).total_seconds() > max_gap_s:
        return None

    relevant = [anchor, *deduplicated[anchor_index + 1 :]]
    if relevant[-1].observed_at < captured_at:
        return None
    previous_time = starts_at
    previous_power = anchor.power_w
    energy_wh = 0.0
    evidence_ids: list[str] = []
    for sample in relevant[1:]:
        sample_time = min(sample.observed_at, captured_at)
        if sample_time < previous_time:
            continue
        gap_s = (sample_time - previous_time).total_seconds()
        if gap_s > max_gap_s:
            return None
        energy_wh += previous_power * gap_s / 3600.0
        previous_time = sample_time
        previous_power = sample.power_w
        evidence_ids.append(f"goodwe-pv:{sample.observed_at.isoformat()}")
        if sample_time == captured_at:
            break
    if previous_time != captured_at:
        return None

    return PVEnergyTimelineInterval(
        starts_at=starts_at,
        ends_at=captured_at,
        energy_wh=energy_wh,
        evidence_type=PVEnergyEvidenceType.ACTUAL,
        confidence=1.0,
        evidence_ids=tuple(evidence_ids or (f"goodwe-pv:{sequence}",)),
        method_version=ACTUAL_PV_METHOD_VERSION,
    )
