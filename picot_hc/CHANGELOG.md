# Changelog

## 0.1.0-dev.12

- Bevestigde Ecowitt-temperatuur en vochtmetingen voor drie zones en buiten.
- Buitenluchtvochtigheid uitlezen, opslaan en tonen bij gezamenlijke metingen.
- Badkamer-energiemeter toegevoegd naast de bestaande vermogensmeting.
- Lege bestaande opties aangevuld; eigen entiteiten en comfortinstellingen behouden.

## 0.1.0-dev.11

- Daggroepen, losse dagkeuze en dupliceren; meerdere vensters per dag.
- Eén temperatuur en comfortvinkje per venster; centrale optimalisatieband.
- Comfort is een vast doel zonder economische afwijkingsruimte.
- Dev.10-gegevens gearchiveerd; gewijzigde grenzen vragen controle.
- Comfort blijft plannerinvoer zonder automatische apparaatopdrachten.

## 0.1.0-dev.10

- Bronvrij comfortschema beneden met begin/einde, harde ondergrens en flexibele band.
- Plannerinvoer met comfortdeadlines; vaste doelen voor boven en badkamer.
- Handmatige brontemperatuur als gedwongen bron met status, zones en eindmoment.
- Directe dev.9-schemasturing vervalt; financiële planning volgt later.
- Bestaande schema’s worden gearchiveerd en uitgeschakeld naar vensters omgezet.

## 0.1.0-dev.9

- Bewerkbaar weekschema beneden, standaard uit, met gekozen cv of airco.
- Handmatige wijziging pauzeert tot volgend schemamoment of HC hervatten.
- Actuele meting, comfortgrenzen, broncapaciteiten en achterdeur bewaken uitvoering.
- Geen herhaling van onzekere opdrachten; schema en pauze blijven bewaard.

## 0.1.0-dev.8

- Cv-temperatuurbediening hersteld wanneer climate.huiskamer geen stapgrootte meldt.
- Gebruik in dat geval de door de gebruiker bevestigde stap van 0,5 °C.

## 0.1.0-dev.7

- Bedieningsknoppen werken ook bij lokale HA-toegang via HTTP zonder randomUUID.
- Fouten bij het voorbereiden van een opdracht worden zichtbaar bij de knop.

## 0.1.0-dev.6

- Handmatige bronbediening voor cv, beide airco’s en badkamerverwarming.
- Duurzame opdrachtregistratie, HA-terugmeldingen, timeouts en foutstatussen.
- Geen automatische herhaling; Uit kan een wachtende opdracht vervangen.
- Schema, overrides, deurregeling en automatische prijsplanning blijven vervolgwerk.

## 0.1.0-dev.5

- Shelly-vermogensmeter en energiemeter gekoppeld aan airco boven.
- Lege velden in bestaande configuratie worden voor deze airco automatisch aangevuld.

## 0.1.0-dev.4

- Huidige Nordpool-prijsbron als werkelijk tarief bevestigd door gebruiker.
- Neerslaghoeveelheid uit de dagverwachting verwijderd op verzoek; weertype en neerslagkans blijven zichtbaar.

## 0.1.0-dev.3

- Weerkaart via weather.buienradar met actuele metingen en dagverwachting.
- Verwachting bewaren met ontvangsttijd, eenheden en fout-/verouderingsmelding.
- Weer blijft informatie; automatische klimaatreacties volgen later.

## 0.1.0-dev.2

- Minimum, gewenste temperatuur en maximum per zone instellen en opslaan op het dashboard.
- Waarden blijven bewaard na herstart; geen HA-verbinding of nieuwe meting nodig.
- Invoervalidatie en behoud van onopgeslagen invoer tijdens verversen.
- Nog steeds observatie: instellingen sturen geen apparaten aan.

## 0.1.0-dev.1

- Zelfstandige observatie-app voor beneden, boven en badkamer.
- Eigen meetopslag, temperatuurgeschiedenis en elektriciteitsprijsgrafiek.
- Configuratie en Ingress via Home Assistant.
- Installatie via dezelfde repository als PicoT HEMS en Energy Devices.
- Nog geen apparaatbediening of automatische prijsoptimalisatie.
