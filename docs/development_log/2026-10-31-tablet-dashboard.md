# Tablet-dashboard en tijdelijke kamertemperatuur

Status: lokaal ingebouwd; geen release, push of livewijziging. HC blijft dev.24.
Werkbasis: dev.324-bronkopie plan-explanation-fix. Op 31 oktober 2026 zijn
__main__.py, schedule.py, heating.py en config.json bytegelijk gecontroleerd met
de actuele GitHub-main-blobs (59e926bc, b5b0edb8, 8da66b6c, bb8dbe65).

## Wijzigingscontract

Alex heeft de zwarte tabletindeling goedgekeurd en opdracht gegeven deze lokaal
via PicoT te koppelen. Owning layers: HC-comfortinvoer (tijdelijk kamerdoel),
bestaande Heating/Control-regelcyclus en tabletprojectie. HC-ADR-014/015 scheiden
comfort van bronkeuze; HC-ADR-017 en het beneden-comfortlog van 22 oktober houden
apparaatopdrachten in de regelcyclus. HC-ADR-019 bepaalt verse sensormetingen.
HEMS-planning, financiën, dispatch, andere zones en bronbeveiligingen blijven
buiten scope. Er is geen wijziging in src/picot of Energy Devices.

De tijdelijke instelling wordt apart opgeslagen, met een vaste eindtijd op de
eerstvolgende begin/eindgrens. Zij vervangt alleen de actuele comfortvraag beneden.
Vensters en basisdoelen worden niet herschreven. Schemawijziging of expliciet
hervatten wist de tijdelijke keuze. Geen schema: wijzig het vaste thermostaatdoel.
Een herstart behoudt de keuze tot haar eindtijd; automatische regeling blijft de
bestaande opt-in/herstartregels volgen. Opslaan stuurt niet rechtstreeks apparaten.

Lerend voorverwarmen/afbouwen en een eerder gekozen energie-startrecept mogen
een actieve tijdelijke kamertemperatuur niet overschrijven. Een source override,
deurvoorwaarde, slechte meting of apparaatstoring blijft leidend. Adviesgeneratie
voor latere schemavensters blijft bestaan; uitvoeren van dat recept kan tijdens
de tijdelijke kamerkeuze niet het kamertarget vervangen.

## Lokale toegang en gegevens

HC serveert tablet.html plus twee externe assets en een begrensde API. Een apart
optioneel HTTP-listener op 8100 biedt uitsluitend tabletassets, snapshot,
temperatuur en kamerhervatten. Standaard uit, hostpoort niet gepubliceerd. Een
apart wachtwoord (minimaal 12 tekens) en CSRF blijven nodig; de HA-token staat
nooit in de pagina. HTTP is uitsluitend voor het vertrouwde eigen netwerk.
De bestaande ingress-beveiliging blijft intact.

Een opt-in read-only lezer haalt iedere vijf seconden de geconfigureerde
HA-energiebronnen op. De zes mappings zijn instelbaar en hebben dezelfde
uitgangsbronnen als de bestaande HEMS-configuratie. Dit is meetweergave, geen
HEMS-planner-/opdrachtpad. Bronleeftijd en eenheden worden gecontroleerd.
P1/PV/werkelijk laden/ontladen: maximaal 30 seconden; SOC maximaal 300 seconden.
Na verlies van de readerverbinding worden ook SOC/modus niet als actueel getoond.
Huisvermogen is afgeleid uit de actuele vermogensbalans. Niet-beschikbare of
tegenstrijdige gegevens blijven onbekend, ook 's nachts. Gemengde export is
neutraal; enige netafname bij laden is rood. Dit is bronindicatie, geen exacte
fysieke toedeling bij meerdere gelijktijdige bronnen.

Frontend: ES5 + XHR, geen externe dependencies of voorbeeldwaarden. Debounce en
één verzoek tegelijk; vijf seconden sinds de laatste tap het doel tonen.
Serverweigering/timeout wist optimistische waarden en toont de fout. Actuele
energiemetingen blijven afzonderlijk zichtbaar bij een ontbrekende klimaatmeting
of ontbrekende PV. Klok/hand, warmtevraag en weersymbool komen uit servergegevens.

## Verificatie

- 29 gerichte Python-tests en 23 subtests geslaagd (tablet, tijdelijke
  temperatuur, bestaande benedencomfortregeling), waaronder 7 backendtests
  inclusief echte HTTP-authenticatie en de productieassets.
- 17 JavaScript-gedragstests geslaagd; controles toegevoegd aan HC-CI.
- Brede HC-run: 451 tests en 53 subtests geslaagd; 2 fouten onderzocht.
  De vendored-notifiercontrole faalt identiek op de oorspronkelijke bronkopie
  door LF versus CRLF; beide bestanden zijn onaangeraakt. De weather redirect-
  test had WinError10053; afzonderlijk slaagt hij op zowel basis als wijziging.
  De brede run was dus niet volledig groen; Linux-CI moet voor release volgen.
- Ruff nieuwe backendmodule/tests geslaagd; bestaande HC gebruikt geen strikte
  Mypy-stap. Docker-build is lokaal niet uitgevoerd.
- Browser op 1024x768: opmaak, temperatuur wijzigen en terugkeer naar de gemeten
  waarde met handstatus gecontroleerd met een lokale testserver/voorbeelddata.
  Dit is geen bewijs van live HA of oude iPad Safari.

## Nog voor ingebruikname

HC-release/CI, installeren, tabletopties en lokale poort instellen; dan op de
fysieke iPad Safari testen. De eerder gedeelde chatgpt.site blijft de demo.
Geen echte HA- of apparaatopdracht is tijdens ontwikkeling uitgevoerd.

Rollback: tablet_enabled uit en poortmapping verwijderen stopt alleen tablettoegang.
Code terugzetten naar dev.24 negeert de nieuwe tijdelijke kamertemperatuur en
herstelt het bestaande schema; controleer actieve apparaatstanden. Bestaande
schemaformat-4-velden zijn niet destructief gemigreerd.

## Releaseopdracht

Alex heeft publicatie als HC 0.1.0-dev.25 aangevraagd. De negen bestaande
wijzigingsbestanden zijn tegen de actuele main-tree gecontroleerd (na normalisatie
van lokale CRLF); alle basishashes komen overeen. Basis is
58bf87278ae88cee0a5dab6a720da9ac1a75ded6. HEMS blijft dev.324.
Linux-CI moet voor merge slagen. Installatie en iPad-controle volgen afzonderlijk.

## Linux-CI bevinding en correctie

De eerste PR-run toont 454 geslaagde HC-tests en één fout: de vendored
meldingsmodule loopt achter bij de gedeelde main-versie. De lokale regeleinden
verborgen eerder ook dit inhoudelijke verschil; de oorspronkelijke conclusie
"alleen LF/CRLF" was dus onvolledig. De actuele gedeelde module ondersteunt
optionele oorzaak-fingerprints; HC gaf en geeft die parameter niet mee.
Voor deze release is de HC-kopie exact gelijkgetrokken met de bestaande
src/picot/health_notifications.py uit main. De gedeelde bron zelf wordt niet
gewijzigd of teruggezet. Bestaande HC-meldingsaanroepen behouden hun gedrag.
