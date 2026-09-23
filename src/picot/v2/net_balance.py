"""Independent input evidence for missing-PV grid reviews (ADR-037.17).

This observer derives facts only. It never supplies PV actuals or selects intent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from picot.v2.contracts import PlanningInputSnapshot
    from picot.v2.planning_input import PlanningInputBundle, SourceEvidence

WINDOW = timedelta(minutes=5)
MAX_AGE = timedelta(seconds=180)
MAX_SKEW = timedelta(seconds=60)
MIN_SURPLUS_W = 250.0
POWER_ROLES = (
    "grid_power", "storage_power_signed", "storage_power_to_house", "storage_power_from_house",
)


@dataclass(frozen=True, slots=True)
class NetBalanceSample:
    sampled_at: datetime
    grid_power_w: float
    storage_power_w: float
    current_soc: float
    evidence_ids: tuple[str, ...]
    source_times: tuple[datetime, ...]

    @property
    def surplus_w(self) -> float:
        return self.storage_power_w - self.grid_power_w


@dataclass(frozen=True, slots=True)
class NetBalanceSurplus:
    evidence_id: str
    snapshot_id: str
    execution_scope_id: str
    assessed_at: datetime
    episode_started_at: datetime
    current_soc: float
    usable_capacity_wh: float
    minimum_surplus_w: float
    samples: tuple[NetBalanceSample, ...]

    def __post_init__(self) -> None:
        if (not all((self.evidence_id, self.snapshot_id, self.execution_scope_id))
                or len(self.samples) < 3
                or any(t.utcoffset() is None for t in (
                    self.assessed_at, self.episode_started_at,
                    *(s.sampled_at for s in self.samples),
                ))):
            raise ValueError("Net proof requires identity and aware continuous samples")
        if (not self.episode_started_at <= self.samples[0].sampled_at <= self.assessed_at - WINDOW
                or self.samples[-1].sampled_at != self.assessed_at
                or not isfinite(self.usable_capacity_wh) or self.usable_capacity_wh <= 0
                or self.current_soc != self.samples[-1].current_soc
                or any(not isfinite(s.surplus_w) or s.surplus_w < MIN_SURPLUS_W
                       or not 0 <= s.current_soc <= 1 or not s.evidence_ids for s in self.samples)
                or self.minimum_surplus_w != min(s.surplus_w for s in self.samples)
                or any(not timedelta(0) < b.sampled_at - a.sampled_at <= MAX_AGE
                       or b.current_soc < a.current_soc
                       for a, b in zip(self.samples, self.samples[1:], strict=False))):
            raise ValueError("Net proof requires five minutes of supported nondecreasing surplus")

    def matches(self, snapshot: PlanningInputSnapshot, scope: str) -> bool:
        return (
            self.snapshot_id == snapshot.snapshot_id and self.assessed_at == snapshot.captured_at
            and self.execution_scope_id == scope and len(self.samples) >= 3
            and self.samples[-1].sampled_at == self.assessed_at
            and self.samples[0].sampled_at <= self.assessed_at - WINDOW
            and self.minimum_surplus_w >= MIN_SURPLUS_W
            and any(s.execution_scope_id == scope and s.current_soc == self.current_soc
                    and s.usable_capacity_wh == self.usable_capacity_wh
                    for s in snapshot.current_storage_states)
        )


def _power_time(item: SourceEvidence, at: datetime) -> datetime | None:
    # HA does not update last_updated when an inactive directional channel
    # remains zero. Only an explicit fresh state read may confirm this zero;
    # signed storage and grid power still require fresh telemetry timestamps.
    if item.semantic_role in {"storage_power_to_house", "storage_power_from_house"}:
        try:
            zero = item.raw_state is not None and float(item.raw_state) == 0.0
        except ValueError:
            zero = False
        read, changed, updated = item.state_read_at, item.last_changed_at, item.observed_at
        if zero and read is not None and changed is not None and updated is not None and (
            all(t.utcoffset() is not None for t in (read, changed, updated))
            and changed <= updated <= read <= at and at - read <= MAX_AGE
        ):
            return read
    return item.observed_at


def _power(item: SourceEvidence, at: datetime) -> float | None:
    measured_at = _power_time(item, at)
    if (item.availability != "available" or item.raw_unit != "W"
            or item.raw_state is None or not item.entity_id or not item.evidence_id
            or not item.mapping_version or measured_at is None
            or measured_at.utcoffset() is None
            or not timedelta(0) <= at - measured_at <= MAX_AGE):
        return None
    try:
        value = float(item.raw_state)
    except ValueError:
        return None
    return value if isfinite(value) else None


def net_balance_for(snapshot: PlanningInputSnapshot, scope: str) -> NetBalanceSurplus | None:
    """A current independent proof never releases actively proven load protection."""
    proof = snapshot.net_balance_surplus
    guard = snapshot.household_load_guard
    return proof if proof is not None and proof.matches(snapshot, scope) and (
        guard is None or not guard.active
    ) else None


class NetBalanceObserver:
    """Require continuous valid samples; restart deliberately discards the window."""

    def __init__(self) -> None:
        self._samples: list[NetBalanceSample] = []
        self._episode: datetime | None = None
        self._mapping: object = None

    def _reset(self) -> None:
        self._samples.clear()
        self._episode = None
        self._mapping = None

    def observe(self, bundle: PlanningInputBundle) -> PlanningInputBundle:
        from picot.v2.planning_input import derive_validated_storage_power_w

        snapshot = bundle.snapshot
        at = snapshot.captured_at

        def result(status: str, proof: NetBalanceSurplus | None = None) -> PlanningInputBundle:
            return replace(bundle, snapshot=replace(
                snapshot, net_balance_surplus=proof, net_balance_status=status,
            ))

        def reject(reason: str) -> PlanningInputBundle:
            self._reset()
            return result(reason)

        roles: dict[str, SourceEvidence] = {}
        for item in bundle.evidence:
            if item.semantic_role not in (*POWER_ROLES, "pv_power"):
                continue
            if item.semantic_role in roles:
                return reject("duplicate_source_role")
            roles[item.semantic_role] = item
        if "pv_power" in roles and _power(roles["pv_power"], at) is not None:
            return reject("pv_available")
        if not all(role in roles for role in POWER_ROLES):
            return reject("required_source_missing")
        values = [_power(roles[role], at) for role in POWER_ROLES]
        if any(value is None for value in values):
            return reject("source_unavailable_stale_or_invalid")
        grid, signed, to_house, from_house = values
        storage_power = derive_validated_storage_power_w(
            signed_power_w=signed, power_to_house_w=to_house, power_from_house_w=from_house,
        )
        if grid is None or storage_power is None:
            return reject("storage_power_inconsistent")
        times = tuple(time for role in POWER_ROLES
                      if (time := _power_time(roles[role], at)) is not None)
        if max(times) - min(times) > MAX_SKEW:
            return reject("source_time_skew")
        if len(snapshot.current_storage_states) != 1:
            return reject("single_storage_scope_required")
        storage = snapshot.current_storage_states[0]
        soc_at = storage.state_read_at or storage.measured_at
        if (soc_at.utcoffset() is None or not timedelta(0) <= at - soc_at <= MAX_AGE
                or not isfinite(storage.current_soc) or not isfinite(storage.usable_capacity_wh)):
            return reject("storage_soc_stale_or_invalid")
        if storage_power - grid < MIN_SURPLUS_W:
            return reject("insufficient_net_surplus")
        mapping = (storage.execution_scope_id, storage.usable_capacity_wh, tuple(
            (role, roles[role].entity_id, roles[role].mapping_version) for role in POWER_ROLES
        ))
        sample = NetBalanceSample(
            at, grid, storage_power, storage.current_soc,
            tuple(roles[role].evidence_id for role in POWER_ROLES) + storage.evidence_ids, times,
        )
        repeated = bool(self._samples and mapping == self._mapping
                        and sample == self._samples[-1])
        if self._samples and (
            mapping != self._mapping or (at <= self._samples[-1].sampled_at and not repeated)
            or at - self._samples[-1].sampled_at > MAX_AGE
            or storage.current_soc < self._samples[-1].current_soc
        ):
            self._reset()
        if not self._samples:
            self._episode = at
            self._mapping = mapping
        if not repeated:
            self._samples.append(sample)
        while len(self._samples) > 2 and self._samples[1].sampled_at <= at - WINDOW:
            self._samples.pop(0)
        if self._samples[0].sampled_at > at - WINDOW:
            return result("collecting_net_surplus")
        assert self._episode is not None
        identity = ("net-balance:v1", self._episode, mapping, storage.current_soc)
        proof = NetBalanceSurplus(
            "net-balance:" + sha256(repr(identity).encode()).hexdigest(),
            snapshot.snapshot_id, storage.execution_scope_id, at, self._episode,
            storage.current_soc, storage.usable_capacity_wh,
            min(sample.surplus_w for sample in self._samples), tuple(self._samples),
        )
        return result("sustained_net_surplus", proof)
