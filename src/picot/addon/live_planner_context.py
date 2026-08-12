"""Live ADR-037 context bridges for confidence and price opportunities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from statistics import fmean
from typing import Mapping

from picot.addon.history_store import HistoryStore
from picot.domain.evidence_confidence_policy import (
    EvidenceConfidenceAssessment,
    EvidenceConfidenceBaseline,
    RelativeEvidenceConfidencePolicy,
)
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
    OpportunityMetric,
    OpportunityMetricKind,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import ProjectedHouseholdEnergyBalance

SOURCE_METHOD_ID = "live-projected-household-balance-v1"
BASELINE_HISTORY_DAYS = 14
MIN_RELIABLE_SAMPLES = 12


@dataclass(slots=True)
class LiveEvidenceConfidenceTracker:
    """Compare current balance confidence against its own rolling historical mean."""

    history: HistoryStore = field(default_factory=HistoryStore)
    _samples: list[float] = field(default_factory=list)
    _loaded: bool = False

    def _load(self, captured_at) -> None:
        if self._loaded:
            return
        start = captured_at - timedelta(days=BASELINE_HISTORY_DAYS)
        for event in self.history.iter_range(start, captured_at):
            if event.get("event") != "picot_live_adr037_readiness":
                continue
            value = event.get("projected_balance_confidence")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value)
                if 0.0 <= value <= 1.0:
                    self._samples.append(value)
        self._loaded = True

    def assess(
        self,
        *,
        balance: ProjectedHouseholdEnergyBalance,
        snapshot: PlanningInputSnapshot,
    ) -> EvidenceConfidenceAssessment:
        self._load(snapshot.captured_at)
        baseline = None
        if self._samples:
            baseline = EvidenceConfidenceBaseline(
                baseline_id=f"live-confidence-baseline:{snapshot.captured_at.date().isoformat()}",
                source_method_id=SOURCE_METHOD_ID,
                mean_confidence=fmean(self._samples),
                sample_count=len(self._samples),
                reliable=len(self._samples) >= MIN_RELIABLE_SAMPLES,
                evidence_ids=("history:picot_live_adr037_readiness",),
                method_version="rolling-own-mean-v1",
            )
        assessment = RelativeEvidenceConfidencePolicy().assess(
            current_confidence=balance.confidence,
            current_source_method_id=SOURCE_METHOD_ID,
            current_evidence_ids=(balance.balance_id,),
            baseline=baseline,
        )
        self._samples.append(balance.confidence)
        return assessment


def opportunity_set_from_planner_context(
    planner_context: Mapping[str, object],
    *,
    snapshot_id: str,
) -> OpportunitySet | None:
    """Rebind canonical Price Driven v2 opportunities to the live snapshot.

    The facts and immutable evidence references are preserved. No opportunity is
    inferred from prices here; v1/legacy planner context therefore remains blocked.
    """

    if planner_context.get("strategy_id") != "price-driven-v2-canonical":
        return None
    raw_items = planner_context.get("price_opportunities")
    if not isinstance(raw_items, list):
        return None

    opportunities: list[Opportunity] = []
    metric_fields = {
        "average_price_eur_per_kwh": OpportunityMetricKind.AVERAGE_ENERGY_PRICE_EUR_PER_KWH,
        "minimum_price_eur_per_kwh": OpportunityMetricKind.MINIMUM_ENERGY_PRICE_EUR_PER_KWH,
        "maximum_price_eur_per_kwh": OpportunityMetricKind.MAXIMUM_ENERGY_PRICE_EUR_PER_KWH,
        "reference_price_eur_per_kwh": OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH,
        "boundary_price_eur_per_kwh": OpportunityMetricKind.PRICE_BOUNDARY_EUR_PER_KWH,
        "duration_seconds": OpportunityMetricKind.DURATION_SECONDS,
        "source_interval_count": OpportunityMetricKind.SOURCE_INTERVAL_COUNT,
        "bridged_interval_count": OpportunityMetricKind.BRIDGED_INTERVAL_COUNT,
    }
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        raw_evidence = raw.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            return None
        evidence: list[EvidenceReference] = []
        for item in raw_evidence:
            if not isinstance(item, dict):
                return None
            source_id = item.get("source_id")
            point_indexes = item.get("point_indexes")
            if not isinstance(source_id, str) or not isinstance(point_indexes, list):
                return None
            evidence.append(
                EvidenceReference(
                    source_id=source_id,
                    point_indexes=tuple(int(index) for index in point_indexes),
                )
            )
        metrics = tuple(
            OpportunityMetric(kind=kind, value=float(raw[field_name]))
            for field_name, kind in metric_fields.items()
            if isinstance(raw.get(field_name), (int, float))
            and not isinstance(raw.get(field_name), bool)
        )
        opportunities.append(
            Opportunity(
                opportunity_id=str(raw["opportunity_id"]),
                snapshot_id=snapshot_id,
                kind=OpportunityKind(str(raw["kind"])),
                starts_at=_parse_datetime(str(raw["starts_at"])),
                ends_at=_parse_datetime(str(raw["ends_at"])),
                confidence=float(raw["confidence"]),
                lifecycle=OpportunityLifecycle.DETECTED,
                evidence=tuple(evidence),
                metrics=metrics,
            )
        )
    return OpportunitySet(snapshot_id=snapshot_id, opportunities=tuple(opportunities))


def _parse_datetime(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
