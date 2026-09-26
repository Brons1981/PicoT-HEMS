"""Large market comparisons keep replay input and every financial alternative."""

import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from legacy_cp_pipeline import CanonicalPipeline
from test_market_revision_comparison import scenario

import picot.v2.planning_incident_history as history_module
from picot.domain.energy_path import ProjectedEnergyState
from picot.domain.evaluation import (
    CandidateComparisonValue,
    CandidateOutcome,
    CandidateValidity,
    ComparisonDirection,
    EvaluationRecord,
    InvalidCandidateRecord,
    ObjectiveComparisonRecord,
    ObjectiveOutcome,
    RelativeResult,
)
from picot.domain.market_revision_comparison import (
    MarketRevisionCandidateEvidence,
    MarketRevisionDayResult,
)
from picot.domain.objectives import ObjectiveKind
from picot.v2.contracts import CandidateSet
from picot.v2.planning_incident_history import PlanningIncidentHistory, _record_json_value
from picot.v2.planning_input import PlanningInputBundle


def large_market_run(tmp_path, count):
    # Real complete snapshot/store provenance; repeated alternatives below are
    # frozen serializer fixtures, not independently selected planning results.
    _, snapshot, _ = scenario(tmp_path)
    run = CanonicalPipeline().run(captured_at=snapshot.captured_at)
    source = run.candidate_set.candidates[0]
    path = run.candidate_set.energy_paths[0]
    states = tuple(ProjectedEnergyState(
        at=snapshot.captured_at + timedelta(minutes=15 * n), confidence=0.9,
        household_import_w=0.0, household_export_w=0.0, pv_production_w=1000.0,
        household_demand_w=400.0, battery_soc=0.5, storage_energy_wh=4080.0,
        conversion_losses_w=50.0,
    ) for n in range(145))
    candidates = tuple(replace(
        source, candidate_id=f"main-charge-candidate-{n:016x}",
        energy_path_id=f"main-charge-path-{n:016x}", run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id, family="cost_first",
    ) for n in range(count))
    paths = tuple(replace(path, path_id=c.energy_path_id, run_id=snapshot.run_id,
                          snapshot_id=snapshot.snapshot_id, projected_states=states)
                  for c in candidates)
    common_evidence = tuple(f"forecast-tariff-evidence-{n:016x}" for n in range(400))
    outcomes = []
    evidence = []
    invalid = []
    values = []
    for n, candidate in enumerate(candidates):
        ids = (f"schedule:{n:016x}", *common_evidence)
        reasons = ("market_revision_terminal_inventory_not_comparable",) if n % 10 == 1 else ()
        result = 0.5 - n / 10000
        outcomes.append(CandidateOutcome(
            candidate_id=candidate.candidate_id,
            objective_outcomes=(ObjectiveOutcome(
                ObjectiveKind.FINANCIAL_RESULT, result, ComparisonDirection.HIGHER_IS_BETTER,
                "EUR", 0.9, ids,
            ),), confidence=0.9, recoverability=None, execution_complexity=8,
            expected_switching_count=7, complexity_version="test:segment-count",
            validity=CandidateValidity.INVALID if reasons else CandidateValidity.VALID,
            invalidity_reasons=reasons, evidence_ids=ids,
        ))
        if reasons:
            invalid.append(InvalidCandidateRecord(candidate.candidate_id, reasons))
        values.append(CandidateComparisonValue(
            candidate.candidate_id, result,
            RelativeResult.EQUAL if n == 0 else RelativeResult.WORSE,
        ))
        evidence.append(MarketRevisionCandidateEvidence(
            candidate_id=candidate.candidate_id, assignment_id="market:2026-08-23",
            variant=("retained", "shortened", "removed")[n % 3],
            horizon_start=snapshot.captured_at, horizon_end=snapshot.horizon_end,
            days=(MarketRevisionDayResult("2026-08-23", 0.25, 0.8),
                  MarketRevisionDayResult("2026-08-24", 0.35, 0.3)),
            grid_charge_wh=2000.0 + n, terminal_storage_wh=4080.0, minimum_storage_wh=816.0,
            wear_cost_eur=0.0, comparable_result_eur=None if reasons else result,
            delta_from_incumbent_eur=None if reasons else result - 0.1,
            invalidity_reasons=reasons, evidence_ids=ids,
        ))
    reference = "market-candidates:serialization-fixture"
    winner, incumbent = candidates[0], candidates[-1]
    record = EvaluationRecord(
        evaluation_id="evaluation:serialized-market", schema_version=1,
        snapshot_id=snapshot.snapshot_id, strategy_version=1,
        candidate_set_reference=reference,
        evaluated_candidate_ids=tuple(c.candidate_id for c in candidates),
        invalid_candidates=tuple(invalid),
        strategic_objective_order=(ObjectiveKind.FINANCIAL_RESULT,),
        objective_comparisons=(ObjectiveComparisonRecord(
            ObjectiveKind.FINANCIAL_RESULT, 1000, ComparisonDirection.HIGHER_IS_BETTER,
            "EUR", tuple(values), (winner.candidate_id,), True, True,
        ),), tie_breaks=(), decisive_step="objective:financial_result",
        winning_candidate_id=winner.candidate_id, created_at=snapshot.captured_at,
        implementation_version="test:canonical-evidence",
    )
    return replace(
        run, planning_input=snapshot,
        candidate_set=replace(run.candidate_set, run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id, candidate_set_id=reference,
            candidates=candidates, energy_paths=paths),
        outcomes=replace(run.outcomes, run_id=snapshot.run_id, snapshot_id=snapshot.snapshot_id,
            candidate_set_id=reference, candidate_ids=tuple(c.candidate_id for c in candidates),
            outcomes=(), canonical_outcomes=tuple(outcomes),
            market_revision_evidence=tuple(evidence)),
        evaluation=replace(run.evaluation, run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id, evaluation_id=record.evaluation_id,
            candidate_set_id=reference, winning_candidate_id=winner.candidate_id,
            winning_energy_path_id=winner.energy_path_id,
            incumbent_candidate_id=incumbent.candidate_id,
            evaluated_candidate_ids=record.evaluated_candidate_ids,
            canonical_record=record, status="winner_selected", decisive_step=record.decisive_step),
    )


