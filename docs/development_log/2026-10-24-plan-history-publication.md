# Planvergelijking en publicatievolgorde

Status: lokaal geïmplementeerd na akkoord van Alex; basis HEMS dev.316 / PR #726.
Alex heeft release dev.317 aangevraagd; publicatie via PR en CI. Installatie en livecontrole volgen afzonderlijk. Kleine financiële stand-bywisselingen vallen buiten deze reparatie.

## Contract

Het actuele canonieke plan en zijn SOC-prognose worden samen gepubliceerd voordat de nieuwe-planmelding wordt verzonden. Optioneel financieel rekenwerk mag deze publicatie niet ophouden of later een ouder dashboard terugzetten. Historische plannen worden uitsluitend gelezen en vergeleken; het openen ervan verandert geen actief plan of SOC-grafiek.

ADR-017/030/035 en de canonieke pipelinegrens blijven leidend: Projection/UI presenteert opgeslagen identiteit en segmenten; geen nieuwe simulatie, selectie, dispatch of planherstel. De terugvalgrens is de dev.316-weergave/publicatievolgorde, zonder wijzigingen aan persistente plangegevens.

## Bewijs en wijzigingen

Diagnose 2026-10-24T213406.439 bevat actief plan fe0cbe95dfde4600 van21:33, voorganger efa6754227a00c73 van21:31 en het voor-resetplan32b52be1b0196702. SOC-cache en displayhistorie stonden nog op21:31. De exacte vertraging van die afzonderlijke run is niet bewezen: het incident werd wegens22 MB teruggebracht tot een begrensde samenvatting.

- live_runtime publiceert eerst de volledige plan/SOC-weergave; daarna de planningmelding en financiële afleiding. Financiële resultaten gebruiken de bestaande overlay en vervangen geen later gepubliceerde weergave. Uitvoering en vroege gezondheidsmeldingen blijven op hun oorspronkelijke plaats.
- ActivePlanCommitmentStore biedt twintig recente, begrensde en losgekoppelde records uit de bestaande gedeelde leescache, inclusief actieve plannen. Geen tokens, zware bewijslijsten of schrijfoperaties. Alleen expliciet bewaarde redenen worden getoond.
- GET /api/plan-history is alleen-lezen en ongecachet; lezen houdt de publicatielock niet vast. De browser toont huidig en gekozen historisch plan naast elkaar. Amsterdamtijd inclusief UTC-offset maakt het teruggezette uur ondubbelzinnig. Selectie verandert actieve tijdlijn/SOC niet. Ontbrekende gegevens, afkapping en mislukte verversing zijn zichtbaar.

## Verificatie

- Fail-before: drie ontbrekende-historiegevallen en drie werkelijke runtime-publicatiegevallen faalden op de verwachte grens.
- Finale gecombineerde historie/API-handler/runtime/JS/opstart/commitmentstore/leescache/SOC-cache/webpublicatie: 52 geslaagd, 1 echte socket-opstarttest uitgesloten na WinError10013 in de sandbox.
- Aanvullende frontendcontroles:82 geslaagd,1 sockettest uitgesloten (overlap met bovenstaande).
- Ruff: drie gewijzigde productiebronbestanden en drie nieuwe testbestanden groen. Mypy: drie productiebronbestanden groen voor Linux. Volledige JavaScript-syntax gecontroleerd.
- Werkelijke diagnose:20 samenvattingen,54.061 JSON-bytes; actief plan en beide relevante voorgangers aanwezig. De 138 MB bron wordt niet naar de browser gestuurd.

HTTP-handlergedrag is lokaal getest met geheugenstreams, inclusief GET/no-store en POST405. Echte netwerk-/browser-/HA-eindcontrole en volledige CI blijven onderdeel van een volgende release. Publicatie vóór een melding garandeert beschikbaarheid van de juiste serverweergave; het is geen ontvangstbevestiging van een reeds geopende browser.

Onafhankelijke review vond een beschadigd historisch segment dat het overzicht kon laten mislukken. Het nieuwe regressiegeval faalde vóór herstel; ongeldige historische records worden nu overgeslagen met zichtbare teller, terwijl het geldige actieve plan beschikbaar blijft. De werkelijke diagnose geeft nul overgeslagen records en dezelfde drie relevante voorgangers. Geen planner-, stand-bybeleid- of HC-wijziging. Alleen HEMS krijgt versie dev.317.
