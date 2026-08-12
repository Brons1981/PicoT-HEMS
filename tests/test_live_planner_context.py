from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from picot.addon.history_store import HistoryStore
from picot.addon.live_planner_context import (
    LiveEvidenceConfidenceTracker,
    opportunity_set_from_planner_context,
)
from picot.domain.evidence_confidence_policy import EvidenceConfidenceDecision
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalancePoint,
)

BASE = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _balance(confidence: float) -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-live",
        created_at=BASE,
        horizon_end=BASE + timedelta(hours=1),
        execution_scope_id="storage-primary",
        starting_storage_energy_wh=4000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=BASE + timedelta(hours=1),
                projected_storage_energy_wh=4200.0,
                cumulative_pv_energy_wh=800.0,
                cumulative_household_load_wh=600.0,
            ),
        ),
        confidence=confidence,
        evidence_ids=("live-evidence",),
    )


class _Snapshot:
    captured_at = BASE


def test_confidence_uses_its_own_rolling_mean(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    for index in range(12):
        store.append(
            {
                "event": "picot_live_adr037_readiness",
                "captured_at": (BASE - timedelta(minutes=index + 1)).isoformat(),
                "projected_balance_confidence": 0.8,
            }
        )
    tracker = LiveEvidenceConfidenceTracker(history=store)

    assessment = tracker.assess(balance=_balance(0.81), snapshot=_Snapshot())

    assert assessment.baseline_mean_confidence == 0.8
    assert assessment.decision is EvidenceConfidenceDecision.LOWER_TARGET_ALLOWED
    assert assessment.reason == "current_confidence_at_or_above_own_reliable_mean"


def test_price_opportunities_preserve_canonical_evidence_and_rebind_snapshot() -> None:
    context = {
        "strategy_id": "price-driven-v2-canonical",
        "price_opportunities": [
            {
                "opportunity_id": "low-1",
                "kind": "lowest_price_window",
                "starts_at": BASE.isoformat(),
                "ends_at": (BASE + timedelta(hours=1)).isoformat(),
                "confidence": 1.0,
                "evidence": [
                    {"source_id": "ha-price-source", "point_indexes": [0, 1, 2, 3]}
                ],
                "average_price_eur_per_kwh": 0.12,
                "duration_seconds": 3600.0,
                "source_interval_count": 4.0,
                "bridged_interval_count": 0.0,
            }
        ],
    }

    result = opportunity_set_from_planner_context(context, snapshot_id="live-snapshot")

    assert result is not None
    assert result.snapshot_id == "live-snapshot"
    assert len(result.opportunities) == 1
    assert result.opportunities[0].evidence[0].source_id == "ha-price-source"
    assert result.opportunities[0].snapshot_id == "live-snapshot"


def test_legacy_price_context_does_not_become_fake_canonical_opportunity() -> None:
    assert (
        opportunity_set_from_planner_context(
            {"strategy_id": "price-driven-v1"}, snapshot_id="live-snapshot"
        )
        is None
    )
