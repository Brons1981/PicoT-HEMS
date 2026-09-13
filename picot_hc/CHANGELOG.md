# Changelog

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
