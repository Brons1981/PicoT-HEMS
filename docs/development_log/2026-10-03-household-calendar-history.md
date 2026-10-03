# Doorlopende huisverbruikshistorie per kalenderdag — 3 oktober 2026

Status: lokaal gebouwd en geverifieerd, geen release/push/live-installatie.
Basis main `3c6aff42b06ca6ecd86f94607b09d00b24103cfe`, HEMS dev.283.
Branch `feat/household-calendar-history`.
Contract: ADR-037.22; Alex vraagt registratie naast de huidige methode, met
bestaande historie, om weekdagen en weekenden te vergelijken vóór plannergebruik.

## Resultaat

- Aparte `picot_v2_household_calendar.sqlite`: oorspronkelijke Nederlandse
  kalenderdagen, weekdagen/ISO-weken en klokkwartieren, UTC-identiteit/fold,
  aantallen metingen, samplegemiddelden, geïntegreerde energie en meetdekking.
- Bron: uitsluitend het bestaande `picot_v2_household_load_history.jsonl` met
  geldige canonieke huisverbruiksmetingen. Geen nieuwe HA-history-opvragen.
  De oorspronkelijke bron en alle planner-/Solcastregels blijven gelijk.
- Automatische hervatbare aanvulling vanaf de eerste bestaande meting; maximaal
  512 regels per transactie. Checkpoint en energie worden samen gecommit.
  Herstart, gedeeltelijke regels, bronrotatie en oude/duplicate tijden worden
  expliciet behandeld. Rotatie geldt als onderbreking, zonder geraden brug.
- Lineaire integratie tussen opeenvolgende metingen, maximaal 180 seconden.
  Langere gaten, corrupte regels en open-daggrenzen worden niet opgevuld.
- Eigen proces met 128 MiB adresruimte, nice 10, 128 MiB databasegrens,
  128 MiB vrije-ruimtereserve; één seconde tussen backfillbatches, daarna
  60 seconden polling. Publicatie maximaal elke 15 minuten plus eerste rapport
  en het bereiken van de staart. Een overleden observer wordt maximaal eenmaal
  per vijf minuten opnieuw gestart; geen herplanning en niet wachten op verwerking.
- Optie `household_calendar_history_enabled` standaard true, ook wanneer zij
  ontbreekt in oudere options. False stopt de nieuwe aansluiting na herstart.
  De oude snapshot-captureproef blijft afzonderlijk en standaard false.
- Atomair JSON-rapport `picot_v2_household_calendar.json` in de diagnose-ZIP.
  Maximaal 112 recente dagen in het rapport; oudere kwartieren blijven in SQLite.
  Zeven weekdagprofielen en werkdag/weekendprofielen over de laatste acht weken.
- Tab Historie toont automatische aanvulling, weekdag/dagtypegemiddelden,
  medianen, meetdekking, beperkte dagsommen en retrospectieve modelnacontrole.
  Alleen afgesloten dagen met >=95% dekking tellen in de daggemiddelden mee.
  Meetenergie wordt niet naar 24 uur opgeschaald. Een oud rapport wordt gemeld.
- De aparte read-only API leest een begrensd gepubliceerd rapport, zonder de
  SQLite-writer of een planningsrun nodig te hebben. Grote kwartierdetails blijven
  in de ZIP; geen vergroting van het canonieke dashboardpayload.

## Vergelijking en grenzen

Het huidige gewogen klokkwartiermodel, dezelfde weekdag en werkdag/weekend
worden retrospectief vergeleken. Elke doelwaarde gebruikt uitsluitend eerdere
kalenderdagen. Maximaal zeven geldige perioden, minimaal twee. Het huidige model
behoudt zijn veertiendagenvenster en sampleweging; de alternatieven hebben een
achtwekenvenster. Herhaalde wintertijdkwartieren tellen als één brondag.
Alle modellen worden op dezelfde voldoende gedekte doelkwartieren beoordeeld.
Absolute fout en signed bias zijn afzonderlijk zichtbaar.

