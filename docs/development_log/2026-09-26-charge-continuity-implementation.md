# Fix 2 — herstelopties bij lopend netladen en juiste schakelreden

Alex heeft op 26 september 2026 om 21:34 Europe/Amsterdam akkoord gegeven op
deze beperkte reparatie na het afzonderlijke onderzoek. Basis: dev.271,
`b5920fc046858fa07aaf2edaa91fb4c6160f1bad`. Branch:
`fix/charge-continuity-candidates`. Alex heeft om 21:50 Europe/Amsterdam akkoord
gegeven op afzonderlijke publicatie als dev.272 via PR en automatische controles.
Status: releasevoorbereiding; installatie en liveverificatie volgen afzonderlijk.

## Verandercontract

Eerste onjuiste grens: Candidate Generation stopt na PV-opties, waarna de
adapter al die opties afwijst wegens laadcontinuïteit. De mogelijkheden voor
een geldig herstel met behoud of verlenging van het netlaadblok ontbreken.
Daarnaast gaat bij de verse uitvoeringswaarneming de uitvoeringsreden verloren;
de schakeltabel gebruikt daardoor de plankeuzereden.

ADR-037.15, ADR-024/031/032, V2ADR-061 en het canonieke pipelinecontract blijven
leidend. De eerste wijziging hoort bij kandidaatconstructie en haar invoeradapter.
De tweede draagt bestaand uitvoeringsbewijs over aan diagnose en schakelhistorie.
Evaluation, Plan Builder, Store, dispatchbeleid, BMS/vermogen, de vijftienminuten-
belastingprojectie, financiële rekenregels en het financiële tabblad zijn buiten
scope. Werkelijk 100%, reserve, bestaande markt-/andere dagverplichtingen,
handmatige override en oorspronkelijke planherkomst blijven vereist.

Terugvalgrens: de twee bronwijzigingen en hun tests. Uitvoeringsplannen en de
Store houden hetzelfde formaat; alleen een optioneel diagnostisch veld komt
erbij. Dev.268 blijft Alex' afzonderlijk afgesproken operationele terugvalbasis,
met de eerder beschreven gegevensback-upvoorwaarde uit de dev.271-release.

## Implementatie

De adapter bepaalt de reeds bestaande beschermde eindtijd vóór de zoekopdracht
en neemt die exacte grens op in de fysieke tijdlijn. De discoverer krijgt deze
als `required_grid_until` en behoudt dat netlaadgedeelte in iedere proef. Een
berekend toekomstig 100%-punt mag het beschermde blok niet verkorten: de bestaande
vrijgave op werkelijk waargenomen 100% blijft bij de adapter.

Naast behoud van het laadgedeelte plus latere NOM worden ononderbroken
verlengingen vanaf de actuele tijd aangeboden, tot een simulatie tijdens die
laadactie vol raakt of een beschermd interval de actie begrenst. Geen nieuwe
latere herstart van het lopende laadblok, geen overschrijven van marktsegmenten
en geen financieel gekozen winnaar binnen de discoverer. Zonder actieve
continuïteitsvoorwaarde blijft de bestaande kandidaatconstructie ongewijzigd.
De adapter behoudt ook zijn eindcontrole op continuïteit.

`apply_committed` draagt de reden van de bestaande uitvoeringsgrens over als
`ExecutionPrimitiveBoundary.execution_reason`. Specifieke marktstopredenen
blijven behouden; een gewone grens gebruikt dezelfde tekst als de zelfstandige
klokuitvoering. De schakelhistorie gebruikt die uitvoeringsreden wanneer deze
aanwezig is. De oorspronkelijke EvaluationRecord en plankeuzereden blijven
ongewijzigd beschikbaar. Er is geen andere primitive of opdracht gekozen door
deze registratiecorrectie.

## Historische canonieke replay

Drie originele snapshots doorliepen de volledige pipeline met geïsoleerde
stores, vastgelegde invoer en conversie, slijtage 0 en apparaatbesturing uit.
Dezelfde herkomstherstelprocedure als bij dev.271; toekomstige mutable toestand
is niet uit het eindarchief teruggeprojecteerd. Iedere replay staat op zichzelf.

