"""Read-only explanation of admitted canonical decisions; never a planner."""

from picot.domain.evaluation import CandidateValidity, ComparisonDirection, ObjectiveOutcome
from picot.domain.objectives import ObjectiveKind
from picot.v2.contracts import CanonicalPipelineRun


def build_plan_decision(run: CanonicalPipelineRun) -> dict[str, object]:
    snapshot, evaluation = run.planning_input, run.evaluation
    record = evaluation.canonical_record
    plans = run.execution_plan_set.plans
    state = next(iter(snapshot.current_storage_states), None)
    forecast = snapshot.household_load_forecast
    session_in_forecast = bool(forecast and any(
        i.method_version == "energy-device-session-demand:v1" for i in forecast.intervals
    ))
    ev = ("Bevestigde autolaadsessie verwerkt in de verbruiksprognose."
          if session_in_forecast else
          "Geen afzonderlijke toekomstige autolaadsessie verwerkt in de verbruiksprognose.")
    payload: dict[str, object] = {
        "source": "comparison" if record is not None else "observation",
        "evidence_retained": False,
        "assessed_at": snapshot.captured_at.isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "evaluation_id": evaluation.evaluation_id,
        "execution_plans": [{"plan_id": p.plan_id, "energy_path_id": p.winning_energy_path_id}
                            for p in plans],
        "status": "unavailable", "reason": "Geen vergelijkbare planbeoordeling beschikbaar.",
        "horizon_start": None, "horizon_end": None,
        "incumbent_cost_eur": None, "alternative_cost_eur": None,
        "improvement_eur": None, "minimum_improvement_eur": None,
        "solcast_basis": snapshot.solcast_planning_basis,
        "initial_soc": state.current_soc if state else None,
        "ev_assumption": ev,
        "household_assumption": ("Verwacht huisverbruik uit de beschikbare prognose."
                                 if forecast else "Geen huisverbruiksprognose beschikbaar."),
        "trigger": evaluation.reason,
    }
    if evaluation.status == "fallback_active":
        payload.update(status="fallback", reason=(
            "Geen uitvoerbaar nieuw plan vrijgegeven. Terugval actief; "
            "zie de actuele foutmelding. Oorzaak: " + evaluation.reason))
        return payload
    if record is None:
        if plans:
            payload.update(status="retained", reason=(
                "Het bestaande plan blijft gelden. Deze controle heeft geen nieuwe "
                "financiële vergelijking gemaakt."))
        return payload
    winner = record.winning_candidate_id
    incumbent = evaluation.incumbent_candidate_id
    published = bool(winner and any(p.winning_candidate_id == winner for p in plans))
    retained = winner is not None and winner == incumbent
    if not retained and not published:
        payload.update(status="publication_failed", reason=(
            "De beoordeelde vervanger is niet vrijgegeven. Het bestaande plan is niet "
            "door die keuze vervangen. Oorzaak: " + evaluation.reason))
        return payload
    payload["status"] = "retained" if retained else "replaced" if incumbent else "selected"
    step = record.decisive_step or ""
    if "minimum_improvement_incumbent_retained" in step:
        reason = ("Bestaand plan behouden: geen uitvoerbaar, vergelijkbaar alternatief "
                  "haalt het minimale financiële voordeel.")
    elif "equivalent_incumbent_retained" in step:
        reason = "Bestaand plan behouden: geen beter uitvoerbaar alternatief."
    elif retained:
        reason = "Bestaand plan behouden na vergelijking van de uitvoerbare alternatieven."
    elif evaluation.daily_main_shortfall is not None or evaluation.daily_main_input_shortfalls:
        reason = ("Plan aangepast omdat de bestaande route het vereiste laad-/SOC-doel "
                  "niet meer haalt. Uitvoerbaarheid gaat voor financieel planbehoud.")
    elif evaluation.daily_bridge is not None and evaluation.daily_bridge.trigger is not None:
        reason = ("Plan aangepast vanwege een verwacht energietekort vóór het volgende "
                  "laadvenster. De uitvoerbare overbruggingsroutes zijn vergeleken.")
    elif step == "objective:financial_result":
        reason = "Deze route wint de vastgelegde financiële vergelijking."
    else:
        reason = "Deze route is gekozen volgens de vastgelegde plandoelen en gelijkspelregels."
    excluded = {reason for candidate in record.invalid_candidates for reason in candidate.reasons}
    if "main_revision_terminal_inventory_not_equal" in excluded:
        reason += (" Alternatieven met een andere eindvoorraad zijn uitgesloten: "
                   "hun totale kosten zijn niet eerlijk vergelijkbaar.")
    if "main_revision_comparison_horizon_not_equal" in excluded:
        reason += " Alternatieven met een andere vergelijkingsperiode zijn uitgesloten."
    payload["reason"] = reason
    for tie in record.tie_breaks:
        if tie.minimum_improvement_eur is not None:
            payload["minimum_improvement_eur"] = tie.minimum_improvement_eur
    # Show producer-supplied total EUR only. Acquisition rates and their scaled
    # benefits must never masquerade as whole-route savings in the dashboard.
    valid = {o.candidate_id: o for o in run.outcomes.canonical_outcomes
             if o.validity is CandidateValidity.VALID}
    financial: dict[str, ObjectiveOutcome] = {
        key: f for key, outcome in valid.items() for f in outcome.objective_outcomes
        if f.objective is ObjectiveKind.FINANCIAL_RESULT and f.unit == "EUR"
        and f.direction is ComparisonDirection.HIGHER_IS_BETTER
    }
    if incumbent not in financial:
        if any(f.unit == "EUR/kWh-stored" for o in valid.values()
               for f in o.objective_outcomes if f.objective is ObjectiveKind.FINANCIAL_RESULT):
            payload["reason"] = reason + (
                " Deze beoordeling gebruikt de laadprijs per opgeslagen kWh; "
                "er is geen vergelijkbaar totaalvoordeel vastgelegd.")
        return payload
    alternatives = [o for key, o in valid.items() if key != incumbent and key in financial
                    and o.commitment_improvement_eur is not None]
    alternative = (next((o for o in alternatives if o.candidate_id == winner), None)
                   if not retained else max(alternatives,
                       key=lambda o: (financial[o.candidate_id].value, o.candidate_id),
                       default=None))
    if alternative is None:
        return payload
    by_candidate = {c.candidate_id: c.energy_path_id for c in run.candidate_set.candidates}
    paths = {p.path_id: p for p in run.candidate_set.energy_paths}
    path = paths.get(by_candidate.get(alternative.candidate_id, ""))
    if path is None or not path.segments:
        return payload
    # A market recovery comparison may have an earlier financial boundary.
    market = next((e for e in run.outcomes.market_revision_evidence
                   if e.candidate_id == alternative.candidate_id), None)
    payload.update(
        incumbent_candidate_id=incumbent, alternative_candidate_id=alternative.candidate_id,
        incumbent_cost_eur=-financial[incumbent].value,
        alternative_cost_eur=-financial[alternative.candidate_id].value,
        improvement_eur=alternative.commitment_improvement_eur,
        horizon_start=(market.horizon_start if market else
                       min(s.starts_at for s in path.segments)).isoformat(),
        horizon_end=(market.horizon_end if market else
                     max(s.ends_at for s in path.segments)).isoformat(),
    )
    return payload
