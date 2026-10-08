"""Measured external demand and its explicitly delegated storage policy."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class ExternalLoadPolicy:
    source_id: str
    revision: str
    measured_at: datetime
    power_w: float
    storage_support_allowed: bool
    execution_scope_id: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.revision or not self.execution_scope_id:
            raise ValueError("external load policy requires provenance and scope")
        if self.measured_at.tzinfo is None or not isfinite(self.power_w) or self.power_w < 0:
            raise ValueError("external load policy requires dated finite demand")
