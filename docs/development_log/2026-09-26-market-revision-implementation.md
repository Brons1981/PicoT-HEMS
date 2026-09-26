# Financiële marktrevisie — lokale implementatie

Datum: 26 september 2026. Alex gaf om 19:55 Europe/Amsterdam akkoord op het
implementatieplan. Basis: dev.270 (`db9aa739`), branch
`fix/bridge-nom-export-target`. Besluit: [ADR-019.5](../architecture/ADR-019.5-financial-market-revision.md).
Status: lokaal geïmplementeerd en geverifieerd; dev.271 voorbereid na Alex’
publicatieakkoord om 20:50 Europe/Amsterdam. Publicatie via PR en CI;
installatie/livebewijs volgen afzonderlijk. Dev.268 blijft de afgesproken operationele terugvalbasis.

## Gedrag en eigenaarschap

De oorspronkelijke intentiefout is hersteld: omzetting van export naar NOM wist
ook het expliciete exportdoel. De regressie gebruikt de 504,5251533820346 Wh uit
het zaterdagincident. De domeinvalidatie blijft inconsistenties afwijzen.

Bij een bestaande toegelaten herplanning maakt MEP alternatieven voor behoud,
inkorten en verwijderen van de betrokken marktopdracht, met toegelaten
overbruggings-/laadvarianten. Behoud met aanvullend laden doet mee. Een nog niet
begonnen exportvenster kan aan beide randen worden ingekort. Een begonnen actie
kan korter doorlopen, maar wordt niet gepauzeerd en later als tweede actie gestart.
Andere vastgelegde markt- en laadopdrachten behouden hun eigenaarschap.

De bestaande simulator en afrekening rekenen vanaf hetzelfde actuele snapshot
tot het einde van morgen in Europe/Amsterdam. Dit kan maximaal 49 uur omvatten
rond wintertijd. Een korter oud plan kapt beschikbare financiële dekking niet af.
Buiten de oude planhorizon geldt de bestaande expliciete voortzetting met
huishoudondersteuning; een incumbent zonder volledige plandekking krijgt een
afwijsreden. Reeds gemaakte kosten en opbrengsten tellen niet opnieuw mee.

Evaluation kiest uit geldige, vergelijkbare complete paden op exportopbrengsten
minus importkosten en ingestelde slijtage. Per dag blijven de bedragen zichtbaar.
PV, verdrongen eigen verbruik en conversieverliezen zitten in de fysieke stromen.
De slijtageterm gebruikt de ingestelde EUR/kWh op batterijonttrekking, inclusief
ontlaadverlies. Gewone laadselectie buiten deze vergelijking houdt haar bestaande
maatstaf. Bij gelijkwaardige uitkomsten blijft de geldige incumbent behouden.

De eindvoorraad moet gelijkwaardig zijn. Bij een geldig oud plan is zijn opnieuw
gesimuleerde eindvoorraad de referentie. Bij een ongeldig oud doel wordt een
gemeenschappelijke fysiek haalbare voorraad uit de herstelkandidaten gebruikt;
het oude onhaalbare doel mag niet alle herstelplannen blokkeren. Afwijkende
eindvoorraad krijgt een expliciete reden waarom financieel vergelijken nog niet
kan; er is geen verzonnen restwaarde of afzonderlijk herstelprijsmodel toegevoegd.

Ontbrekende vereiste prijzen/prognoses bewijzen geen financiële besparing.
Onvolledige dekking kan een gewone laadreparatie met behouden export toelaten,
maar geen financiële exportwijziging. Ontbreekt alleen prognosedekking voorbij
een nog geldig bestaand plan, dan wordt diens volledige horizon opnieuw
gevalideerd. Een werkelijk onhaalbaar plan wordt niet alsnog geldig verklaard.
De bestaande bescherming van een lopende laadsessie blijft ook gelden als alle
marktvarianten precies op die continuïteitsvoorwaarde stranden.

Ook een nog ongebonden dagdoel binnen de vergelijkingshorizon maakt de financiële
onderbouwing onvolledig. Dat doel en zijn laadkosten mogen niet gratis worden
weggelaten. De gewone herstelroute kan met behouden export doorgaan; de bestaande
volgende planningsronde legt het afzonderlijke dagdoel vast. Het bewijs noemt
expliciet welke dagopdracht nog geen plan heeft en claimt geen vergelijkbaar EUR-resultaat.

