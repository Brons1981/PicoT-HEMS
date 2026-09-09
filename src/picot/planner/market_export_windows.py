"""Exact constant-battery-power export windows with household power priority.

These are unranked physical timing alternatives, not admissions or plans.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True, slots=True)
class ExportCapacityPart:
    starts_at: datetime
    ends_at: datetime
    export_power_w: float

    def __post_init__(self) -> None:
        if (
            self.starts_at.utcoffset() is None
            or self.ends_at.utcoffset() is None
            or self.ends_at <= self.starts_at
            or not isfinite(self.export_power_w)
            or self.export_power_w < 0
        ):
            raise ValueError("export capacity needs aware positive duration and finite power")

    @property
    def energy_wh(self) -> float:
        return self.export_power_w * (self.ends_at - self.starts_at).total_seconds() / 3600


def export_windows(
    parts: tuple[ExportCapacityPart, ...],
    target_wh: float,
) -> tuple[tuple[ExportCapacityPart, ...], ...]:
    """Include windows touching either end of every available capacity step.

    A gap is a protected action and cannot be crossed. Zero spare power cannot
    support an uninterrupted export window. SOC is assessed by the shared
    simulator later; this helper never invents available battery energy.
    """
    if not isfinite(target_wh) or target_wh <= 0:
        raise ValueError("export allocation must be finite and positive")
    blocks: list[list[ExportCapacityPart]] = []
    for part in parts:
        if part.export_power_w == 0:
            continue
        if not blocks or blocks[-1][-1].ends_at != part.starts_at:
            blocks.append([])
        blocks[-1].append(part)
    windows = []
    for block in blocks:
        starts = {p.starts_at for p in block}
        for end_index in range(len(block)):
            remaining = target_wh
            for p in reversed(block[: end_index + 1]):
                if remaining <= p.energy_wh + 1e-6:
                    starts.add(p.ends_at - timedelta(hours=remaining / p.export_power_w))
                    break
                remaining -= p.energy_wh
        for start in sorted(starts):
            remaining = target_wh
            allocation = []
            for p in block:
                left = max(start, p.starts_at)
                if left >= p.ends_at:
                    continue
                available = p.export_power_w * (p.ends_at - left).total_seconds() / 3600
                amount = min(remaining, available)
                right = (
                    p.ends_at
                    if amount == available
                    else (left + timedelta(hours=amount / p.export_power_w))
                )
                allocation.append(ExportCapacityPart(left, right, p.export_power_w))
                remaining -= amount
                if remaining <= 1e-6:
                    windows.append(tuple(allocation))
                    break
    return tuple(windows)
