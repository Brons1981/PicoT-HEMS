# HC-ADR-015 — Eenvoudige comfortvensters

Status: geaccepteerd door Alex op 2026-09-14; vervangt alleen de vensterinvoer en
bandsemantiek van HC-ADR-014. De overige bron-, override- en tijdregels blijven gelden.

## Besluit

Alleen beneden heeft meerdere vensters per dag. Elk venster bevat dagen, begin,
einde, één temperatuur en een comfortvinkje. De editor groepeert identieke vensters
voor meerdere dagen, biedt daggroepen en dupliceren. Opslag blijft per begindag;
uitvouwen mag maximaal 112 vensters opleveren. Overlap blijft verboden.

Comfort aangevinkt: temperatuur bij aanvang bereiken en aanhouden; geen economische
afwijking (afgeleid minimum = maximum = doel). Regeltechnische hysterese is geen
optimalisatieband en wordt pas bij de toekomstige uitvoering ontworpen.
Comfort uit: doel ± één centrale band, instelbaar 0–5 °C (initieel 1 °C), begrensd
op de bestaande absolute 5–35 °C. Geen eigen min/max per venster. Algemene zonegrenzen
blijven bestaan en conflicten worden gerapporteerd. Boven en badkamer blijven vast.

## Opslag en uitvoering

Formaat 3 bewaart de band en per venster day/start/end/target/hard; min/max worden
alleen voor plannerinvoer afgeleid. Dev.10-formaat 2 wordt atomair gearchiveerd onder
archive-id 2. Dagen/tijden/doelen/vinkjes en overrides blijven intact. Veranderen de
grenzen, dan uitschakelen met zichtbare controlemelding. Migratie is eenmalig en
verhoogt de revisie. Terugval naar dev.10 vereist de bijbehorende HC-databack-up.

De owning layer is HC-comfortinvoer plus editor. Geen wijziging aan HEMS, handmatige
bronbediening of financiële uitvoering. Opslaan en migratie sturen geen apparaten.

## Bewijs

Python: band, exact comfort, validatie, migratie/herstart/archief en bestaande
comfort-, DST-, override- en API-regressies. Browser: daggroepen, dupliceren,
meerdere vensters, bewaren/herladen, conceptbehoud, handmatige bediening en mobiel.
