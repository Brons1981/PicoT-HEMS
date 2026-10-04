# 2026-10-04 - korte meetgaten in lopende marktroute

Status: IMPLEMENTED; release dev.285 aangevraagd. CI en livevalidatie nog open.
Baseline: main 8142d8aec0138dbfa7c232616b117561abdb6e08, HEMS dev.284.
Releasebranch: fix/market-export-recovered-gap.

## Bewijs en reparatie

ZIP picot-diagnostics - 2026-10-04T201906.832.zip: werkelijk gestart 19:15:52,
Zendure-ontlaadsensor NaN van 19:20:24.833124 tot 19:20:25.819761 Europe/Amsterdam.
Shelly bleef circa 2,1 kW export melden. Stopverzoek 19:21:09, afgesloten 19:21:35.
Eerste verkeerde grens: het korte herstelde gat maakte alle export ongeldig;
de execution guard gebruikte dat als definitieve stopreden.

BoundedMarketExport houdt geldige meting, schatting en ontbrekende-exportbovengrens
apart. Maximaal 2 seconden per hersteld gat, totaal maximaal 5 Wh onzekerheid.
De guard gebruikt de bovengrens voor het budget en bewaart kwaliteitsvelden in
MarketExecutionProgress via de bestaande store. Geen planner/EV/marktselectiewijziging.
De strikt gemeten exportinterface blijft ongewijzigd; voltooide oude opdrachten
worden niet heropend. ADR-019.10 legt de goedgekeurde grens vast.

## Verse verificatie

- Voor fix: regressie met 0,986637 seconde hersteld gat faalt op onterechte NOM.
- Na fix: 75 gerichte en aangrenzende tests slagen, inclusief store, herstart,
  afsluiting, vervangende acties, marktwijzigingen en actieve hoofdlaadketen.
- Ruff en strikte mypy op de gewijzigde modules slagen; patch en diff gecontroleerd.
- Exacte diagnose-replay: oude strikte meting None; nieuwe meting 181,691519 Wh
  geldig en 0,576205 Wh apart geschat/met dezelfde onzekerheidsbovengrens.
- Versiecontrole en CI op releasecommit volgen voor samenvoegen.

## Grenzen en volgende stap

Geen live-installatie of HA-herstart uitgevoerd. Eerst PR/CI en publicatie dev.285,
dan installatie door Alex en verse diagnose tijdens de volgende marktroute.
Historie, dagdoelen, marktbudget en laadplanning behouden. Eerste terugvalbasis
blijft dev.268; oudere loaders kunnen nieuwe voortgangsvelden niet lezen.
