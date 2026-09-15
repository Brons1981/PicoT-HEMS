# PicoT Home Climate

Versie **0.1.0-dev.12** — zelfstandige meting, comfortvensters en handmatige bronbediening voor Home Assistant.

## Wat deze versie doet

- Leest HA-statussen iedere 30 seconden. De dagverwachting wordt afzonderlijk opgevraagd via de vaste uitleesactie weather.get_forecasts.
- Registreert drie zones, aanwezigheid, buitenmeting, cv, gas en CO₂ in een eigen SQLite-database.
- Toont een lokaal dashboard, expliciete prijsintervallen en 24 uur temperatuurgeschiedenis.
- Laat ontbrekende entiteiten en eenheidsproblemen zien. Houdt laatst ontvangen gegevens zichtbaar bij verbindingsverlies, gemarkeerd als verouderd.
- Biedt temperatuurinstellingen per zone op het dashboard; entiteiten en vochtgrenzen blijven in de HA-appconfiguratie.

Er is geen afhankelijkheid van PicoT HEMS. De bronbediening is handmatig. Het comfortschema levert bronvrije eisen aan de toekomstige planner en voert zelf geen opdrachten uit. Tijdelijk badkamervenster, woningmodel, kostenvergelijking en automatische prijsoptimalisatie volgen volgens `docs/PicoT_HC_basis.md`.

## Installeren vanuit de PicoT HEMS-repository

Deze installatievorm is voorbereid; Docker-build, Supervisor-installatie en live HA-verbinding zijn nog niet getest in deze ontwikkelomgeving.

1. Gebruik de bestaande repository `https://github.com/Brons1981/PicoT-HEMS` in de HA-app/add-onwinkel, dezelfde als voor Energy Devices. Er is geen extra repository nodig.
2. Nadat deze toevoeging op `main` staat: vernieuw de winkel en zoek **PicoT Home Climate** onder PicoT HEMS Add-ons.
3. Installeer de app. De eerste installatie bouwt de container en heeft toegang tot het Python-basisimage nodig.
4. Controleer de configuratie. De door Alex aangeleverde entiteiten staan vooraf ingevuld. De bevestigde Ecowitt-entiteiten en badkamer-energiemeter zijn vooraf ingevuld.
5. Start de app en open de webinterface via HA. De interface gebruikt Ingress; er is geen externe poort gepubliceerd. De HA-verbinding gebruikt het Supervisor-token intern.

Gegevens staan in `/data/hc.sqlite3` binnen de app. Ze blijven behouden bij herstart/update. Verwijderen van de app kan de gegevens verwijderen. Gebruik een HA-back-up inclusief deze app; back-upmodus is cold.

## Weer en verwachting

De weerkaart gebruikt standaard `weather.buienradar`, ook bij een update van bestaande HC-opties. Je ziet actuele toestand, temperatuur, gevoelstemperatuur, luchtvochtigheid, wind, windstoten en luchtdruk voor zover beschikbaar. De dagverwachting toont weertype, maximum/minimum, wind en beschikbare neerslagkans. De neerslaghoeveelheid in mm wordt niet getoond. Ontbrekende waarden worden geen nul.

HC vraagt de dagelijkse verwachting elke 30 minuten via HA op; na een fout volgt na 5 minuten een nieuwe poging. De laatste verwachting blijft bewaard, met een foutmelding/verouderd-markering. Na twee uur zonder succesvolle ontvangst is deze eveneens verouderd. De bronpublicatietijd van een forecast is niet beschikbaar: ontvangsttijd bewijst geen recente modelupdate. Dagen in het verleden worden niet getoond.

`weather_entity` is aanpasbaar in de appopties; leeg schakelt het ophalen uit. De eigen buitentemperatuursensor blijft apart. Weermetingen en verwachtingen worden opgeslagen, maar sturen nog geen apparaten aan en vervangen geen ontbrekende buitensensor. De latere planner moet dagverwachtingen expliciet onderscheiden van uurgegevens.

Technische bron: [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/), `weather.get_forecasts` met `type: daily` en `return_response`. Dit is een POST om gegevens op te vragen, geen opdracht aan een klimaatapparaat.

## Handmatige bronbediening

Onder Bronbediening staan cv, beide airco’s en badkamerverwarming. Kies een
apparaatmodus en klik Modus toepassen, of stel afzonderlijk de apparaattemperatuur
in. Uit blijft beschikbaar terwijl een eerdere opdracht wacht. Auto is de eigen
apparaatmodus, niet de HC-planner. Comfortvensters staan los van apparaatinstellingen. Badkamer Aan is gewone handmatige bediening: zelf weer uitschakelen;
het tijdelijke verwarmvenster is nog niet gebouwd.

