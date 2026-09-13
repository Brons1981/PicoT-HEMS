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
