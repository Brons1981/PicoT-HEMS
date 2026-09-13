# PicoT Home Climate

Versie **0.1.0-dev.4** — zelfstandige observatiebasis voor Home Assistant.

## Wat deze versie doet

- Leest HA-statussen iedere 30 seconden. De dagverwachting wordt afzonderlijk opgevraagd via de vaste uitleesactie weather.get_forecasts.
- Registreert drie zones, aanwezigheid, buitenmeting, cv, gas en CO₂ in een eigen SQLite-database.
- Toont een lokaal dashboard, expliciete prijsintervallen en 24 uur temperatuurgeschiedenis.
- Laat ontbrekende entiteiten en eenheidsproblemen zien. Houdt laatst ontvangen gegevens zichtbaar bij verbindingsverlies, gemarkeerd als verouderd.
- Biedt temperatuurinstellingen per zone op het dashboard; entiteiten en vochtgrenzen blijven in de HA-appconfiguratie.

Er is geen afhankelijkheid van PicoT HEMS. Deze versie stuurt geen apparaten aan. Schema-editor, badkamerknop, woningmodel, kostenvergelijking en automatische prijsoptimalisatie volgen volgens `docs/PicoT_HC_basis.md`.

## Installeren vanuit de PicoT HEMS-repository

Deze installatievorm is voorbereid; Docker-build, Supervisor-installatie en live HA-verbinding zijn nog niet getest in deze ontwikkelomgeving.

1. Gebruik de bestaande repository `https://github.com/Brons1981/PicoT-HEMS` in de HA-app/add-onwinkel, dezelfde als voor Energy Devices. Er is geen extra repository nodig.
2. Nadat deze toevoeging op `main` staat: vernieuw de winkel en zoek **PicoT Home Climate** onder PicoT HEMS Add-ons.
3. Installeer de app. De eerste installatie bouwt de container en heeft toegang tot het Python-basisimage nodig.
4. Controleer de configuratie. De door Alex aangeleverde entiteiten staan vooraf ingevuld. Temperatuur-/vochtsensoren en buitenmeting mogen leeg blijven tot Ecowitt geplaatst is.
5. Start de app en open de webinterface via HA. De interface gebruikt Ingress; er is geen externe poort gepubliceerd. De HA-verbinding gebruikt het Supervisor-token intern.

Gegevens staan in `/data/hc.sqlite3` binnen de app. Ze blijven behouden bij herstart/update. Verwijderen van de app kan de gegevens verwijderen. Gebruik een HA-back-up inclusief deze app; back-upmodus is cold.

## Weer en verwachting

De weerkaart gebruikt standaard `weather.buienradar`, ook bij een update van bestaande HC-opties. Je ziet actuele toestand, temperatuur, gevoelstemperatuur, luchtvochtigheid, wind, windstoten en luchtdruk voor zover beschikbaar. De dagverwachting toont weertype, maximum/minimum, wind en beschikbare neerslagkans. De neerslaghoeveelheid in mm wordt niet getoond. Ontbrekende waarden worden geen nul.

HC vraagt de dagelijkse verwachting elke 30 minuten via HA op; na een fout volgt na 5 minuten een nieuwe poging. De laatste verwachting blijft bewaard, met een foutmelding/verouderd-markering. Na twee uur zonder succesvolle ontvangst is deze eveneens verouderd. De bronpublicatietijd van een forecast is niet beschikbaar: ontvangsttijd bewijst geen recente modelupdate. Dagen in het verleden worden niet getoond.

`weather_entity` is aanpasbaar in de appopties; leeg schakelt het ophalen uit. De eigen buitentemperatuursensor blijft apart. Weermetingen en verwachtingen worden opgeslagen, maar sturen nog geen apparaten aan en vervangen geen ontbrekende buitensensor. De latere planner moet dagverwachtingen expliciet onderscheiden van uurgegevens.

Technische bron: [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/), `weather.get_forecasts` met `type: daily` en `return_response`. Dit is een POST om gegevens op te vragen, geen opdracht aan een klimaatapparaat.

## Configuratie

Minimum, gewenste temperatuur en maximum staan per zone op het dashboard. Klik op Opslaan; herstarten is niet nodig. HC bewaart deze waarden in zijn eigen database. Per zone gelden de appopties als beginwaarden totdat je op het dashboard opslaat. Daarna hebben de dashboardwaarden voorrang, ook na herstart of update. Een leeg veld wordt opgeslagen als niet ingesteld.

Entiteiten en overige configuratie staan in de HA-appopties. Herstart HC na wijzigingen daaraan. `options.example.json` is een zelfstandig voorbeeld voor lokaal testen.