## Publicatie, historie en uitleg

De Plan Builder vertaalt het canonieke winnende pad. `MarketPlanRevision` verbindt
de vorige binding, actuele eigenaar, hetzelfde snapshot, EvaluationRecord en
winnend energiepad met de nieuwe binding of expliciete verwijdering. De Store
controleert dit en schrijft plan, bindings en historie atomair. Zonder dat
revisiebewijs blijft ongemerkt verlies van export verboden.

Oorspronkelijk exportbudget, verstreken gepland volume, geannuleerd volume,
resterend planvolume en gemeten export blijven afzonderlijk. Herhalen/herstarten
vernieuwt geen dagbudget. Vooraf verwijderen sluit als `skipped`; verwijderen
tijdens een begonnen of nog onbevestigde uitvoering houdt de stopwaarneming aan.
De uitvoeringsbewaking volgt de nieuwe tijdgrenzen en het goedgekeurde volume,
met de oorspronkelijke herkomst voor metingen.

De UI toont het canonieke financiële bewijs van winnaar en verliezers. Bij een
volgende poll zonder nieuwe vergelijking blijft dit alleen zichtbaar voor exact
hetzelfde uitvoeringsplan, met oorspronkelijk tijdstip en het label dat niet
opnieuw is berekend. Na herstart is die UI-cache leeg; de diagnosehistorie blijft.

Marktincidenten gebruiken expliciet `market-revision-compact:v1`: volledige
replay-input/evaluatie, volledige paden van winnaar en incumbent, alle overige
kandidaatidentiteiten, financiële uitkomsten en afwijsredenen. Overige volledige
paden worden expliciet als weggelaten geteld. Herhaalde evidence-ID-reeksen zijn
verliesvrij via een dictionary terug te bouwen. De echte writer bewaart de
4007-kandidatentest in 6.65 MB, onder zijn bestaande limiet van 8 MiB. Normale
incidenten houden hun bestaande formaat.

## Historische replay

Drie originele snapshots zijn via de echte canonieke pipeline opnieuw verwerkt
in geïsoleerde tijdelijke stores, met apparaatbesturing uitgeschakeld. Actuele
opdrachten, actieve verwijzingen, uitvoeringsvoortgang en prognoses kwamen uit
ieder afzonderlijk snapshot. Het eindarchief leverde uitsluitend al bestaande
onveranderlijke planherkomst en marktregelidentiteit; geen latere uitvoering
werd teruggeprojecteerd. Bestaande tarief-/conversiemodellen, ingestelde slijtage
0 EUR/kWh, geen nieuwe markttoelating tijdens deze replay.

| Snapshot, lokale tijd | Uitkomst | Bewijs |
| --- | --- | --- |
| 25 september 13:21:55 | Bestaand plan behouden | Geen nieuwe materiële trigger; geen onnodige kandidatenberekening. |
| 25 september 19:30:47 | Bestaand plan behouden | Dezelfde uitvoeringsbeslissing als het oorspronkelijke snapshot. |
| 26 september 16:29:47 | Financieel gekozen herstel met behoud marktroute | 1615 alternatieven; intentiefout verdwenen; geen NOM-terugval. |

Voor zaterdag, vanaf 16:29:47 tot einde zondag:

| Beste geldige variant | Verwacht gezamenlijk resultaat |
| --- | ---: |
| Behoud marktroute | +0,726127 EUR |
| Inkorten marktroute | +0,670591 EUR |
| Verwijderen marktroute | +0,260786 EUR |

Behoud levert in deze vergelijking **0,465341 EUR meer dan verwijderen** op.
De gekozen route heeft 6035,263 Wh netladen, 4111,731 Wh eindvoorraad en 816 Wh
minimumvoorraad. Ten opzichte van het opnieuw doorgerekende oorspronkelijke plan
is het voordeel 0,005736 EUR. Voltooide dagdoelen bleven intact; de opgeslagen
uitkomst bleef na herstart gelijk. De dagbedragen zijn 0 EUR import en 0,805619 EUR
export op zaterdag, 0,833793 EUR import en 0,754302 EUR export op zondag.

