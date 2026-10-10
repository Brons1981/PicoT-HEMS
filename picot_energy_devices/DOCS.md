# PicoT Energy Devices

Deze app verzamelt apparaatprofielen. PicoT blijft onafhankelijk plannen; deze
opnames activeren geen optimalisatie of apparaatsturing.

## Een programma inleren

1. Voeg het apparaat toe met een naam en vermogenssensor. Een cumulatieve
   energiemeter is optioneel.
2. Klik vlak vóór het starten van het apparaat op **Start inleren** en geef de
   opname een programmanaam, bijvoorbeeld *Vaatwasser Eco 50°*.
3. Laat de opname het hele programma lopen, inclusief rustige fases. Een daling
   onder 20 W beëindigt de opname niet.
4. Klik op **Programma klaar** zodra het programma werkelijk klaar is.
5. Kies **Bekijken** voor het vermogensverloop en de afzonderlijke metingen.
   Je kunt de naam wijzigen of een foutieve opname verwijderen.

Een lopende opname blijft na een herstart bewaard. Eventuele meetuitval tijdens
het herstarten wordt zichtbaar. Verwijder een lopende opname om deze te annuleren.
Stopknoppen bedienen alleen de opname, nooit het fysieke apparaat.

## Meetkwaliteit

Energie wordt geschat uit het gemeten vermogen en de tijd tussen metingen
(vorige vermogen aangehouden). Bij de start wordt de laatste beschikbare meting
gebruikt als deze nog vers is; dit staat in de meettabel. Zonder verse startmeting
begint de opname met een expliciet meetgat. Optionele energiemeterstanden blijven
bij iedere meting bewaard, maar worden niet als volledige sessie-energie voorgesteld.

Onbeschikbaarheid en te lange meetonderbrekingen tellen niet als nulverbruik en
worden niet met verzonnen energie opgevuld. Bij meetgaten toont de app de bekende
energie als onvolledig. Alleen afgeronde opnames zonder meetgaten en met minimaal
twee vermogenspunten tellen mee voor de samenvatting op de kaart. Een opname blijft
ook met meetgaten beschikbaar voor inspectie. Verschillende programma's blijven
als afzonderlijk benoemde opnames bewaard; de kaartsamenvatting is een algemene
apparaatsamenvatting, geen programmaspecifieke voorspelling.

## Oude sessies

Automatische sessiedetectie is voor deze inleerfase uitgeschakeld. Bestaande
automatisch opgesplitste sessies tellen niet mee in het handmatige leerprofiel.
Via **oude automatische sessies wissen** verwijder je die historie voor het
apparaat, na bevestiging. Handmatige opnames blijven daarbij bewaard.

Automatisch herkennen van programma's, leren van start-/stopdrempels en het
gebruiken van profielen in PicoT's planning zijn vervolgstappen.

## EV-regelwaarde observeren (schaduw)

Deze optionele functie schakelt niets en is niet geschikt als actieve netmeter.
Zet `regulation_shadow_enabled` aan om iedere seconde de ingestelde RAW-netmeter,
EV-meter en getekende Zendure-terugmelding te lezen. Het gewone leerinterval
blijft onafhankelijk. De uitvoer is uitsluitend
`sensor.picot_ev_regulation_shadow`; de bestaande CT-sensor wordt niet geschreven.

`last_reported` moet aanwezig zijn, met tijdzone. Een ontbrekende rapporttijd,
een RAW- of EV-bron ouder dan 3 seconden of die bronnen meer dan 2 seconden uit elkaar geven
`unavailable` met een reden. `last_changed` en het moment van ophalen worden
niet gebruikt als bewijs van verse meting. Bij RAW en EV zijn nieuwe uitleesrapporten nodig, ook als hun vermogen gelijk blijft.
De leeftijd van de batterijrapportage is diagnostiek en blokkeert de vrijgave niet.