@pytest.mark.parametrize("count", [1501, 4007])
def test_large_market_record_preserves_snapshot_all_outcomes_and_selected_paths(
    tmp_path, monkeypatch, count,
):
    run = large_market_run(tmp_path, count)
    original_asdict = history_module.asdict

    def bounded_asdict(value):
        if isinstance(value, CandidateSet):
            assert len(value.energy_paths) <= 2, "excluded paths must never be expanded first"
        return original_asdict(value)

    monkeypatch.setattr(history_module, "asdict", bounded_asdict)
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    snapshot = run.planning_input
    bundle = PlanningInputBundle(snapshot, (), (), snapshot.captured_at, snapshot.captured_at)
    history.record(bundle=bundle, run=run)
    body = history.path.read_bytes()
    assert len(body) < history_module.MAX_INCIDENT_RECORD_BYTES
    record = json.loads(body)
    assert record.get("detail_level") != "bounded"
    poll = record["poll"]
    assert poll["comparison_detail_format"] == "market-revision-compact:v1"
    assert poll["planning_input"] == json.loads(json.dumps(
        asdict(snapshot), default=_record_json_value,
    ))
    assert poll["evaluation"] == json.loads(json.dumps(
        asdict(run.evaluation), default=_record_json_value,
    ))
    assert len(poll["candidate_set"]["candidates"]) == count
    assert len(poll["outcomes"]["canonical_outcomes"]) == count
    alternatives = poll["outcomes"]["market_revision_evidence"]
    assert len(alternatives) == count
    paths = poll["candidate_set"]["energy_paths"]
    assert [p["path_id"] for p in paths] == [
        run.candidate_set.energy_paths[0].path_id, run.candidate_set.energy_paths[-1].path_id,
    ]
    assert paths == json.loads(json.dumps(
        [asdict(run.candidate_set.energy_paths[0]), asdict(run.candidate_set.energy_paths[-1])],
        default=_record_json_value,
    ))
    assert poll["candidate_set"]["omitted_alternative_energy_path_count"] == count - 2
    dictionary = poll["comparison_evidence_dictionary"]

    def resolve(reference):
        item = dictionary[reference]
        if "ids" in item:
            return item["ids"]
        base = dictionary[item["base"]]["ids"]
        return base[:item["prefix_count"]] + item["middle"] + base[item["suffix_start"]:]

    for actual, expected in zip(alternatives, run.outcomes.market_revision_evidence, strict=True):
        assert actual["candidate_id"] == expected.candidate_id
        assert actual["comparable_result_eur"] == expected.comparable_result_eur
        assert actual["invalidity_reasons"] == list(expected.invalidity_reasons)
        assert actual["days"] == [asdict(day) for day in expected.days]
        assert resolve(actual["evidence_ids_ref"]) == list(expected.evidence_ids)
    for actual, expected in zip(
        poll["outcomes"]["canonical_outcomes"], run.outcomes.canonical_outcomes, strict=True,
    ):
        assert resolve(actual["evidence_ids_ref"]) == list(expected.evidence_ids)
        assert resolve(actual["objective_outcomes"][0]["evidence_ids_ref"]) == (
            list(expected.objective_outcomes[0].evidence_ids)
        )
    print(f"market candidates={count}, diagnostic bytes={len(body)}")