- `zones`: drie zones met apparaat, temperatuur, vocht, vermogen en energie-entiteiten. Een lege sensornaam betekent nog niet gekoppeld.
- `minimum`, `target`, `maximum`: optionele temperatuurgrenzen per zone; nog geen numerieke defaults. Minimum ≤ doel ≤ maximum. Deze versie toont/bewaart ze, maar regelt er nog niet op.
- `humidity_min`, `humidity_target`, `humidity_max`: aanvankelijk 40, 50 en 60. In deze versie alleen instellingen, geen ontvochtigingsopdrachten. Automatische vochtregeling is eerst voorzien voor boven.
- `presence`: voorlopig iPhone-tracker, later te vervangen door het juiste `person`-ID. UniFi is niet toegevoegd.
- `price_entity` en `price_attributes`: standaard de aangeleverde Nordpool-entiteit en `raw_today`, `raw_tomorrow`. Elke rij moet `start`, `end` met tijdzone en numerieke `value` hebben. Numerieke lijsten zonder tijdstippen worden niet geïnterpreteerd.
- Prijzen ondersteunen EUR/kWh en EUR/MWh (ook met €-symbool). Negatieve prijzen zijn toegestaan. Geen invulling van ontbrekende tijdvakken, geen eigen belastingen toegevoegd.
- `confirmed_price_entity`: de door Alex bevestigde werkelijke prijsbron is `sensor.nordpool_kwh_nl_eur_3_095_0`. Deze bevestiging geldt ook bij bestaande opties zonder dit veld. De bedragen worden ongewijzigd gebruikt, zonder extra belasting of opslag. Bij een andere prijsentiteit geldt deze bevestiging niet.
- `price_basis_confirmed`: handmatige bevestiging voor een andere gecontroleerde prijsbron. Om een bevestiging in te trekken: maak `confirmed_price_entity` leeg en zet deze vlag op false.
- `gas_price`: 1.41197 €/m³; `gas_valid_until`: 2027-06-14, volgens gebruiker. Er is nog geen kostenplanner die dit tarief toepast.
- `poll_seconds`: 10–300, standaard 30. `stale_seconds`: standaard 120 en minstens tweemaal pollinterval. `retention_days`: 1–365, standaard 90.

## Meetkwaliteit en grenzen

Een geslaagde HA-uitlezing bewijst alleen dat HA bereikbaar is. Bron-`last_updated` en ontvangsttijd worden afzonderlijk opgeslagen. Een ongewijzigde sensor kan een oude `last_updated` hebben zonder defect te zijn; deze versie stelt nog geen sensor-specifieke rapportagekwaliteit vast. Vóór sturing moeten die verwachtingen per sensor worden geconfigureerd.

Statussen unknown/unavailable blijven onbekend, ook voor aanwezigheid. Verkeerde numerieke eenheden worden geweigerd. De cv-status wordt zonder interpretatie getoond. Gas omvat ook tapwater. Midea-energieattributen worden nog niet gebruikt als betrouwbare energiemeter. Geen COP, gas-toewijzing of besparing wordt afgeleid.

Prijsdata worden bij ongeldige, conflicterende of overlappende intervallen niet getekend. In tijdgrafieken blijven gaten zichtbaar. De browser toont tijden in Europe/Amsterdam; opslag gebruikt UTC-tijdstippen. Grafieken vernieuwen iedere 15 seconden.

## Lokaal draaien en testen

Python 3.12, uitsluitend standaardbibliotheek; geen pip-installatie nodig.

```bash
python3 -m unittest discover -s tests -v
python3 -m picot_hc --config options.example.json --data ./data
```

Open lokaal `http://127.0.0.1:8099`. Zonder HA-token toont de app ontbrekende gegevens en een verbindingsmelding, geen demonstratiemetingen. Voor een echte lokale HA-verbinding gebruik je `HC_HA_API` (eindigt op `/api`) en `HC_HA_TOKEN` via je eigen beveiligde omgeving. Tokens staan nooit in browsercode of voorbeelden. Zet deze ontwikkelserver niet rechtstreeks op internet.

## Vervolg

HA-installatie vanuit de bestaande repository en bronattributen testen; Ecowitt koppelen; daarna bronbediening en metingen, adviesplanner en uiteindelijk automatische regeling per zone. De oorspronkelijke ADR’s zijn opgenomen onder `docs/`.

Gebruikte interfaces: [HA REST API](https://developers.home-assistant.io/docs/api/rest/), [appconfiguratie](https://developers.home-assistant.io/docs/apps/configuration/), [appcommunicatie](https://developers.home-assistant.io/docs/apps/communication/).

HC staat als eigen map `picot_hc/` naast `picot_hems/` en `picot_energy_devices/`. Alleen de distributierepository wordt gedeeld. HC heeft een eigen container, versie, configuratie, Ingress-paneel en database; HEMS hoeft niet te draaien.
