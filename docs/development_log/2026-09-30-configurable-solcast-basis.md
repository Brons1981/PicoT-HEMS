# Instelbare Solcast-basis — 30 september 2026

Alex heeft een instelbare prognose aangevraagd: lower, gemiddelde lower–central,
central en upper. Geen release aangevraagd. Basis dev.282, lokale branch
feat/solcast-planning-basis. De automatische central-failsafe blijft uitgesteld.

De add-onoptie solcast_planning_basis wordt opgenomen in Planning Input en diens
identiteit. ScenarioTimeline draagt de keuze als metadata; de originele waarden
blijven intact. De bestaande gedeelde fysieke simulatie kiest de betreffende
energie vóór laadvermogensbegrenzing. Alle actieve dagplannerberekeningen via
het inputadapterpad gebruiken deze keuze, inclusief verkorting, herstel en
waardering. Standaard blijft mean-lower-central met dezelfde rekenmethode.

Nieuwe Execution Plans bewaren de keuze; deserialisatie van oudere records
zonder veld behoudt het gemiddelde. Diagnose/UI gebruikt het kandidaatlabel
voor de actieve dagplanner. De optie alleen vervangt geen commitment: na
opslaan en herstarten vraagt de gebruiker herberekening via de bestaande knop.
De legacy lower-uitstelcontrole is niet gewijzigd.

Verse verificatie:
- 279 tests geslaagd: daily_main, market, versie, independent daily simulator en
  intent simulator, plus Zendure planning input. Duur 273 seconden.
- 29 gerichte tests geslaagd vóór extra achterwaartse-compatibiliteitstest;
  aansluitend alle 9 active-pipeline tests inclusief die extra test geslaagd.
- 40 web-UI tests geslaagd.
- Alle 4 inputassemblagetests geslaagd, inclusief keuzedoorgifte, afzonderlijke
  snapshotidentiteiten en standaard bij ontbrekende optie.
- Ruff op gewijzigde Python-bestanden geslaagd; mypy op 6 planner/inputmodules
  en afzonderlijk web_ui en execution_plan geslaagd; diff-check geslaagd.
- De nieuwe keuzetests tegen dev.282 falen op het ontbrekende planning_basis-veld.

Geen publicatie, versieophoging, installatie of livevalidatie uitgevoerd.
De echte dag van Alex is nog niet opnieuw doorgerekend met deze implementatie.

## Releaseaanvraag

Alex heeft op 30 september 2026 release dev.283 aangevraagd via PR en CI.
Installatie en livecontrole volgen afzonderlijk.