HC haalt vlak vóór een opdracht de actuele HA-status op en toetst mogelijkheden.
Temperatuurbediening vereist Celsius, een enkel setpoint, gemelde grenzen en
stapgrootte; ontbrekende gegevens blokkeren die knop. Beschikbare modi komen uit HA.
Een HTTP-antwoord betekent alleen dat HA de opdracht heeft aangenomen. HC wacht
op een nieuwe uitlezing die de gevraagde instelling toont. Activiteit en gemeten
vermogen blijven apart; een bevestigde instelling bewijst niet dat er warmte is.

Opdrachten blijven bewaard, ook na herstart. Geen automatische herhaling bij fout,
timeout of herstart. Het dashboard toont de laatste twintig opdrachten.
`command_timeout_seconds` bepaalt de wachttijd (30–900, standaard 300 seconden).
Na een herstart krijgt een lopende opdracht de status onderbroken; controleer de
werkelijke apparaatstand voordat je een nieuwe opdracht geeft.

## Comfortschema beneden

Kies per venster meerdere dagen (ma–vr, weekend, alle dagen of losse vinkjes),
begin/einde, één temperatuur en **Comforttemperatuur**. Voeg meerdere vensters
per dag toe of dupliceer een venster en pas dagen/tijden aan. Identieke vensters
worden bij herladen samen getoond; overlap wordt geweigerd, ook over middernacht.

Comfort aangevinkt betekent de temperatuur bij aanvang bereiken en aanhouden:
de planner krijgt daarvoor geen economische afwijkingsruimte. Zonder vinkje geldt
één centrale **Optimalisatieband (± °C)**, standaard 1 °C, instelbaar 0–5 °C.
17 °C met ±1 °C geeft 16–18 °C. De absolute grenzen blijven 5–35 °C;
algemene zonegrenzen blijven afzonderlijk bewaakt. Er zijn geen min/max-invoervelden
per venster. Boven en badkamer behouden hun vaste zone-instellingen.

De financiële planner en automatisch voorverwarmen zijn nog niet geïmplementeerd.
Opslaan, inschakelen, hervatten en herstarten sturen geen apparaat aan.
Handmatige brontemperaturen blijven gedwongen bronkeuzes; cv raakt beneden en boven.
Bestaande handmatige keuzes worden door een schemabewerking niet verlengd.

Dev.10 wordt atomair gearchiveerd en omgezet met behoud van dagen, tijden,
temperaturen, comfortvinkjes en handmatige keuzes. Wijzigen de afgeleide grenzen,
dan staat het schema uit met een controlemelding. Controleer de band en schakel
het daarna opnieuw in. Voor teruggaan naar dev.10 is herstel van de HC-back-up
nodig: die versie begrijpt het nieuwe opslagformaat niet.

## Configuratie

Minimum, gewenste temperatuur en maximum staan per zone op het dashboard. Klik op Opslaan; herstarten is niet nodig. HC bewaart deze waarden in zijn eigen database. Per zone gelden de appopties als beginwaarden totdat je op het dashboard opslaat. Daarna hebben de dashboardwaarden voorrang, ook na herstart of update. Een leeg veld wordt opgeslagen als niet ingesteld.

Entiteiten en overige configuratie staan in de HA-appopties. Herstart HC na wijzigingen daaraan. `options.example.json` is een zelfstandig voorbeeld voor lokaal testen.

- `zones`: drie zones met apparaat, temperatuur, vocht, vermogen en energie-entiteiten. Een lege sensornaam betekent nog niet gekoppeld.
- `minimum`, `target`, `maximum`: optionele temperatuurgrenzen per zone; nog geen numerieke defaults. Minimum ≤ doel ≤ maximum. Deze versie toont/bewaart ze, maar regelt er nog niet op.
- `humidity_min`, `humidity_target`, `humidity_max`: aanvankelijk 40, 50 en 60. Deze grenzen activeren geen automatische ontvochtiging; de apparaatmodus dry kan handmatig worden beproefd. Automatische vochtregeling is eerst voorzien voor boven.
- `presence`: voorlopig iPhone-tracker, later te vervangen door het juiste `person`-ID. UniFi is niet toegevoegd.
- `price_entity` en `price_attributes`: standaard de aangeleverde Nordpool-entiteit en `raw_today`, `raw_tomorrow`. Elke rij moet `start`, `end` met tijdzone en numerieke `value` hebben. Numerieke lijsten zonder tijdstippen worden niet geïnterpreteerd.
- Prijzen ondersteunen EUR/kWh en EUR/MWh (ook met €-symbool). Negatieve prijzen zijn toegestaan. Geen invulling van ontbrekende tijdvakken, geen eigen belastingen toegevoegd.
- `confirmed_price_entity`: de door Alex bevestigde werkelijke prijsbron is `sensor.nordpool_kwh_nl_eur_3_095_0`. Deze bevestiging geldt ook bij bestaande opties zonder dit veld. De bedragen worden ongewijzigd gebruikt, zonder extra belasting of opslag. Bij een andere prijsentiteit geldt deze bevestiging niet.
- `price_basis_confirmed`: handmatige bevestiging voor een andere gecontroleerde prijsbron. Om een bevestiging in te trekken: maak `confirmed_price_entity` leeg en zet deze vlag op false.
- `gas_price`: 1.41197 €/m³; `gas_valid_until`: 2027-06-14, volgens gebruiker. Er is nog geen kostenplanner die dit tarief toepast.
- `poll_seconds`: 10–300, standaard 30. `stale_seconds`: standaard 120 en minstens tweemaal pollinterval. `retention_days`: 1–365, standaard 90.

