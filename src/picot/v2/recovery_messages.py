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