Dit is prognosebewijs voor deze afzonderlijke snapshots, geen gemeten winst of
optelbare weekbesparing. De eerder gedocumenteerde tweepadsvergelijking hield
andere vensters vast; de nieuwe vergelijking omvat ook inkorten en extra laden.
Voor 22–24 september ontbreken volledige vergelijkbare snapshots in de ZIP.

De zoekruimte is eindig en bestaat uit uitvoerbare aaneengesloten exportdelen
en bestaande laad-/brugfamilies. Technische binaire zoekproeven voor minimale
laadduur worden wel gesimuleerd, maar niet als afzonderlijke financiële plannen
opgeslagen. Ongewijzigde simulatiebasis en exacte afrekenintervallen worden
hergebruikt. De zaterdagrun hield dezelfde beste bedragen en daalde van 4007 naar
1615 gepubliceerde kandidaten; de laatste rekentijd was 41,7 s tijdens gelijktijdige
tests. Dit is geen runtimegarantie voor het Home Assistant-apparaat en geen bewijs
van een wiskundig globaal optimum buiten de gegenereerde families.

## Verificatie

- Volledige suite op de definitieve code: **1755 geslaagd, 1 optioneel overgeslagen**.
  Alle 262 testbestanden precies eenmaal verdeeld over vier onafhankelijke
  pytest-processen: 490 + 433 + 425 + 407 geslaagd. Alle processen exitcode 0;
  langste groep 190,25 s. De architectuur- en end-to-endtests zitten in deze suite.

- Ruff: volledige CI-selectie, alle broncode en gewijzigde/nieuwe tests schoon.
- Mypy: volledige CI-selectie, 263 bron-/testbestanden zonder fouten.
- `git diff --check`: schoon.
- Canonieke replays op de definitieve code: beide vrijdagplannen behouden;
  zaterdag 1615 alternatieven, geen fallback, dezelfde financiële bedragen.
- Gerichte dekking: financieel behoud/inkorten aan beide randen/verwijderen;
  onhaalbaar bestaand 100%-doel met geldig herstel; ontbrekende prijzen en
  forecasts; ongebonden doel voor morgen en vervolgplanning; behoud actieve
  laadcontinuïteit; 37-uursplanprojectie en herstel na exportverwijdering;
  atomaire opslag/schrijffout/idempotentie/herstart; gewijzigde uitvoeringsgrens;
  canonieke projectie/UI en begrensde incidentopslag.

De optionele skip betreft de afzonderlijke diagnostische fixture van
19 september (`PICOT_TEST_DIAGNOSTIC`), die niet beschikbaar is. Dat is een
andere fixture dan de drie hierboven uitgevoerde vrijdag-/zaterdagreplays.

Verificatievingerafdruk van alle Python-bron- en testbestanden (pad plus inhoud,
gesorteerd): `add98c5c80c00c5d2e7b5fe95c9b80d62d55e21e80aae19d193108128935cd43`.
Na deze controles zijn alleen documentatiestatussen bijgewerkt.

## Release dev.271

Alex heeft bevestigd deze wijziging eerst afzonderlijk live te brengen en daarna
het andere schakelpunt te onderzoeken. HEMS-manifest en Python-versie zijn samen
verhoogd naar `2.0.0-dev.271`; het add-onchangelog beschrijft deze scope.
De functionele bron-/testinhoud is vóór de versieverhoging gecontroleerd tegen
bovenstaande verificatievingerafdruk en was identiek. De versieverhoging krijgt
een eigen pakket-/versiecontrole; PR- en main-CI bewaken de gepubliceerde code.
Installatie door Alex en een nieuwe diagnose moeten livewerking aantonen.

Verse lokale releasecontrole op dev.271: 27 versie-/pakket-, canonieke pipeline-
en architectuurtests geslaagd; Ruff op alle broncode en de bijgewerkte versietest
schoon, evenals `git diff --check`. De expliciete versietest is gelijk met het
manifest en de pakketversie naar dev.271 bijgewerkt.

De schakelregistratie van 15:25 is alleen onderzocht in het eerdere incidentlog.
Deze wijziging introduceert geen nieuw schakelbeleid of gewijzigd label daarvoor.
