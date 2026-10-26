# NOM-continuiteit na herstel van een voltooid dagdoel

Status: release dev.321 aangevraagd, gebouwd op HEMS dev.320 / main
184e2cddf5a714575b5bb78c59160c065f3e8c56, op akkoord van Alex.
Publicatie via PR en groene CI; geen livewijziging. Alleen HEMS-herstelgedrag binnen scope.

## Bewijs en contract

Diagnose `2026-10-26T061710.080` bevestigt voltooid herstel om 06:14 en actieve uitvoering.
Het oude plan `plan-c1b0600587958fbf` bevatte NOM van 09:00 tot 15:00 Amsterdamtijd.
Het resetplan `plan-3aa6b9399589002a` uit dev.320 koos per kwartier NOM alleen bij
voorspeld PV-overschot. Daardoor ontstonden vier onderbrekingen naar slim ontladen:
09:15-09:45, 11:00-11:30, 12:45-13:00 en 13:30-13:45.

De correctie gebruikt het gevalideerde oorspronkelijke dagplan als bron voor de
resterende huishoudelijke instructies, begrensd tot uiterlijk het bestaande dageinde.
Alleen bewezen voltooide hoofdlaadblokken worden vrijgegeven. Er worden geen
geannuleerde netlaad-, export-, aanvullende laad-, reserve- of handelsopdrachten
uit historie geactiveerd. Bij een niet-passieve bron blijft de bestaande herstelroute
beschikbaar; een oud plan wordt nooit blind actief gezet.

De gehele route gaat opnieuw door de bestaande fysieke projectie, capability- en
reservecontroles, CandidateOutcome, Evaluation en ExecutionPlanBuilder. Er is geen
nieuwe economische selectie, vermogensaansturing of aangepaste PV-drempel.
ADR-033 en ADR-037.21 blijven leidend.

## Implementatie en opslag

- Een zuivere dev.320-resetroute wordt herkend via de gevalideerde completed-route-binding
  en haar huishoudsegmenten. Zij kan eenmaal door een historisch onderbouwde route worden
  vervangen. Nieuwe canonieke identiteit voorkomt een herhaalde correctie.
- Deze specifieke correctie wordt voor de bridge-beoordeling herkend. Zonder toekomstige
  hoofdlaadsessie kan die beoordeling geen dagelijkse eigenaar voor de resetroute aanwijzen;
  dat mag deze beperkte correctie niet vooraf tegenhouden.
- De binding bewaart zowel `previous_plan_id` (feitelijk vervangen plan) als
  `reference_plan_id` (gevalideerde oorspronkelijke dagroute). Restart valideert bron,
  eigenaar, voltooiingsbewijs, horizon en behouden instructies opnieuw.
- Dagvoltooiing en beide historische plannen blijven ongewijzigd. Alleen het nieuwe plan
  en de actieve verwijzing worden atomair vastgelegd.
- Mislukt de optionele correctie van een bestaand plan, dan blijft dat plan beschikbaar
  onder de bestaande uitvoeringsbeveiligingen. Een reset zonder actief plan vereist nog
  steeds een geldige nieuwe route voordat uitvoering wordt vrijgegeven.

## Verificatie

De nieuwe NOM-continuiteitstest faalde op dev.320 door de verwachte vervanging van
historisch NOM door alleen ontladen. De correctie laat dezelfde test slagen.
Tien gerichte tests slagen: reset met voorspelde kwartiertekorten, eenmalige correctie
van de dev.320-route, herstart/planbehoud, vijf typen vrijgegeven verplichtingen die niet
mogen terugkeren, beschadigde bronverwijzing en mislukte opslag/ontbrekende capability.

Offline herhaling van de echte invoer en store van 06:16:32 levert:

- `winner_selected / completed_day_execution_recovered`;
- nieuw plan `plan-d4aaed969623d05f`;
- alleen slim ontladen tot 09:00, aaneengesloten NOM 09:00-15:00, daarna alleen slim
  ontladen tot middernacht;
- oorspronkelijke route als bron en dev.320-resetroute als voorganger;
- na herstart `ready / plan_retained`, zonder nieuwe correctie of liveopdrachten.

Ruff en mypy voor de vier gewijzigde/nieuwe productiemodules zijn groen.
De lokaal beschikbare mypy-native-parser blijft onbruikbaar; de gewone parser is gebruikt,
zonder typechecks uit te schakelen.

Brede gerichte regressies: 72 geslaagd (herstel, reset, bridge, reserve en persistente
planherstelcontracten). Finale continuiteitssuite: 10 geslaagd; negen overlappen
met de brede suite. Totaal 73 unieke tests geslaagd.

## Ingebruikname

Versie opgehoogd naar dev.321 op expliciet releaseverzoek. Na installatie kan de
in de diagnose aangetroffen zuivere dev.320-resetroute automatisch worden gecorrigeerd;
een nieuwe planreset is daarvoor niet nodig. De oorspronkelijke diagnose en `sources/`
zijn ongewijzigd. Volledige release-CI en livecontrole volgen afzonderlijk.
