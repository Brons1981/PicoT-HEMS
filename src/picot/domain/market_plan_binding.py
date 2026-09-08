"""Market ownership in a shared canonical plan; never charge completion evidence."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class MarketPlanBinding:
    assignment_id: str
    execution_scope_id: str
    plan_id: str
    snapshot_id: str
    segment_ids: tuple[str, ...]
    expected_export_wh: float
    segment_export_wh: tuple[float, ...]

    def __post_init__(self) -> None:
        if not all(v.strip() for v in (
            self.assignment_id, self.execution_scope_id, self.plan_id, self.snapshot_id,
        )):
            raise ValueError("market binding requires explicit lineage")
        if (not self.segment_ids or any(not s.strip() for s in self.segment_ids)
                or len(set(self.segment_ids)) != len(self.segment_ids)):
            raise ValueError("market binding requires unique execution segments")
        if not isfinite(self.expected_export_wh) or self.expected_export_wh <= 0:
            raise ValueError("market binding requires positive expected export")
        if (len(self.segment_export_wh) != len(self.segment_ids)
                or any(not isfinite(v) or v <= 0 for v in self.segment_export_wh)
                or abs(sum(self.segment_export_wh) - self.expected_export_wh) > 1e-6):
            raise ValueError("market segment energy must cover the complete export allocation")