| Snapshot | Kandidaten | Gekozen eerste laadblok | Marktroute |
| --- | ---: | --- | --- |
| 15:23:49 | 66 | Doorladen tot 15:38:49 | Ingekort door bestaande financiële selectie |
| 15:25:22 | 66 | Doorladen tot 15:40:22 | Ingekort door bestaande financiële selectie |
| 15:30:35 | 306 | Netladen tot 15:45 | Behouden door bestaande financiële selectie |

De eerste twee snapshots liepen oorspronkelijk vast op kandidaatuitputting.
Ze leveren nu een canoniek geselecteerde, opgeslagen revisie zonder de
onderbreking op de oude grens van 15:25:30. Bij alle drie is het herladen plan
na herstart identiek en zijn bestaande voltooide dagdoelen behouden. Lokale
replaytijden circa 5,2 / 5,2 / 13,5 seconden zijn geen NUC-runtimegarantie.

Dit is geen doorlopende fictieve daguitvoering: na een andere beslissing zouden
latere SOC-metingen anders zijn geweest. Het bewijst herstel op die invoer en
geen garantie dat bij alle toekomstige meetafwijkingen nooit meer wordt geschakeld.

## Verificatie

- Twee nieuwe adapterregressies faalden vóór herstel op
  `ongoing_load_requires_committed_grid_continuity` (actieve en onbekende belasting).
- De nieuwe ketentest voor een tijdens berekening verstreken segmentgrens faalde
  vóór herstel omdat de schakelhistorie de plankeuzereden gebruikte.
- Gerichte groepen: 23 kandidaat-/belastingtests, 29 uitvoerings-/historietests
  en 44 selectie-/markt-/continuïteitstests geslaagd.
- Extra grenzen: voorspeld vol verkort geen beschermd blok; andere beschermde
  intervallen worden niet overschreven; ontoereikend vermogen blijft onhaalbaar.
- Ruff op alle broncode, v2-tests en gewijzigde/nieuwe tests: schoon.
- Volledige Mypy CI-selectie: 263 bron-/testbestanden zonder fouten. De bestaande
  lokale Mypy-cache gaf een bewezen SQLite-corruptiefout; dezelfde controle is
  geslaagd met een afzonderlijke verse cache, zonder bron- of dependencywijziging.
- Volledige pytest-suite: **1761 geslaagd, 1 optioneel overgeslagen**. Alle 263
  testbestanden precies eenmaal verdeeld over vier geïsoleerde processen:
  440 + 507 + 414 + 400 geslaagd; alle exitcodes 0. Langste groep 192,57 s.
  De optionele skip vereist de niet beschikbare afzonderlijke diagnosefixture
  van 19 september via `PICOT_TEST_DIAGNOSTIC`; de drie bovenstaande replays
  gebruiken de wel beschikbare diagnose van 26 september.
- `git diff --check`: schoon. Geen functionele wijziging na deze controles.

Vingerafdruk van alle Python-bron- en testbestanden vóór de releaseversieverhoging
(gesorteerd pad, nulbyte, inhoud, nulbyte), SHA-256:
`cc5132b51530eaaa3e993e287d69a466697cbd14b7294b22292a6ded6ff19912`.

Acceptatie: kandidaatuitputting door de laat toegepaste continuïteitsvoorwaarde
is gerepareerd; behoud en verlenging zijn canoniek te selecteren. De uitvoering
houdt haar bestaande tijdgrenzen en de historie toont de daarbij behorende reden.
Replays, herstartcontrole, volledige regressies, architectuurtests en statische
controles slagen. Installatie en werking op de NUC zijn nog niet geverifieerd.

## Release dev.272

Na Alex' releaseakkoord is alleen de versie in runtime, add-onmanifest en
versietest verhoogd; de changelog beschrijft de twee goedgekeurde correcties.
De functionele broncode is sinds de volledige verificatie niet gewijzigd.
Na de versieverhoging: alle 11 versie-/add-oncontroles geslaagd; Ruff en
`git diff --check` schoon.
Publicatie verloopt via een afzonderlijke PR, groene automatische controles
en samenvoegen naar main. Er is geen nieuw opslagformaat of beleidswijziging.

Het financiële tabblad blijft het afzonderlijke derde herstelpunt uit
`2026-09-26-financial-tab-triage.md`.