Dit zijn geen vastgelegde oorspronkelijke livevoorspellingen, kandidaatplannen
of financiële besparingen. Geen nieuwe actieve plannerinput. Totaal huisverbruik
kan geen apparaten herkennen; EV-laden/wassen/drogen zijn inbegrepen voor zover
de bestaande balans ze bevat. Seizoen, vakantie en gebeurtenissen zijn nog geen
aparte classificaties. De eerste resultaten zijn een kleine bruikbare steekproef.

## Verse verificatie

`pytest -q` op kalenderhistorie, web/UI/HTTP, diagnose-export, huidige historie en
prognose, capturetrial, architectuureigenaarschap, live compositie/PV/pollcyclus,
versies, material replanning, execution evidence en beide canonieke pipelines:
**193 geslaagd in 61,07 seconden**.

Gedekt: hervatting zonder extra energie, transactie-interruptie, rotatie,
onvolledige regel, corruptie/lange gaten, 92/100-kwartierdagen, werkelijk toekomstige
data zonder leakage naar eerdere nacontrole, exact gelijk baselinekwartier aan
de bestaande forecaster, workerstart/foutisolatie/backoff, ontbreken van
Supervisor-token bij lanceren, atomair publiceren en afzonderlijke HTTP/ZIP-uitvoer.

`ruff check src/picot` plus nieuwe/gewijzigde gecontroleerde tests: geslaagd.
`mypy src/picot`: geslaagd, **239 bronbestanden**. `git diff --check`: geslaagd.
De echte observer-CLI publiceert onder de eigen proceslimiet een geldig rapport;
workerlog bevestigt adresruimte 134.217.728 bytes en nice 10, zonder stderr.
Dit is ontwikkelomgevingsbewijs, geen NUC-belastingsmeting.

HTTP-route en JavaScript-syntax zijn getest. Een browser-screenshotcontrole kon
niet worden uitgevoerd: de aanwezige Playwright-package heeft geen browserbinary.
Er is geen browser of dependency geïnstalleerd.

## Echte ZIP van Alex

`picot-diagnostics - 2026-10-03T074347.717.zip`, huisverbruiksbestand van
14 augustus t/m 3 oktober: **52.828 metingen, 51 dagen**. In 104 begrensde
transacties verwerkt, geen afgewezen/oude records. **4.441 kwartieren**, SQLite
528.384 bytes, JSON 1.981.809 bytes. Aanvulling plus twee rapportberekeningen
1,106 seconden in de ontwikkelomgeving (zonder live throttling).
SQLite-integriteitscontrole `ok`; SHA-256 van de bron blijft identiek.

Alleen dagen met >=95% dekking en afgesloten vóór 3 oktober:

| Type | Bruikbare dagen | Gemiddeld gemeten | Gemiddelde dekking |
|---|---:|---:|---:|
| Werkdag | 11 | 6,252 kWh | 96,83% |
| Weekend | 6 | 13,322 kWh | 97,92% |

Over 2.301 gemeenschappelijk bruikbare kwartieren:

| Model | Gemiddelde absolute kwartierfout | Gemiddelde signed fout |
|---|---:|---:|
| Huidig klokkwartier | 47,419 Wh | -3,833 Wh |
| Dezelfde weekdag | 42,883 Wh | -11,195 Wh |
| Werkdag/weekend | 38,867 Wh | -7,455 Wh |

Werkdag/weekend geeft circa 18% lagere absolute kwartierfout in deze nacontrole,
maar iets meer onderschatting. Geen conclusie over laadgedrag/kosten of universele
modelkeuze. De huidige planner blijft gebruiken wat hij nu gebruikt.

## Publicatie en livebewijs

Geen versieophoging, commit, push, PR, release of installatie uitgevoerd.
Na een afzonderlijke release/installatie start registratie automatisch; geen
handmatige diagnose-import of inschakelen van de capturetrial nodig. De aanwezige
NUC-bron wordt dan lokaal ingelezen, niet vervangen door de ontwikkelkopie.
Na installatie: diagnose met calendar-JSON en `caught_up=true` controleren,
nieuwe metingen/herstart bekijken en NUC-runtimebelasting beoordelen.

## Releaseaanvraag

Alex heeft op 3 oktober 2026 om 08:51 Europe/Amsterdam release aangevraagd.
Publicatie als dev.284 via PR en CI; installatie en liveverificatie volgen apart.
