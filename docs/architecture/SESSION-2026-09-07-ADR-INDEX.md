# Aanvullende ADR-reeks — MEP-2026-09-07

Datum: 2026-09-07
Status: ACCEPTED — gebruiker heeft vastlegging en start van de afgebakende herbouw bevestigd.

## Bevroren basis

De gebruiker bevestigt in deze sessie uitsluitend ADR-001 t/m ADR-037 als geaccepteerd en bevroren.
Bestaande verwijzingen naar acceptatie van latere ADR's of V2ADR's gelden niet als nieuwe goedkeuring in deze sessie.
De bestaande bestanden worden niet verwijderd of herschreven.

## Nummering

ADR-XXX.n is een zelfstandig gekoppeld aanvullend besluit bij ADR-XXX.
Het nummer verwijst naar de inhoudelijk meest verwante basis-ADR; het is geen vervanging van diens bestand.
Het sessiekenmerk MEP-2026-09-07 maakt de herkomst uniek en herkenbaar.
Na acceptatie blijven ook deze teksten bevroren; volgende wijzigingen krijgen een volgend vrij achtervoegsel en expliciete reikwijdte.

| Nummer | Onderwerp | Status |
| --- | --- | --- |
| [ADR-037.1](ADR-037.1-daily-charge-commitment.md) | Dagelijkse laadverplichting, behoud basisplan en gerichte aanvulling | ACCEPTED |
| [ADR-019.1](ADR-019.1-user-rule-market-dispatch.md) | Handel als gebruikersopdracht, optioneel herstel en nettomarge | ACCEPTED |

De inhoud legt de besproken richting vast. Open specificatiepunten zijn expliciet gemarkeerd en niet stilzwijgend besloten.
Geen van deze documenten verklaart de huidige MEP-code correct of reeds overeenkomstig geïmplementeerd.

## Acceptatie en verificatie — 2026-09-07

De gebruiker heeft vastlegging en een start van de herbouw bevestigd. Acceptatie geldt voor de beschreven besluiten; open punten zijn geen impliciete implementatiekeuzes. De bestaande pipeline blijft behouden. Nieuwe planning geldt pas als LIVE_VERIFIED na controle via de werkelijke Home Assistant-keten. Offline succes alleen is onvoldoende. Opeenvolgende beslismomenten, opgeslagen commitments en herstarts horen bij de verificatie. Geen dagelijkse symptoomfixes op dev.243 als vervanging van de samenhangende herbouw.

## Aanvullende precisering

[ADR-037.2 — Leveringsdaggrens](ADR-037.2-delivery-day-boundary.md) is ACCEPTED: de gepubliceerde lokale leveringsdag begrenst de dagelijkse verplichting. ADR-037.1 blijft bevroren; zijn open periodepunt is hiermee gesloten.

[ADR-037.3 — Voltooiing door hoofdlaadopdracht](ADR-037.3-main-charge-completion.md) is ACCEPTED en beperkt de voltooiingsregel uit ADR-037.1/037.2: alleen de oorspronkelijke hoofdopdracht kan afvinken; aanvullende segmenten nooit.
