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
een bron ouder dan 3 seconden of bronnen meer dan 2 seconden uit elkaar geven
`unavailable` met een reden. `last_changed` en het moment van ophalen worden
niet gebruikt als bewijs van verse meting. Controleer live dat elke bron ook
bij gelijkblijvend vermogen nieuwe rapporttijden krijgt.

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
beleidssnapshot voor HEMS dev.287-evtest.2. De opties `regulation_api_enabled`
en `regulation_control_enabled` staan standaard uit. De API gebruikt de echte
RAW-P1, actueel getekend Zendurevermogen en de EV-meter; ze regelt geen actuator.

Volg [de gezamenlijke installatie- en terugvalhandleiding](../homeassistant/energy_devices/README.md).
De bestaande CT REST-definitie krijgt de Energy Devices-API als bron. De
@gielz-integratie en automatiseringen blijven volledig origineel. HEMS blijft
RAW meten. De
shadow-entiteit zelf wordt niet als regelsensor gebruikt. Een live sessie is
nog nodig om firmware, meetvertragingen en HA-scheduling te beoordelen.