Attributen tonen RAW, EV, batterij, bronleeftijden, tijdverschil, uitgesloten EV
vermogen en de kandidaatregelwaarde. Vermogen is positief voor import/laden.
De kandidaat sluit EV alleen uit van een tekort; echt PV-overschot blijft
beschikbaar. Tijdens EV-laden wordt de toegestane netvraag in stappen van 20 W
richting nul afgerond, met een conservatieve 20 W update-dodeband. Verminderingen,
nul en richtingswisselingen gaan direct door. Zonder EV is de kandidaat exact RAW.

Dit is een zelfstandige schaduwproef: niet verbinden met @gielz of HEMS. Een
`unavailable` schaduwsensor stopt de batterij niet. Voor actieve ingebruikname
moet het gedrag van de originele @gielz-consument bij meetverlies offline worden
getoetst; de bestaande noodstop wacht een minuut. @gielz blijft ongewijzigd.

Terugval van de schaduwproef: optie uitzetten. De actieve integraties zijn er
niet afhankelijk van. Release en live installatie zijn afzonderlijke stappen.

## Experimentele gecombineerde EV-test (0.3.0-dev.2)

De shadowproef is uitgebreid met een optionele lees-API en een afzonderlijk
beleidssnapshot voor HEMS dev.288. De opties `regulation_api_enabled`
en `regulation_control_enabled` staan standaard uit. De API gebruikt de echte
RAW-P1, actueel getekend Zendurevermogen en de EV-meter; ze regelt geen actuator.

Volg [de gezamenlijke installatie- en terugvalhandleiding](../homeassistant/energy_devices/README.md).
De bestaande CT REST-definitie krijgt de Energy Devices-API als bron. De
@gielz-integratie en automatiseringen blijven volledig origineel. HEMS blijft
RAW meten. De
shadow-entiteit zelf wordt niet als regelsensor gebruikt. Een live sessie is
nog nodig om firmware, meetvertragingen en HA-scheduling te beoordelen.

## EV-laadsessies (experimenteel)

### Optionele lokale Shelly-meetbron

Voor een Shelly Plug S Gen3 die via HA ongeveer iedere minuut rapporteert:

```yaml
ev_local_rpc_url: "http://192.168.6.113/rpc/Switch.GetStatus?id=0"
```

Na opslaan en herstart haalt Energy Devices eenmaal per seconde de lokale status
op. Sessies en EV-regeling delen dezelfde uitlezing: `apower` in W en `output`
als fysieke switchstatus. Schakelen blijft via de expliciet gekozen HA-switch.
Controleer dat het URL-adres en de gekozen switch dezelfde fysieke plug zijn.
De bestaande HA-vermogenentiteit hoeft niet sneller te rapporteren.

De request-starttijd dateert de lokale observatie; cachelezen vernieuwt die tijd
niet. De API levert geen afzonderlijke sampletijd voor `apower`, dus snelle interne
meetverversing moet live worden getest met opeenvolgende antwoorden en laadstart/stop.
Een timeout (2 seconden), ongeldige response of observatie ouder dan 3 seconden
blokkeert een nieuwe EV-correctieberekening. De hieronder beschreven korte
overbrugging kan de laatst geldige correctie behouden. Er is geen stille overstap
naar een oude HA-EV-waarde.
De bestaande onafhankelijke HA RAW-terugval blijft verantwoordelijk voor P1.
Het snapshot toont `ev_measurement_source: local_rpc` en behoudt bij blokkade de
werkelijke reden. Een lege URL behoudt de bestaande HA-meetroute.

Schakel `ev_sessions_enabled: true` in. Voor deze installatie:

```yaml
ev_power_entity: sensor.shellyplugsg3_d885ac1e8c94_vermogen
ev_switch_entity: switch.shellyplugsg3_d885ac1e8c94
```

