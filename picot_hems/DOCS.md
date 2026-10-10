# PicoT HEMS

Deze add-on draait de eerste begrensde PicoT-validatie binnen Home Assistant OS.

## Eerste test

Laat `mode` op `dry_run` staan. Controleer daarna in de add-onlogs of:

- de ingestelde prijsentiteit wordt gelezen;
- een goedkoopste prijsvenster wordt geselecteerd;
- de huidige Zendure-modus wordt gelezen;
- de gewenste modus uitsluitend `Alleen slim ontladen` of `Nul op de meter` is;
- `dispatch_status` gelijk is aan `dry_run_only` of `skipped_already_active`.

## Live inschakelen

Zet `mode` pas op `live` nadat de dry-runuitvoer klopt. De add-on wijzigt uitsluitend:

`input_select.zendure_2400_ac_modus_selecteren`

De twee toegestane opties zijn:

- `Alleen slim ontladen`
- `Nul op de meter`

## Standaardconfiguratie

```yaml
mode: dry_run
price_entity: sensor.nordpool_kwh_nl_eur_2_10_021
target_entity: input_select.zendure_2400_ac_modus_selecteren
window_points: 1
interval_seconds: 60
```

De Home Assistant Supervisor-token wordt tijdens runtime geleverd en wordt niet opgeslagen in de repository of add-onconfiguratie.

## MEP-marktinstellingen

Onder **Instellingen → Add-ons → PicoT HEMS → Configuratie** zijn de twee
financiële toelatingswaarden rechtstreeks door de gebruiker instelbaar:

- `market_daily_trading_margin_percent`: gewenste extra handelsmarge in procenten;
  standaard `10.0`.
- `market_daily_wear_eur_per_kwh`: toegerekende batterijslijtage per geëxporteerde
  kWh; standaard `0.05` euro.
- `market_daily_maximum_trading_soc_percent`: eenmalige migratiewaarde voor de
  canonieke gebruikersregel **Maximaal SoC voor handel**; standaard `25.0`.
  Na de eerste start wordt de regel beheerd via **PicoT Pipeline → Strategie**.
  PicoT begrenst de ingestelde waarde verder met de onderste SoC-grens, de
  huishoudreserve en een aanvullende reserve van 10 procentpunt.

De Strategie-pagina bevat ook **Beschikbare PV behouden bij netladen**. Wanneer
deze regel actief is, blijft NOM rond het begrensde netlaadblok beschikbaar en
vult het net alleen het resterende opslagtekort. Een wijziging wordt duurzaam
opgeslagen en laat PicoT direct opnieuw plannen.

Start de add-on na een wijziging van de overige add-onopties opnieuw. In
**PicoT Pipeline → Strategie** toont
iedere onderzochte marktroute de herstelprijs, RTE-correctie, handelsmarge,
slijtage en de daaruit volgende minimale exportprijs. Zo blijft zichtbaar waarom
de gewijzigde instelling een route wel of niet toelaat.

## Optionele energie-apparaatkaarten

Wanneer de afzonderlijke add-on **PicoT Energy Devices** actief is, verschijnen
zijn kaarten automatisch onder **PicoT Pipeline → Apparaten**. De catalogus is
optioneel: PicoT plant en werkt normaal wanneer de add-on ontbreekt of tijdelijk
niet beschikbaar is.

Een kaart kan door de gebruiker op de prijs-/planningstijdlijn worden geplaatst.
In DEV.238 zijn die plaatsingen uitsluitend zichtbaar en duurzaam opgeslagen;
ze veranderen nog geen MEP-plan. Daardoor kan eerst betrouwbare apparaatdata
worden verzameld zonder de live planner te beïnvloeden.

## Kleine topsessies

`micro_charge_suppression_percent` bepaalt vanaf welk resterend percentage PicoT
geen nieuwe afzonderlijke laadsessie meer start. De standaardwaarde is `2.0`.
De grens geldt voor CP, de etmaalsimulatie en MEP. Onderdrukking is alleen
toegestaan wanneer de minimumreserve zonder die topsessie in alle doorgerekende
scenario's veilig blijft. Een al lopende laadsessie wordt niet afgebroken.

## Herstel na export-eerst

Een export-eerst-marktroute hoeft de batterij na normaal huisverbruik niet
absoluut op 100% te laten eindigen. MEP vergelijkt het einde van ieder scenario
met hetzelfde scenario zonder handel. De route is fysiek toegestaan wanneer de
batterij minstens tot dat baseline-niveau wordt hersteld en de minimumreserve
gewaarborgd blijft. Daarna moet de volledige route, inclusief RTE, handelsmarge
en slijtage, nog steeds financieel positief zijn.

## Kostprijs van opgeslagen energie

PicoT houdt gemeten laadenergie als afzonderlijke voorraadloten bij. Netenergie
krijgt de werkelijke inkoopprijs; PV-energie krijgt de gemiste terugleverwaarde.
Een onbekende beginvoorraad krijgt bewust geen verzonnen kostprijs. De loten
blijven over de daggrens behouden, zodat vandaag goedkoop geladen energie morgen
nog tegen de juiste kostprijs kan worden beoordeeld.

MEP onderzoekt één aaneengesloten exportvenster en reserveert daarna zo nodig een
volledig herstelvenster. Het herstel hoeft alleen het scenario-baselineverloop te
herstellen en de complete route moet in het slechtste scenario minimaal vijf cent
netto opleveren. Zodra de exportsessie is gestart, blijft die sessie vastgelegd tot
het venster of het energiedoel eindigt; een nieuwe 60-secondenpoll start geen losse
kwartierhandel.


## Snapshotopnameproef — dev.264

