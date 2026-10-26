"""Explain recovery states without claiming successful device actuation."""

from collections.abc import Mapping


def recovery_message(reason: str) -> str | None:
    messages = {
        "historical_main_completed_waiting_for_reconciliation": (
            "Het daglaaddoel is voltooid: 100% SOC is bevestigd in de meetgeschiedenis. "
            "Het oude laadblok staat nog in het uitvoeringsplan en wordt daarom geblokkeerd. "
            "PicoT verwerkt automatisch het resterende plan opnieuw; "
            "herstel indrukken is niet nodig."
        ),
        "daily_main_active_plan_unavailable": (
            "Er ontbreekt een actief uitvoeringsplan. PicoT gebruikt de beveiligde NOM-terugval "
            "voor de aansturing en probeert automatisch opnieuw een geldig plan op te bouwen. "
            "Of NOM werkelijk actief is, hangt af van de terugmelding van de batterij."
        ),
        "daily_main_planning_data_unavailable": (
            "De gegevens voor de dagplanning ontbreken of zijn niet bruikbaar. "
            "Er kan nu geen nieuw plan worden vrijgegeven. "
            "PicoT probeert automatisch opnieuw zodra de gegevens beschikbaar zijn."
        ),
        "completed_day_execution_recovered": (
            "Het daglaaddoel blijft voltooid. "
            "Het resterende uitvoeringsplan is automatisch hersteld."
        ),
    }
    continuity_prefix = "planning_unresolved_current_execution_retained:"
    if reason.startswith(continuity_prefix):
        labels = {
            "supplemental_goal_unreachable": "aanvullend laaddoel niet haalbaar",
            "daily_main_goal_unreachable": "daglaaddoel niet haalbaar",
            "supplemental_retirement_bridge_deficit":
                ("aanvullend laadblok blijft nodig voor de energievoorziening "
                 "tot het volgende laadblok"),
            "market_recovery_not_proven": "energieherstel na handel niet aangetoond",
            "household_bridge_unreachable": "energietekort tot het volgende laadblok",
            "household_reserve_unreachable": "huishoudelijke energiereserve niet haalbaar",
        }
        issues = reason[len(continuity_prefix):].split(";")
        descriptions = "; ".join(dict.fromkeys(
            labels.get(issue.split(":", 1)[0], issue) for issue in issues))
        return (
            "Herplanning heeft nog geen geldige route: " + descriptions
            + " (" + reason[len(continuity_prefix):] + ")"
            + ". De huidige planactie is afzonderlijk gecontroleerd en blijft tijdelijk gelden. "
            "De laadopdrachten blijven open; uiterlijk bij de volgende plangrens of na "
            "15 minuten is een nieuwe beoordeling vereist."
        )
    if reason == "current_execution_proof_expired_or_replaced":
        return (
            "De tijdelijke uitvoeringscontrole is verlopen of hoort bij een andere planactie. "
            "Een nieuwe beoordeling is nodig voordat het behouden plan verder mag."
        )
    missing_prefix = "daily_main_planning_data_unavailable:"
    if reason.startswith(missing_prefix):
        labels = {
            "price_points": "elektriciteitsprijzen",
            "pv_energy_timeline": "zonneproductieprognose",
            "household_load_forecast": "huishoudelijke verbruiksprognose",
            "current_storage_states": "actuele batterijstatus (SOC en capaciteit)",
        }
        missing = ", ".join(
            labels.get(key, key) for key in reason[len(missing_prefix) :].split(",")
        )
        return (
            "Geen nieuw uitvoeringsplan: ontbrekende invoer: " + missing + ". "
            "PicoT probeert automatisch opnieuw zodra deze gegevens beschikbaar zijn. "
            "(" + reason + ")"
        )
    if reason in messages:
        return messages[reason] + " (" + reason + ")"
    prefix = "completed_day_recovery_failed:"
    if reason.startswith(prefix):
        return (
            "Het daglaaddoel is voltooid, maar het resterende plan kon niet veilig worden "
            "vastgelegd. Oorzaak: " + reason[len(prefix) :] + ". "
            "PicoT probeert dit automatisch opnieuw in de volgende regelcyclus."
        )
    return None


def recovery_details(attributes: Mapping[str, object]) -> str | None:
    reasons = [
        attributes.get(key) for key in ("error", "reason", "failure_reason", "execution_reason")
    ]
    blockers = attributes.get("blockers")
    if isinstance(blockers, (list, tuple)):
        reasons.extend(blockers)
    texts = [
        recovery_message(reason) or reason
        for reason in reasons
        if isinstance(reason, str) and reason and reason != "-"
    ]
    if any(isinstance(reason, str) and recovery_message(reason) for reason in reasons):
        return "; ".join(dict.fromkeys(texts))
    return None
