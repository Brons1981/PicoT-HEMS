# Verificatie 0.1.0-dev.1

13 september 2026. Ontwikkelpakket, geen live release.

## Bevestigd

- Python 3.12: `python3 -m unittest discover -s tests -v`.
- Ontbrekende en ongeldige sensoren worden geen nulmetingen; echte nul blijft geldig.
- Validatie temperatuur-/vochtgrenzen en Supervisor-opties zonder temperatuurdefaults.
- Prijsintervalverwerking: negatieve prijzen, kwartieren, expliciete tijdzones, EUR/MWh-conversie, gaten, afwijzen van overlap en ambigue tijd.
- SQLite-opslag overleeft opnieuw openen; bewaartermijn ruimt oudere rijen op.
- Lokale HTTP-integratietest: GET naar gesimuleerde HA-server, registratie, uitlezen via dashboard-API, geschiedenis en HTML.
- Geen apparaatopdrachten: alleen GET in HA-client, geen schrijfroute op de dashboardserver.
- HA-token komt niet in dashboarddata; HTTP-redirects sturen het token niet door.
- Rechtstreekse toegang wordt geweigerd in Ingress-modus.
- Bij verbindingsfalen blijft geschiedenis behouden en wordt de verouderde toestand gemarkeerd.
- JavaScript-syntaxis gecontroleerd met `node --check picot_hc/web/app.js`.

## Niet bevestigd

- Visuele browsercontrole: Playwright-pakket aanwezig, maar geen Chromium-executable geïnstalleerd. Er is geen screenshot of geslaagde browsertest.
- Docker-build en HA Supervisor-installatie: Docker ontbreekt in de ontwikkelomgeving.
- Live uitlezing van Alex’ HA, werkelijke prijsattributen en sensoreenheden.
- Apparaatbediening: bewust afwezig in de observatiebasis.

## Eerste controle op HA

Installeer na merge vanuit de bestaande PicoT HEMS-repository, controleer dat de drie zones verschijnen en de bekende vermogens-/energiebronnen aansluiten. Ontbrekende Ecowitt-metingen moeten als niet gekoppeld verschijnen. Controleer de eigen prijsgrafiek tegen de Nordpool-bron, inclusief eenheden en belastingen, en herstart HC om behoud van meetgeschiedenis te bevestigen. Pas daarna de observatiebasis als live getest beschouwen.

## Dashboardinstellingen — 0.1.0-dev.2

- 16 lokale Python-tests geslaagd, inclusief opslaan via HTTP, direct uitlezen
  zonder nieuwe HA-meting, herstart, lege waarden, zonescheiding en ongeldige invoer.
- Opslagfout met echte SQLite-trigger: foutmelding, bestaande waarden behouden.
- POST vereist Ingress-toegang en een apart CSRF-token; HA-client blijft GET-only.
- JavaScript-syntaxis gecontroleerd. De CI-browsercontrole gebruikt een echte HC-server
  voor opslaan, herladen, conceptinvoer bij verversen, ongeldige grenzen en mobiele breedte.
- Lokale Chromium-download loopt vast; de browsercontrole wordt in CI uitgevoerd.
- Live update en Ingress-interactie van dev.2 zijn nog niet bevestigd.

## Weer — 0.1.0-dev.3

21 Python-tests omvatten echte HTTP-forecastresponse, cache/herstart, foutisolatie,
tijdzones, eenheden, ontbrekende waarden en weigeren van redirects met HA-token.
De browsercontrole is uitgebreid met actuele weergegevens en vijf forecastdagen
via een gesimuleerde HA-server. CI-build en browserresultaat volgen bij de PR;
echte HA-forecast en Ingress-weergave van dev.3 moeten na update worden bevestigd.

## Tarief en neerslag — 0.1.0-dev.4

22 Python-tests geslaagd; JavaScript-syntaxis gecontroleerd. Browsercontrole
uitgebreid met bronbevestiging, 0 mm met regen, 0,04 mm en <0,01 mm.
CI-browser/build en live update afzonderlijk controleren. De ruwe forecast
van de gemelde 0 mm is niet beschikbaar in deze sessie.

Definitieve dev.4-weergave: neerslaghoeveelheid en bijbehorende toelichting zijn
verwijderd. Bestaande browsercontrole aangepast om afwezigheid van deze regels
en behoud van het weertype te controleren.

## Bronbediening — 0.1.0-dev.6

35 Python-tests geslaagd. Twaalf nieuwe controles gebruiken een echte lokale
HTTP-server en SQLite voor opdrachtpayloads, onafhankelijke terugmelding, oude
uitlezingen, idempotentie, grenzen/stappen/eenheid, afwijzingen, dubbel verzoek,
timeout, herstart, opslagfouten, uit-preëmptie en toegangscontrole. Een mislukte
opslagtransactie verstuurt geen opdracht en behoudt een eerdere lopende opdracht.
JavaScript-syntaxis en git diff --check slagen. Lokale Ruff/Mypy-executables zijn
niet beschikbaar; de bestaande repositorycontroles draaien in GitHub.

De CI-browsercontrole is uitgebreid met modus wijzigen, temperatuur instellen,
uitzetten, onafhankelijke bevestiging en geen replay bij herladen, via een
gesimuleerde HA-server. De CI-containerbuild en browsertest moeten op de PR slagen.
Geen echte HA-services of apparaten aangestuurd vanuit deze ontwikkelsessie.
De geïnstalleerde broncapaciteiten en fysieke terugmelding zijn nog niet live getest.

## Lokale HTTP-bediening — 0.1.0-dev.7

35 Python-tests geslaagd; JavaScript-syntaxis en diff gecontroleerd. De
browsercontrole schakelt randomUUID uit en controleert echte modus-,
temperatuur- en uitopdrachten met terugmelding via gesimuleerd HA. Een
voorbereidingsfout moet zichtbaar zijn, zonder verzending of vastgelopen knop.
Browser- en containercontrole draaien in CI; live HA-controle volgt na update.
