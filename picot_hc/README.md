# PicoT Home Climate

Handleiding voor de lokale HC/HEMS-ontwikkelversie van 24 oktober 2026.
Deze wijzigingen zijn nog niet gepubliceerd. Het bestaande versienummer in de
appconfiguratie is geen bewijs dat deze functies al live beschikbaar zijn.

## Beneden instellen

Alle comfortinstellingen voor beneden staan centraal bij **Comfortschema**.
Met een actief schema kies je dagen, begin/einde en doeltemperatuur per venster.
Buiten de vensters geldt **Minimum buiten comfortvensters**. Met het schema uit,
of zonder vensters, gebruikt HC **Handmatige thermostaat** zonder aanvullende
tijdschakelingen. Opslaan wijzigt de instellingen; automatische verwarming moet
apart zijn ingeschakeld voordat HC apparaten aanstuurt.

Het vinkje **Comforttemperatuur** maakt het venster strikt: geen economische
verlaging van het doel. Zonder vinkje geldt de ingestelde optimalisatieband.
Vensters mogen niet overlappen, ook niet over middernacht. Boven en badkamer
houden hun eigen vaste instellingen. Garage is uitsluitend een meetzone.

Wanneer HC beneden verwarmt, blijft de eigen bron bij het bereiken van het doel
op temperatuur handhaven. Het bereiken van bijvoorbeeld 20 graden veroorzaakt
geen korte uit/aan-cyclus. HC kan het setpoint aanpassen; de airco of thermostaat
regelt vervolgens zelf de warmtelevering. Een beschermende stop, handmatige
keuze, uitschakelen van de regeling of toegelaten bronwissel blijft mogelijk.
Na uitschakelen geldt minimaal drie minuten rust voordat HC opnieuw start.
Een economische bronwissel wacht op de bestaande minimumlooptijd van vijf minuten
en op bevestigde uitschakeling van de vorige bron.

Bij een gekozen CV-start voor beneden kan boven tot de overdracht blijven
verwarmen. HC plant minimaal vijf minuten looptijd en ruimte voor twee polls
(minimaal zestig seconden) voor de uitschakelbevestiging. Vlak voor die overdracht
start HC boven geen nieuwe korte run. De CV start pas na bevestigde uitschakeling;
een handmatige overname, storing of ontbrekende bevestiging wordt niet omzeild.
Een geldig gekozen CV-tijdstip blijft bij planvernieuwing behouden. Als andere
alternatieven afvallen, kan HC het voorstel eenmalig beperken tot dat gekozen
CV-plan; daarvoor is opnieuw beoordeling en toestemming van HEMS nodig.

De CV-keuze wordt bepaald door beneden. De temperatuur boven blokkeert die keuze
niet en kan de CV ook niet zelfstandig aanvragen. Als de CV boven meeverwarmt,
is dat een gevolg van de installatie. Bij alleen warmtevraag boven gebruikt HC
de airco boven. Boven, garage en badkamer vallen buiten de economische optimalisatie
voor beneden.

## Leren en eerder afbouwen

**Opwarmtijd beneden automatisch bijleren** is een afzonderlijke optie in het
comfortschema. HC begint met de ingestelde beginopwarmtijd (standaard 45 minuten)
en past deze begrensd aan op basis van volledige opwarmpogingen. De maximale
opwarmtijd is instelbaar. Dit is geen garantie dat elk venster vanaf de eerste
dag op temperatuur is: passende metingen moeten eerst worden opgebouwd.

**Temperatuurverlaging voorzichtig bijleren** laat HC binnen de ingestelde
minimumtemperatuur voorzichtig onderzoeken hoe ver het huis mag afkoelen.
**Eerder afbouwen binnen comfortmarge** kan het doel aan het einde van een niet-strikt
comfortvenster een halve graad verlagen. Dat gebeurt alleen bij voldoende passende
afkoelmetingen en behoud van de ondergrens. Een strikt comfortvenster wordt niet
economisch afgezwakt. Ontbrekende of onderbroken metingen worden niet ingeleerd als
succesvolle pogingen. Handmatige overname en schemawijzigingen begrenzen het leren.

