"""Plan the bedroom's evening recovery within its daytime noise window."""

from datetime import datetime

from .energy_outlook import read_outlook
from .schedule import TZ

FLOOR_C = 15.5
RECOVERY_C = 16.0
MIN_RUN_SECONDS = 600
PLANNING_SECONDS = 45 * 60


def overlap(start, end, left, right):
    return max(0, min(end, right) - max(start, left))


def evening_heat(now, temperature, running_since, prices, states):
    local = datetime.fromtimestamp(now, TZ)
    deadline = local.replace(hour=18, minute=0, second=0, microsecond=0).timestamp()
    closes = local.replace(hour=20, minute=0, second=0, microsecond=0).timestamp()
    latest_start = deadline - PLANNING_SECONDS
    result = dict(target=FLOOR_C, demand=False)
    if local.hour < 8 or now >= closes:
        return dict(result, reason='Slaapkamer mag afkoelen. Qlima beschikbaar van 08:00 tot 20:00.')
    if running_since is not None:
        demand = temperature < RECOVERY_C or now - running_since < MIN_RUN_SECONDS
        return dict(result, demand=demand, reason=('Slaapkamer verwarmen tot 16,0 °C.' if demand
                                                  else 'Slaapkamer op temperatuur voor vanavond.'))
    if temperature > FLOOR_C:
        return dict(result, reason='Slaapkamer boven 15,5 °C. HC blijft meten tot het avondvenster.')
    if now > deadline:
        return dict(result, reason='Avonddoel gemist. Slaapkamer kan vannacht afkoelen.')
    if now >= latest_start:
        return dict(result, demand=True, reason='Slaapkamer bijverwarmen. De prijs mag de start niet verder uitstellen.')

    # Compare complete runs including ones crossing a tariff boundary. The HEMS
    # forecast only breaks price ties. Projected export isn't an assigned budget.
    outlook = read_outlook(states, now)
    candidates = {now, latest_start}
    for row in prices:
        for boundary in (row['start'], row['end'] - PLANNING_SECONDS):
            if now < boundary < latest_start:
                candidates.add(boundary)
    for slot in outlook['slots']:
        for boundary in (slot['starts_at'], slot['ends_at'] - PLANNING_SECONDS):
            if now < boundary < latest_start:
                candidates.add(boundary)
    scored = []
    for start in candidates:
        end = start + PLANNING_SECONDS
        lengths = [overlap(start, end, row['start'], row['end']) for row in prices]
        if abs(sum(lengths) - PLANNING_SECONDS) > .01:
            continue
        rate = sum(length * row['value'] for length, row in zip(lengths, prices)) / PLANNING_SECONDS
        solar = sum(slot['pv_export_wh'] * overlap(start, end, slot['starts_at'], slot['ends_at'])
                    / (slot['ends_at'] - slot['starts_at']) for slot in outlook['slots'])
        scored.append((round(rate, 6), -solar, start))
    if not scored:
        return dict(result, reason='Onvolledig prijsvenster. HC beoordeelt de slaapkamer uiterlijk om 17:15 opnieuw.')
    _, _, start = min(scored)
    if start <= now:
        return dict(result, demand=True, reason='Slaapkamer bijverwarmen in het voordeligste beschikbare prijsvenster.')
    time = datetime.fromtimestamp(start, TZ).strftime('%H:%M')
    return dict(result, reason=f'Slaapkamer wacht op het voordelige prijsvenster om {time}.')