## Meetkwaliteit en grenzen

Een geslaagde HA-uitlezing bewijst alleen dat HA bereikbaar is. Bron-`last_updated` en ontvangsttijd worden afzonderlijk opgeslagen. Een ongewijzigde sensor kan een oude `last_updated` hebben zonder defect te zijn; deze versie stelt nog geen sensor-specifieke rapportagekwaliteit vast. De maximale meetleeftijd is vastgelegd als voorwaarde voor de toekomstige planner; deze moet passen bij de echte sensorrapportage. Handmatige bronbediening gebruikt een verse HA-uitlezing, die geen onafhankelijke fysieke meting garandeert.

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

Bronbediening is door de gebruiker live bevestigd. Volgende controles: comfortvensters invullen, vaste doelen controleren, Ecowitt koppelen en gedwongen bronkeuzes live beproeven; daarna woningmodel, aanwezigheid en financiële planning/uitvoering. De oorspronkelijke ADR’s zijn opgenomen onder `docs/`.

Gebruikte interfaces: [HA REST API](https://developers.home-assistant.io/docs/api/rest/), [appconfiguratie](https://developers.home-assistant.io/docs/apps/configuration/), [appcommunicatie](https://developers.home-assistant.io/docs/apps/communication/).

HC staat als eigen map `picot_hc/` naast `picot_hems/` en `picot_energy_devices/`. Alleen de distributierepository wordt gedeeld. HC heeft een eigen container, versie, configuratie, Ingress-paneel en database; HEMS hoeft niet te draaien.

### Airco boven: Shelly-meter

De zone boven gebruikt `sensor.shellyplugsg3_d0cf13c907e0_vermogen` (W) en
`sensor.shellyplugsg3_d0cf13c907e0_energie` (kWh), volgens de gecorrigeerde
entiteitenlijst. Bij bestaande configuraties worden lege meetvelden voor
`boven` met apparaat `climate.19791209313101_climate` automatisch aangevuld.
Zelf ingevulde entiteiten blijven behouden. Lege velden gebruiken hier dus de
bevestigde standaardmeters. Op het dashboard verschijnen vermogen en cumulatieve
energie; verkeerde eenheden of ontbrekende sensoren blijven herkenbaar.

Voor `climate.huiskamer` is een stap van 0,5 °C door de gebruiker bevestigd.
HC gebruikt deze alleen wanneer HA geen `target_temp_step` doorgeeft en de
eenheid °C is. Een expliciete HA-stap heeft voorrang; andere entiteiten krijgen
geen impliciete stap. Temperatuur instellen blijft beschikbaar in heat/auto;
Uit schakelt de cv uit en activeert geen verwarming via een temperatuurwijziging.

## Ecowitt en badkamer-energiemeter (dev.12)

Bron: Alex’ PicoT_HC_entiteiten.xlsx, 2026-09-15. Beneden gebruikt de gateway-
binnenmeting, buiten kanaal 1, boven kanaal 2 en badkamer kanaal 3. Temperatuur en
luchtvochtigheid worden uitgelezen; buitenluchtvochtigheid staat bij gezamenlijke
metingen en wordt met de snapshots opgeslagen. De badkamer gebruikt nu ook de
cumulatieve kWh-entiteit naast vermogen.

Bij updates vult HC lege meetvelden voor deze zones aan. Ingevulde eigen entiteiten
blijven behouden. De badkamer-energiemeter wordt alleen automatisch gekoppeld bij
de bevestigde badkamerschakelaar. Buitenluchtvochtigheid is configureerbaar via
`outdoor_humidity`. Een leeg veld krijgt de bevestigde standaard bij herstart.
Ontbrekende of onbruikbare gegevens blijven ontbrekend; geen fictieve nulwaarden.
De bestaande temperatuur-/vochtgrafieken bouwen historie op vanaf ontvangst.
De historische grafiek is niet uitgebreid met buitenluchtvochtigheid.

Schema, comfortdoelen en handmatige keuzes blijven behouden. Dit voegt metingen
toe; automatische bronkeuze en aansturing volgen later.