## Samenwerking met HEMS

De basisregeling kan zelfstandig werken. Economische planbeoordeling en uitvoering
van een gekozen energieplan vragen de bijbehorende HEMS-koppeling en actuele,
geldige gegevens. **Gekozen start beneden automatisch uitvoeren (proef)** is een
aparte optie en staat standaard uit.

HC stelt maximaal vijf onderbouwde alternatieven tegelijk voor, met een
verwacht energieprofiel en eventuele gaskosten. HEMS beoordeelt deze samen met
huisverbruik, prijzen, PV, batterij en bestaande verplichtingen. HEMS kiest hooguit
een plan of geeft een afwijzing met voorwaarden terug. Een energievooruitblik is
een richtlijn, geen gegarandeerde beschikbaarheid. MEP ontvangt generieke
energieprofielen en reservevoorwaarden, geen kennis van airco's of comfortschema's.

Extra bijladen kan deel uitmaken van de beoordeling, ook wanneer alleen de
beloofde eindreserve tekortschiet en een dagdoel al behaald is. Een voorwaardelijke
keuze geeft nog geen starttoestemming: eerst moet de echte route zijn vastgelegd
en opnieuw beoordeeld. Voor starten controleert HC opnieuw bron, meetkwaliteit,
prijzen, voorspellingen en toestemming. Herstarten hervat een oude startintentie
niet automatisch. De zoektocht naar extra laden is begrensd; dit is geen garantie
van het wereldwijde kostenminimum over alle mogelijke laadblokken.

## CV, gas en hulpstroom

De basisbronkeuze gebruikt de ingestelde COP-/rendementsschattingen en geldige
stroom- en gasprijzen. Voor volledige CV-planvergelijking zijn passende metingen
van opwarmen en handhaven nodig. Onbekende waarden worden niet als nul behandeld.

Er is geen afzonderlijke CV-elektriciteitsmeter in deze installatie. De opties
`cv_auxiliary_mode: estimated`, `cv_auxiliary_running_w: 100`,
`cv_auxiliary_postrun_w: 50` en `cv_auxiliary_postrun_seconds: 300` zijn expliciete,
voorlopige modelaannames. Ze zijn geen gemeten verbruik of bewezen besparing.
Een ingestelde maar defecte echte CV-meter wordt niet stilzwijgend vervangen door
het model. De bevestigde aircometer meet uitsluitend de airco beneden.

Gas bevat ook tapwater. HC gebruikt `binary_sensor.dhw_status` en de diagnostische
`sensor.dhw_status`. Omdat die signalen 30-60 seconden kunnen achterlopen, wordt
de toewijzing gedurende 90 seconden opnieuw beoordeeld. Onbekend of actief
tapwater kan een CV-energievoorstel blokkeren. Verwarming en tapwater worden niet
zonder onderbouwing als dezelfde vervangbare belasting behandeld.

## Weer en meetkwaliteit

De eigen Ecowitt-temperatuurmeting blijft de ruimtemeting. HC controleert waarde,
eenheid en `last_reported` samen via HA. Een constante temperatuur met een nieuwe
melding kan dus geldig blijven, ook als `last_updated` oud is. Bij ontbrekende of
te oude metingen blokkeert HC nieuwe verwarming en stopt het zo nodig zijn eigen
betrokken bron. Laatst bekende waarden blijven zichtbaar als verouderd.

De ingestelde `weather_entity` levert actuele weersomstandigheden en een aparte
dagverwachting. Alleen wanneer die HA-bron uurverwachtingen ondersteunt, vraagt HC
ook uurgegevens op voor temperatuur, wind en bewolking. De werkelijke ondersteuning
van de huidige bron moet nog live worden vastgesteld.