Laat `history_capture_trial_enabled` eerst op `false` staan en verzamel 30 minuten
logboek als baseline. De nieuwe JSON-regels heten `picot_v2_history_capture_trial`.
Na beoordeling kan de optie op `true` worden gezet, gevolgd door een appherstart.
Dan worden gedurende 30 minuten bestaande volledige incidentrecords opgenomen.
De recorder heeft een wachtrij van twee records, 64 MiB gereserveerde tekstobjecten
en een eigen opslagbudget van 512 MiB met 128 MiB vrije-ruimtereserve.

Een schrijffout stopt de opname. Afwijzingen en ontbrekende opnamen blijven
zichtbaar. Er is geen automatische indexverwerking of verwijdering. Na de proef
de optie terug op `false` zetten en herstarten; opgeslagen bestanden blijven staan.
Een herstart met `true` begint een nieuwe proef. Een lopende schrijfactie mag na
de 30-minutengrens afronden. Deze proef is nog geen vrijgave voor permanent gebruik.

Vanaf dev.265 bevat de diagnose-download ook de reeds opgeslagen proefobjecten
en een exportmanifest. Zet `history_capture_trial_enabled` vóór installatie op
`false` en download na de update één nieuwe diagnose-ZIP. Een nieuwe opname is
niet nodig. Export is begrensd op 16 MiB en 64 objecten en verwijdert niets. Het
manifest meldt ontbrekende of gedeeltelijke export; inhoudsverificatie volgt apart.

## Solcast-basis voor MEP

De add-onoptie `solcast_planning_basis` kiest `lower`, `mean-lower-central`,
`central` of `upper`. Het gemiddelde van lower en central is de standaard en
wordt per interval berekend. De originele prognoses blijven beschikbaar.
Laadplanning, beoordeling van korter netladen en marktherstel gebruiken dezelfde
keuze. Meer verwachte PV kan minder netladen betekenen, maar geeft geen garantie
op een later laadmoment.

Sla de optie op en herstart de add-on. Gebruik daarna **Planning opnieuw berekenen**
om het bestaande dagplan opnieuw te laten beoordelen. De keuze alleen wist of
vervangt geen opgeslagen plan; lopende laadacties en dagdoelen blijven beschermd.
De gekozen basis wordt bij nieuwe plannen opgeslagen voor diagnose.

## Begrensd uitstel van voorspelde tekorten

Een voorspeld hoofd- of overbruggingstekort tot 3% van de bruikbare capaciteit
kan worden uitgesteld als dezelfde fysieke simulator bewijst dat ingrijpen na
vijftien minuten nog uitvoerbaar is. Bij 8,16 kWh is de grens 244,8 Wh. De volgende
poll beoordeelt opnieuw; onbekende meetkwaliteit, een reeds actueel tekort of
ontbrekende herstelruimte geeft geen vrijstelling. Een herstelbewijs voor de
hoofdroute bewaart het exacte 100%-doel. Het overbruggingsbewijs bewaart de
hoofdopdrachten en houdt rekening met vastgelegde export. Dit wijzigt geen
minimum-SOC en voltooit geen opdracht op basis van een prognose.

Een overbruggingsvariant die zonder batterijopname alleen huisvraag uit het net
laat komen, gebruikt expliciet stand-by. Zij krijgt geen wachtend maximaal
laadcommando dat na een kleine SOC-daling alsnog bijlaadt. Bij een materiële
herziening wordt een eerdere niet-lopende overbrugging opnieuw beoordeeld;
werkelijk lopend snel laden beneden 100% behoudt zijn continuïteit.

## EV-snapshot en huishoudhistorie

Voor de bestaande snapshotkoppeling aan de actieve Energy Devices-correctie:

```yaml
energy_device_policy_enabled: true
energy_device_policy_entity: sensor.picot_ev_regulation_policy
```

Dit zijn **PicoT HEMS-add-onopties**, geen instellingen van `configuration.yaml`.
Start HEMS na wijziging opnieuw. HEMS leest uitsluitend het Energy Devices-contract;
de EV-meter en smartplug blijven bij Energy Devices. Onbruikbare of verouderde
snapshots geven geen toestemming om EV-vraag uit de batterijvraag te verwijderen.
De fysieke RAW-netmeting blijft onveranderd.

Fysiek gemeten, afzonderlijk geïdentificeerd EV-vermogen blijft bewaard naast
het totale verbruik en wordt niet opnieuw als normale huishoudhistorie gebruikt,
ook wanneer de actuele EV-koppeling later wordt uitgeschakeld. Oven en andere
huishoudvraag blijven meetellen. Oude metingen zonder EV-identificatie worden
niet achteraf geschat of gewist.

Een al opgeslagen oud plan kan nog een anoniem overbruggingslaadblok bevatten.
Gebruik na installatie van deze fix eenmaal **Maak een nieuw plan** om die oude
vrije intervallen door de canonieke herberekening te vervangen.

### Gelijke EV-dekking tijdens en na een sessie

Bij ingeschakelde `energy_device_policy_enabled` of `energy_device_sessions_enabled`
gebruikt de huishoudbasis alleen historische metingen met vastgelegde externe
vermogensdekking. Ook een gemeten EV-vermogen van nul telt als dekking. Het einde
van een sessie of een ontbrekend actueel snapshot heropent geen ongeclassificeerde
historie. Bekend EV-vermogen wordt afgetrokken; fysieke bronmetingen worden niet
gewijzigd. Zonder voldoende gedekte historie gebruikt de bestaande expliciete
huishoudbasislast-terugval de ingestelde waarde. Dit is een tijdelijke basis met
beperkte voorspelbaarheid van toekomstig huishoudverbruik, geen kalenderprofiel.
Actuele huishoudmetingen en bewaking van extra huisvraag blijven beschikbaar.