1. Sluit de auto aan en zet de plug aan. De eerste nieuwe geldige meting boven 2000 W herkent direct een sessie; er is geen ingebouwde wachttijd.
2. Controleer de sessie in de EV-laadtijdlijn. Het gemeten vermogen wordt direct overgenomen; vul de duur zelf in. De herkenningsmeting mag maximaal 75 seconden oud zijn en mag niet van vóór het inschakelen van de plug dateren. Meetleeftijd en blokkeerreden zijn zichtbaar. Actieve meetbeschikbaarheid en HEMS behouden hun afzonderlijke versheidscontrole. Meetgaten boven 15 seconden worden niet als geleverde energie ingevuld.
3. Schakel de plug uit en weer in. Controleer werkelijk laadvermogen en bevestig pas daarna **Hervatten getest en geslaagd**.
4. Zet de plug uit. Kies een toekomstige lokale starttijd, vermogen en duur; bevestig de sessie. De eindtijd is een harde bovengrens, niet bewijs dat de auto vol is.
5. Energy Devices schakelt bij start in, herkent vijf minuten lage beschikbare belasting als natuurlijk einde en schakelt uiterlijk bij de bevestigde eindtijd uit. Uitval van de meting bewijst geen einde. Geleverde energie is een integratieschatting; meetgaten blijven zichtbaar.
6. Handmatig uitschakelen tijdens een eigen run onderbreekt de sessie; de app schakelt niet direct tegen je in. Gebruik **Onderbroken sessie hervatten** voor expliciet hervatten binnen het venster.
7. Expliciet annuleren schakelt de gekozen laadplug uit en wacht op bevestiging via de switchstatus.

De Energy Devices-snapshot staat in `sensor.picot_ev_session_snapshot`. HEMS moet een versie met sessie-ingestie gebruiken en de opties hieronder hebben:

```yaml
energy_device_sessions_enabled: true
energy_device_session_entity: sensor.picot_ev_session_snapshot
p1_power_entity: sensor.ct_shelly_pro_3em_api_raw_2
```

Laat EV-correctie tijdens de eerste uitvoeringstest uit. Prognose werkt onafhankelijk daarvan; batterijbescherming wordt uitsluitend uit de afzonderlijke verse regelpolicy afgeleid. Bij een bevestigde sessie gebruikt HEMS alleen historische basislast met bewezen EV-meetdekking. Ontbreekt die dekking, dan gebruikt het de bestaande conservatieve terugval en actuele basislastcontrole. Oude EV-belasting wordt niet geraden of dubbel toegevoegd. BMW-informatie wordt in deze eerste versie niet gebruikt omdat geen BMW-bron is geconfigureerd.

Na een add-oncrash kan de plug aan blijven; bij hervatten wordt de bevestigde eindtijd opnieuw toegepast. Annuleer een geplande/actieve sessie en controleer de fysieke plug vóór uitschakelen/verwijderen van de add-on. De onafhankelijke P1 RAW-terugval blijft functioneren zolang HA draait.


## Bewaking van de aangeboden correctie

De berekening voor avond en PV blijft gelijk. `regulation_offered_entity` wijst
naar de sensor die @gielz werkelijk ontvangt: standaard
`sensor.ct_shelly_pro_3em_api`. Energy Devices leest die entiteit uitsluitend;
@gielz behoudt zijn eigen marges, triggers, modi en acties.

De bewaking vergelijkt deze ontvangen waarde met de berekende P1-kandidaten
van de laatste vijf seconden, met 50 W tolerantie. Daardoor worden opeenvolgende
metingen vergeleken met de bijbehorende correcties, ook bij snelle EV-, oven-
of PV-stappen. Een gelijkblijvende waarde is geen fout. Laden/ontladen wisselen
of fysieke P1 rond nul zijn geen vrijgave- of blokkeercriteria. Deze bewaking
bewijst de overdracht van de correctie, niet de fysieke batterijrespons.

Bij 30 seconden aanhoudende afwijking wordt de correctie vergrendeld uitgezet.
Bij tien seconden aanhoudend ontbrekende/ongeldige metingen gebeurt hetzelfde.
De API geeft dan HTTP 503; de onafhankelijke HA-selector biedt RAW aan. De
reden staat op `sensor.picot_ev_regulation_policy` en de schaduwsensor als
`offered_correction_mismatch` of `persistent_measurement_loss`, met
`correction_guard: latched` en `fallback: latched_raw_fallback`.