Passende waargenomen weersomstandigheden helpen HC vergelijkbare leerperioden
selecteren. Uurverwachtingen begrenzen toekomstige plannen; voorspellingen worden
nooit als gemeten leergegevens opgeslagen. Bij een bron zonder uurondersteuning
blijft de route op waargenomen omstandigheden beschikbaar. Een ondersteunde maar
ontbrekende, onvolledige of verouderde uurverwachting blokkeert de betreffende
optimalisatie; de gewone comfortregeling blijft beschikbaar.

Dagverwachting en uurverwachting worden afzonderlijk vernieuwd, normaal iedere
30 minuten, na fouten met een nieuwe poging na vijf minuten. Uurdata zijn na een
uur verouderd; dagdata na twee uur. Ontvangsttijd bewijst geen recente modelupdate
bij de weerleverancier. Ontbrekende waarden worden nooit nul.

## Handmatige bediening en badkamer

Onder **Bronbediening** kun je modus en apparaattemperatuur handmatig instellen.
De apparaatmodus Auto is niet de HC-planner. Handmatige keuzes blijven leidend;
een schemabewerking neemt de bron niet automatisch over. Een HTTP-antwoord van HA
betekent alleen ontvangst: HC wacht op nieuwe status die de opdracht bevestigt.
Een bevestigde heat-modus bewijst nog geen actieve warmtelevering.

Een handmatig actieve bron wordt bij inschakelen van HC niet automatisch
geclaimd. Storingen blijven zichtbaar tot **Storingen vrijgeven na controle**.
Controleer de apparaatstanden voordat je vrijgeeft. Opdrachten worden bij fout,
timeout of herstart niet automatisch herhaald.

De badkamertimer kiest 1-180 minuten met een doel binnen de badkamergrenzen.
Deze werkt ook zonder algemene automatische regeling. Na afloop geldt weer het
vaste doel als de regeling actief is; anders stopt HC zijn timerverwarming.
**Stop timer**, handmatige bronovername of uitschakelen van de automatische
regeling stopt de timer. Na herstart wordt een timer niet hervat; HC ruimt zijn
eigen timerverwarming op zodra de bron bereikbaar is.

## Configuratie, opslag en installatie

Beneden gebruikt de instellingen in het comfortschema. Boven en badkamer hebben
vaste zone-instellingen op het dashboard. Entiteiten, vochtgrenzen, prijzen en
CV-modelaannames staan in de HA-appopties. Herstart na wijzigingen aan appopties.
Vochtgrenzen starten geen automatische ontvochtiging.

Stroomprijzen moeten expliciete intervallen met tijdzones bevatten. HC gebruikt
de bevestigde prijsbron zonder extra belastingen toe te voegen. Controleer bij
een andere bron de prijsbasis opnieuw. Gasprijs en geldigheidsdatum komen uit de
configuratie. Ontbrekende of conflicterende prijstijdvakken worden niet ingevuld.

HC is een eigen app naast HEMS en Energy Devices, met eigen container, configuratie,
Ingress-paneel en database. De bestaande PicoT HEMS-repository levert de app via
de HA-appwinkel. Deze ontwikkelwijzigingen zijn pas beschikbaar na afzonderlijke
publicatie en installatie. De nieuwe container en woningwerking zijn nog niet volledig geverifieerd.
De lokale browserproef slaagt met een nagebootste HA-omgeving; ook de
typecontrole van de HEMS-uitbreiding slaagt na herstel van de contracttypen.

Gegevens staan in `/data/hc.sqlite3` en blijven bij gewone herstart/update behouden.
Maak voor installatie en teruggaan een HA-back-up inclusief HC; oudere versies
begrijpen niet noodzakelijk alle nieuwe instellingen en opgeslagen plannen.
Na herstart staat automatische verwarming uit. Controleer doelen, apparaatstanden
en meldingen voordat je de regeling weer inschakelt.

**Meetgegevens downloaden** levert de opgeslagen woningmetingen als gzip-JSONL.
Downloaden stuurt geen apparaten aan en verlengt de ingestelde bewaartermijn niet.
Bewaar exports zelf als je langere historie nodig hebt. Grafieken tonen ontbrekende
gegevens als gaten, met tijden in Europe/Amsterdam.

## Lokaal draaien en testen

