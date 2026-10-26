# Automatisch herstel na bewezen dagvoltooiing

Status: lokale reparatie op de exacte tekstbasis van HEMS dev.319 (main
5d7c2f733c472e09be8450cb78237ee9d300eb57). Alex heeft de reparatie gevraagd.
Alex heeft release dev.320 aangevraagd; publicatie via PR en volledige CI.
Installatie en live-aansturing volgen afzonderlijk. Home Climate blijft ongewijzigd.

## Incident en oorzaak

Diagnose `2026-10-26T051229.758` toont historische SOC-voltooiing om 05:01:15
Amsterdamtijd. Na de HA Core-onderbreking blokkeerde uitvoering om 05:03/05:04
op `historical_main_completed_waiting_for_reconciliation`. De historische voltooiing
was dus wel opgeslagen; de resterende uitvoeringsroute werd niet gereconcilieerd.
De bestaande bridge-reconciliatie vereiste een bekende volgende laadsessie. Die ontbrak.
De herstelknop van 05:09:20 verwijderde daarna de actieve route maar behield terecht
het voltooide dagdoel. De planner zocht alleen onvoltooide doelen en bleef daardoor
op `daily_main_active_plan_unavailable` staan.

## Contract en implementatie

De canonieke volgorde blijft Input -> Candidate/EnergyPath -> CandidateOutcome ->
Evaluation -> ExecutionPlanBuilder -> CommitmentStore -> uitvoering (ADR-033/037).
Een bewezen voltooid dagdoel zonder volgende open sessie krijgt een corrigerende
kandidaat. Deze verwijdert alleen nog toekomstige hoofdlaadblokken van dat doel;
onafhankelijke instructies blijven inhoudelijk gelijk. De bestaande PV-overschotregel
bepaalt of een vrijgegeven blok huishoudondersteuning of PV-only NOM wordt.
Er vindt geen nieuwe prijsoptimalisatie of fictieve volgende laadsessie plaats.

Na reset zonder actieve route wordt dezelfde huishoudroute tot het bestaande dageinde
opgebouwd. Actuele invoer, tariefdekking, fysieke limieten, reservecheckpoints en
bestaande verplichtingen blijven voorwaarden. Ontbrekende of onhaalbare gegevens
geven terugval met automatische herbeoordeling in de volgende regelcyclus.

De store legt de nieuwe planidentiteit, evaluatie-identiteit, oorspronkelijke route
(indien aanwezig) en voltooiingsbewijs atomair vast. De oorspronkelijke dagvoltooiing
en historie worden niet herschreven. Herstart valideert deze binding voordat de route
actief wordt. Beschadigde bindingsgegevens blijven geblokkeerd. Een identieke herhaling
mag dezelfde onveranderde route opnieuw activeren; een identiteitsconflict wordt geweigerd.
Bestaande handmatige override- en uitvoeringsbeveiligingen blijven leidend.

Dashboard, planwaarschuwing en gezondheidsmelding verklaren oorzaak, gevolg en automatische
vervolgactie. Ontbrekende prijzen, PV-prognose, verbruiksprognose en batterijstatus worden
bij naam genoemd. Technische foutdetails en aanvullende blokkades blijven zichtbaar.
Een aangevraagde NOM-terugval wordt niet als bevestigde apparaatmodus gepresenteerd.

## Verificatie

- Fout eerst gereproduceerd met historische voltooiing, zowel voor als na herstelreset.
- Gecombineerde gerichte suite: 133 tests geslaagd (planning, bridge, historische en
  actuele voltooiing, reset, store/herstart, reservebindingen, meldingen en dashboard/JS).
- Finale herstel- en meldingensuite: 17 tests geslaagd, inclusief ontbrekende
  capabilities en fysieke limieten (15 overlappen met bovenstaande suite).
- Ruff groen voor de gewijzigde Pythonbestanden; mypy groen voor acht productiemodules.
  Mypy gebruikt de Python-parser (`--no-native-parser`) wegens een interne fout in de
  lokaal aanwezige native parser. Er zijn geen typecontroles uitgezet.
- Offline herhaling met echte diagnose-invoer en oorspronkelijke store van 05:04:33:
  `winner_selected / completed_day_execution_recovered`, plan `plan-3fd9440038e5f4e5`.
- Offline herhaling met diagnose-invoer en store na reset van 05:10:53:
  dezelfde hersteluitkomst, plan `plan-804cfc502195303a`, herstelverzoek
  `999c1ec1-141c-44e5-abc1-893701d1692e` wordt `completed`. Beide plannen bevatten
  76 resterende intervallen. De gemeten RTE van 0.8199 is gebruikt.
- Uitvoering apart getest via de echte CanonicalExecutionRuntime-grens: de herstelde
  route wordt herkend als already_active bij bevestigde modus; manual_override blijft blocked.
  De diagnoseherhalingen zelf hebben geen apparaatopdrachten verstuurd.

Volledige release-CI, installatie en livecontrole volgen afzonderlijk. De nieuwe persistente
bindingsvorm wordt door dev.319 niet begrepen; bij rollback moet de bijbehorende eerdere
store-back-up worden gebruikt, zonder voltooiingsbewijs weg te gooien. De reparatiecode
staat in `recovery-completed-fix`; `sources/` en de oorspronkelijke diagnose zijn ongewijzigd.
