"""Generic near-live grid-power observation outside the Planner cadence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from picot.v2.planning_input import SourceBinding, SourceEvidence


@dataclass(frozen=True, slots=True)
class FastGridPowerObservation:
    """One source-backed grid-power observation for runtime consumers."""

    source: SourceEvidence
    polled_at: datetime

    def __post_init__(self) -> None:
        if self.polled_at.tzinfo is None or self.polled_at.utcoffset() is None:
            raise ValueError("polled_at must be timezone-aware")
        if self.source.semantic_role != "grid_power":
            raise ValueError("source must have the grid_power semantic role")

    def source_projection(self) -> dict[str, object]:
        """Project the raw source without inventing a new physical sample."""
        return {
            "evidence_id": self.source.evidence_id,
            "category": self.source.category,
            "semantic_role": self.source.semantic_role,
            "entity_id": self.source.entity_id,
            "raw_state": self.source.raw_state,
            "raw_unit": self.source.raw_unit,
            "observed_at": (
                self.source.observed_at.isoformat()
                if self.source.observed_at is not None
                else None
            ),
            "availability": self.source.availability,
            "mapping_version": self.source.mapping_version,
            "error": self.source.error,
            "fast_observer_polled_at": self.polled_at.isoformat(),
        }


class FastGridPowerObserver:
    """Publish only genuinely changed HA grid-power source evidence."""

    def __init__(
        self,
        *,
        binding: SourceBinding,
        read_source: Callable[[SourceBinding], SourceEvidence],
        publish: Callable[[dict[str, object]], None],
    ) -> None:
        if binding.semantic_role != "grid_power":
            raise ValueError("binding must have the grid_power semantic role")
        self._binding = binding
        self._read_source = read_source
        self._publish = publish
        self._last_signature: tuple[object, ...] | None = None

    def poll_once(self, *, polled_at: datetime) -> bool:
        """Read once and publish only a new source sample or source state."""
        source = self._read_source(self._binding)
        observation = FastGridPowerObservation(
            source=source,
            polled_at=polled_at,
        )
        signature = (
            source.entity_id,
            source.raw_state,
            source.raw_unit,
            source.observed_at,
            source.availability,
            source.error,
            source.mapping_version,
        )
        if signature == self._last_signature:
            return False
        self._last_signature = signature
        self._publish(observation.source_projection())
        return True