Een korte meetonderbreking mag de laatste geldige correctie behouden, uiterlijk
tien seconden vanaf de oorspronkelijke bronmeting. `holding_measurement: true`
en `reason: short_measurement_gap` maken dit zichtbaar. De oorspronkelijke
`measured_at` blijft staan. Herstel levert direct een nieuwe kandidaat; er is
geen nieuwe eis van drie opeenvolgende vrijgaven. Bij een vastgelopen of gestopte
add-on verloopt de API-producerheartbeat na drie seconden en neemt HA RAW over.
De vergrendeling overleeft een herstart. Reset na onderzoek door
`regulation_control_enabled: false` op te slaan en de add-on te herstarten,
daarna expliciet weer inschakelen en herstarten.

Voor een al gemigreerde HA-configuratie: houd correctie uit, wijzig uitsluitend
in de bestaande CT-selector `api_measurement_age <= 3` naar
`api_measurement_age <= 10`. Behoud `api_report_age <= 3`, de echte RAW-bron,
entity-ID's en @gielz. Zie
[het bijgewerkte fragment](../homeassistant/energy_devices/ct_regulation_fallback_fragment.yaml).
Controleer de HA-configuratie vóór herladen/herstarten. Zonder deze wijziging
valt HA tijdens de overbrugging al na drie seconden terug. HEMS behoudt zijn
bestaande verse-policycontrole; oude metingen worden niet vernieuwd voor planning.

Deze offline getoetste bewaking is nog geen bewijs van live stabiliteit. Controleer
na installatie de aangeboden correctie, start/stop en PV met de diagnostiek.


## Diagnose downloaden

Het dashboard van Energy Devices bevat **Diagnose downloaden**. De ZIP bevat:

- `manifest.json`: softwareversie, gebruikte opties/bronentiteiten, meetdekking,
  aantal nog wachtende of gemiste registraties en eventuele schrijffout.
- `measurements.jsonl`: maximaal één registratie per seconde per functie over
  de laatste 48 uur. RAW, bedoeld regelvermogen, vrijgegeven kandidaat,
  daadwerkelijk gelezen CT-vermogen, batterij en EV hebben aparte velden.
  Fysieke meettijden blijven onderscheiden van het registratietijdstip.
- `events.jsonl`: blijvende historie van statuswijzigingen, overbruggingen,
  waargenomen selector-terugvallen, EV-/plugtransities en herstarts.
- `README.txt`: betekenis en beperkingen van de registratie.

Een vergrendeling bewaart nu `latched_at` en `latched_origin`, inclusief de eerste
foutreden, betrokken bron en beschikbare meetcontext. Die gegevens blijven na
herstart staan, ook wanneer de bronnen inmiddels weer geldig zijn. Voor oude
vergrendelingen zonder deze context worden tijdstip en aanleiding niet geraden.

De registratie begint na installatie van deze uitbreiding en volgt de
ingeschakelde EV-sessie-/regelfuncties. Zonder die functies is er geen volledige
meetgeschiedenis. De werkelijk aangeboden CT wordt uit de bestaande actieve
bewakingsuitlezing overgenomen; bij uitgeschakelde correctie kan die ontbreken.
Een ontbrekende meting wordt als ontbrekend bewaard, niet als nul.

Registratie gebruikt een eigen wachtrij, achtergrondschrijver en database in
`/data/picot_energy_diagnostics.sqlite3`. Volle wachtrij of schrijfproblemen
werpen geen uitzondering naar de regeling; gemiste registraties worden zichtbaar
in de diagnose. Herstelde logging bewaart ook een gebeurtenis met die fouttelling.
De meetdatabase ruimt oude samples periodiek op en hergebruikt vrijgekomen
ruimte. Het gebeurtenissenlog blijft behouden. De ZIP bevat alleen toegestane
instellingen en diagnosevelden, geen Supervisor-token, volledige options.json,
laad-API-URL of volledige apparaatdatabase. Behandel bronentiteiten en gebruiks-
tijden in het bestand als gegevens over je eigen installatie.

De diagnoseknop leest uitsluitend gegevens en wijzigt geen sessie, correctie,
vergrendeling, HEMS-plan of @gielz-instelling. Live vergelijking blijft nodig;
batterijvermogen is de ingestelde bron en niet een onafhankelijk gevalideerde
AC-meting. Deze uitbreiding verandert de correctieberekening en drempels niet.