Gebruik vanuit deze map Python 3.12 en beschikbare systeemtijdzones. De app gebruikt
de standaardbibliotheek. Alleen voor testen zijn pytest en pytest-subtests nodig;
pytest voert ook de bestaande unittest-tests uit.

```bash
python3 -m pip install "pytest>=8.0" pytest-subtests
PYTHONPATH=. python3 -m pytest tests -q
python3 -m picot_hc --config options.example.json --data ./data
```

Open lokaal `http://127.0.0.1:8099`. Zonder HA-token verschijnen ontbrekende gegevens
en een verbindingsmelding. Een echte lokale verbinding gebruikt `HC_HA_API`
(eindigend op `/api`) en `HC_HA_TOKEN` via de beveiligde omgeving. Zet de lokale
ontwikkelserver niet rechtstreeks op internet.

De volledige lokale HC-testreeks leverde op 24 oktober 2026 428 geslaagde tests en
30 subtests op. Dit is geen bewijs van een geslaagde containerbuild, volledige
typecontrole, browserproef of live woningproef. Zie
[releasecontroles](../docs/development_log/2026-10-24-hc-release-checks.md) en
[reserve en uurweer](../docs/development_log/2026-10-24-hc-reserve-completion.md).

## Historische installatiegegevens

Onderstaande notities beschrijven eerdere uitbreidingen en migraties. Uitspraken
zoals "volgt later" horen bij die oudere versie; de actuele werking staat hierboven.

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

## Ecowitt en badkamer-energiemeter (vanaf dev.12)

Bron: Alex’ PicoT_HC_entiteiten.xlsx, 2026-09-15. Beneden gebruikt de gateway-
binnenmeting, buiten kanaal 1, boven kanaal 2 en badkamer kanaal 3. Temperatuur en
luchtvochtigheid worden uitgelezen; buitenluchtvochtigheid staat bovenaan bij de weerkaart en wordt met de snapshots opgeslagen. De badkamer gebruikt nu ook de
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

Vanaf dev.13 toont de weerkaart eigen Ecowitt-metingen naast actueel Buienradar.
De dagverwachting blijft afzonderlijk als voorspelling benoemd.

## Dauwpunt en sensorbatterijen (vanaf dev.14)

De ingevulde entiteitenlijst levert vier dauwpunten in °C: beneden
`sensor.gw1200a_indoor_dewpoint`, boven `sensor.gw1200a_dewpoint_2`, badkamer
`sensor.gw1200a_dewpoint_3` en buiten `sensor.gw1200a_dewpoint_1`.
Batterijmeldingen zijn `binary_sensor.gw1200a_battery_2`, `_3` en `_1` voor
respectievelijk boven, badkamer en buiten. Beneden heeft geen batterijmelding.

Nieuwe optionele instellingen zijn `dewpoint` en `battery` per zone, plus
`outdoor_dewpoint` en `outdoor_battery`. Lege velden krijgen de bevestigde
koppelingen. Bestaande eigen entiteiten worden niet vervangen.

Dauwpunt en batterijmelding staan op de zonekaart en voor buiten op de weerkaart.
Beide worden met bronstatus in de meetgeschiedenis opgeslagen. Oudere metingen
krijgen geen verzonnen waarden. HA-binary sensors met device_class `battery`
gebruiken `off` voor Normaal en `on` voor Batterij bijna leeg. Andere of ontbrekende
waarden blijven ongeldig/onbekend; een verkeerd sensortype vraagt controle.
Zie https://www.home-assistant.io/integrations/binary_sensor/.

Dit voegt observaties toe. Dauwpuntgestuurde ventilatie of verwarming volgt later.
Terugval naar dev.13 behoudt de database; verwijder bij Supervisor-validatiefouten
alleen de nieuwe optionele configuratiesleutels uit de add-on-opties.

## Meetbasis woninggedrag (vanaf dev.15)

HC bouwt de meetreeks voor afkoeling en latere verwarmingssessies verder op in
`/data/hc.sqlite3`. Bestaande snapshots blijven behouden. Nieuwe snapshots krijgen
`building.version = 1` met binnen-buitenverschil in K per zone, achterdeur en
bronmodus, gemelde activiteit en doeltemperatuur. Cv wordt als gedeelde bron van
beneden en boven vastgelegd. Bronrapportagetijd en wijzigingstijd blijven apart;
een ontbrekende bronrapportagetijd wordt niet vervangen door de ontvangsttijd.

De temperatuur beneden blijft de echte meting, ook bij een open achterdeur. De
meereizende deurstatus maakt latere selectie mogelijk. Deur open en herstel na
sluiten mogen niet zonder meer als normaal woningverlies worden ingeleerd.
Een heat-modus bewijst geen actieve verwarming. Het getoonde binnen-buitenverschil
is een rekenkundige observatie, geen bewijs van geschikte of verse leerdata.

Bij Meetbasis woninggedrag staat de registratiestatus en bewaartermijn. Die blijft
zoals ingesteld (standaard 90 dagen). Meetgegevens downloaden levert gzip-JSONL:
eerst formaat/versie/eindtijd/bewaartermijn, daarna de aanwezige snapshots met de
relevante meetvelden, inclusief oudere rijen met `building: null`.
Het endpoint `api/building-export` gebruikt dezelfde toegangscontrole als HC en
leest in kleine pagina's tot een vast eindtijdstip. Downloaden verstuurt geen HA-
opdrachten. Bewaar downloads zelf als de metingen langer nodig zijn; de ingestelde
retentie blijft van toepassing en een download wijzigt deze niet.

Dit is de registratiebasis voor een toekomstig woningmodel. Geschikte perioden,
na-ijlen van warmte, zon en interne warmte moeten nog worden beoordeeld; er wordt
nog geen afkoelcoëfficiënt, COP of verwarmingstijd voorspeld. Terugval naar dev.14
vereist geen databasemigratie en laat de oude meetreeks intact.

## Klimaatgrafieken per zone (vanaf dev.16)

Naast het bestaande temperatuuroverzicht staat per zone een klimaatgrafiek over
de afgelopen 24 uur. Temperatuur (paars, doorgetrokken) en dauwpunt (oranje,
gestippeld) gebruiken samen de linker °C-as. Luchtvochtigheid (blauw, gestreept)
gebruikt rechts altijd 0–100%. De °C-as schaalt op de beschikbare temperatuur- en
dauwpuntwaarden. De grafieken tonen opgeslagen metingen, geen voorspelling.

Aanwijzen of aantikken toont de drie waarden en het tijdstip van het dichtstbijzijnde
opgeslagen meetmoment. Met focus op de grafiek werken ook de pijltjestoetsen.
Ontbrekende/verkeerd gekwalificeerde waarden en gaten vanaf vijf minuten worden
niet verbonden. Oudere historie zonder dauwpunt krijgt geen berekende vervanging.
De bestaande database, bewaartermijn, bronbediening en comfortregeling wijzigen niet.

## Buitenmeting en garage (2 oktober 2026)

Buiten gebruikt nu de vier `sensor.0_energie_gw1200a_*`-entiteiten voor temperatuur,
luchtvochtigheid, dauwpunt en VPD (hPa). De oude kanaal-1-koppelingen worden bij
start vervangen; afwijkende eigen buitenentiteiten blijven behouden.
Kanaal 1 wordt Garage: temperatuur, vocht en dauwpunt worden opgeslagen en in
de zonekaart en 24-uursgrafiek getoond. De garage wordt via cv verwarmd, maar
krijgt geen comfortdoel, warmtevraag of eigen apparaatbediening. Bestaande historie
blijft ongewijzigd; metingen onder het oude buitenlabel worden niet achteraf
hernoemd. De bewaartermijn blijft zoals ingesteld.

De buitenbatterijmelding gebruikt `binary_sensor.0_energie_gw1200a_wh26_battery`.

Actuele verificatie: [typeherstel en browserproef](../docs/development_log/2026-10-24-hc-type-repair.md).
