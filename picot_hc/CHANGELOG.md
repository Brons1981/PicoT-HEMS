# 0.1.0-dev.26

- Behoud huisvermogen op het tablet wanneer de PV-omvormer in de nacht geen verse meting levert: neem alleen bij sun.sun below_horizon 0 W PV aan.
- Behoud verse PV-metingen en de controles op net- en batterijvermogen. Overdag of bij onbekende zonnestatus blijft ontbrekende PV onbekend.
- HEMS hoeft niet bijgewerkt te worden. Schakel na herstart de automatische HC-regeling weer in.

# 0.1.0-dev.25

- Werk de meegeleverde meldingsmodule bij naar de bestaande gedeelde versie; bestaande HC-meldingsaanroepen blijven gelijk.

- Voeg het zwarte lokale tablet-dashboard toe voor Safari: binnen/buiten, weer, P1, PV, batterijrichting, huisvermogen, SOC en actuele modus.
- Wijzig de kamertemperatuur beneden in stappen van 0,5 graden; toon het doel vijf seconden en daarna weer de meting.
- Bewaar de tijdelijke temperatuur tot de eerstvolgende schemaperiode, ook na herstart; toon klok/hand en HC-warmtevraag.
- Laat de bestaande HC-regeling de bron kiezen; respecteer bronoverrides, deurbeveiliging en meetkwaliteit.
- Optioneel via lokale poort 8100 met eigen tabletwachtwoord, standaard uit. Zie README voor activering en sensorinstellingen.
- HEMS blijft dev.324; geen planreset nodig. Schakel na herstart de automatische HC-regeling zoals gebruikelijk weer in.

# 0.1.0-dev.24

- Lees de actuele HA-bronrapportage ook voor de beneden-aircovermogensmeter, zodat een gecachte tijdstempel ongewijzigd vermogen niet onterecht afkeurt.
- Blijf echte veroudering en mislukte uitlezing weigeren; geen nulvulling of verruimde meettermijn.
- Publiceer een concrete foutreden voor HEMS dev.318.

# 0.1.0-dev.23

- Centrale comfortinstellingen beneden, met handmatige thermostaat zonder actief schema.
- Temperatuur handhaven zonder uitschakelen uitsluitend omdat het doel is bereikt.
- Begrensd bijleren van opwarmtijd en afkoeling, plus eerder afbouwen binnen de comfortmarge.
- Maximaal vijf airco/CV-energieplannen voor HEMS, met verse toestemming voor uitvoering.
- CV-keuze op basis van beneden; veilige overdracht van de airco boven met minimumlooptijd en uitschakelbevestiging.
- Vertraagde tapwatertoewijzing, expliciet geschatte CV-hulpstroom en optionele uurweeronderbouwing.
- Vereist HEMS 2.0.0-dev.315 voor de nieuwe planuitwisseling. Werk HEMS eerst bij.
- Automatische regeling staat na herstart uit. Controleer schema, bronnen en meldingen voordat je inschakelt; leren en gekozen starts uitvoeren zijn aparte opties.

# 0.1.0-dev.22

- Eigen fout- en herstelmeldingen via HA-events en centrale iPhone-blueprint.
- Ontdubbeling en bewaarde verzendwachtrij buiten de regelcyclus.

# Changelog

## 0.1.0-dev.21

- Ecowitt VPD correct uitlezen en tonen in hPa, overeenkomstig de werkelijke broneenheid.
- WH26-buitenbatterij gekoppeld aan binary_sensor.0_energie_gw1200a_wh26_battery.
- Bestaande lege en oude kanaal-1-batterijkoppelingen automatisch bijgewerkt.

## 0.1.0-dev.20

- Nieuwe Ecowitt-buitensensoren voor temperatuur, luchtvochtigheid, dauwpunt en VPD.
- Oude kanaal-1-buitenkoppelingen automatisch vervangen bij opstart; eigen afwijkende koppelingen behouden.
- Garage toegevoegd met temperatuur, vocht, dauwpunt, batterijmelding en klimaatgrafiek.
- Garage wordt alleen gemonitord: geen comfortdoel, warmtevraag of apparaatbediening.
- Cv-activiteit ook vastgelegd als context bij de garagemetingen; bestaande historie en bewaartermijn behouden.

## 0.1.0-dev.19

- Actuele temperatuur en ontvangsttijd samen ophalen via HA-sjabloon-API;
  voorkomt onterechte blokkering bij onveranderde Ecowitt-temperaturen.
- Dezelfde controle in meetopslag en direct v��r een bronopdracht.
- Werkelijk oude/toekomstige of ontbrekende meldingen blijven geblokkeerd.
- Duidelijke melding bij mislukte ontvangstcontrole; bestaande bronterugmelding
  blijft beschikbaar om eigen verwarming te stoppen.

## 0.1.0-dev.18

- Badkamertimer met instelbare duur en temperatuur, resterende tijd en stopknop.
- Tijdelijk badkamerdoel werkt onafhankelijk van algemene regeling en prijsgegevens.
- Terug naar vaste regeling na afloop; anders eigen badkamerverwarming uit.
- Handmatige voorrang, begrenzing, meetleeftijd en terugmelding blijven gelden.
- Herstart breekt timer af; eigen timerverwarming wordt gestopt zodra bereikbaar.

## 0.1.0-dev.17

- Opt-in automatische verwarming met gedeelde cv, beide airco's en badkamerschakelaar.
- Bronkeuze op geschatte actuele kosten, instelbare rendementen; cv neemt de plaats
  van beide airco's in wanneer de gezamenlijke comfortvraag dit toelaat.
- Hysterese, uitrusttijd, bevestigde bronwissels, handmatige voorrang, deurvertraging
  en meetleeftijd. Eigen bronnen stoppen bij weggevallen voorwaarden.
- Storing vergrendelt nieuwe opdrachten; geen automatische herhaling, expliciete
  vrijgave. Regeling staat na herstart uit; apparaatstanden blijven controleerbaar.
- Nog geen berekend voorverwarmen, automatisch ontvochtigen of ingeleerd woningmodel.

## 0.1.0-dev.16

- Eigen klimaatgrafiek per zone voor temperatuur, luchtvochtigheid en dauwpunt over de afgelopen 24 uur.
- Temperatuur en dauwpunt delen de �C-as; relatieve luchtvochtigheid gebruikt een aparte 0-100%-as.
- Meetwaarden aanwijzen, aantikken of met pijltjestoetsen bekijken. Ontbrekende waarden blijven onderbroken.

## 0.1.0-dev.15

- Woningmetingen bewaren nu binnen-buitenverschil, achterdeur en gemelde modus, activiteit en doeltemperatuur per warmtebron.
- Achterdeur zichtbaar bij beneden; bronrapportagetijden blijven bij de metingen bewaard.
- Volledige aanwezige meetreeks downloaden voor analyse en langer bewaren.
- Bestaande metingen blijven behouden; dit registreert gegevens zonder automatisch te verwarmen.

## 0.1.0-dev.14

- Dauwpunt van Ecowitt zichtbaar en opgeslagen per zone en buiten.
- Sensorbatterijen boven, badkamer en buiten als tekststatus, met opvallende melding bij bijna leeg.
- Nieuwe lege koppelingen automatisch ingevuld. Eigen koppelingen blijven behouden.
- Onbekende, ontbrekende of ongeldige batterijstatus wordt nooit als normaal getoond.

## 0.1.0-dev.13

- Eigen buitentemperatuur en luchtvochtigheid bovenaan bij de weerkaart.
- Ecowitt, actueel Buienradar en Buienradar-voorspelling duidelijk gescheiden.
- Bronmomenten en ontbrekende/verouderde gegevens blijven zichtbaar.

## 0.1.0-dev.12

- Bevestigde Ecowitt-temperatuur en vochtmetingen voor drie zones en buiten.
- Buitenluchtvochtigheid uitlezen, opslaan en tonen bij gezamenlijke metingen.
- Badkamer-energiemeter toegevoegd naast de bestaande vermogensmeting.
- Lege bestaande opties aangevuld; eigen entiteiten en comfortinstellingen behouden.

## 0.1.0-dev.11

- Daggroepen, losse dagkeuze en dupliceren; meerdere vensters per dag.
- E�n temperatuur en comfortvinkje per venster; centrale optimalisatieband.
- Comfort is een vast doel zonder economische afwijkingsruimte.
- Dev.10-gegevens gearchiveerd; gewijzigde grenzen vragen controle.
- Comfort blijft plannerinvoer zonder automatische apparaatopdrachten.

## 0.1.0-dev.10

- Bronvrij comfortschema beneden met begin/einde, harde ondergrens en flexibele band.
- Plannerinvoer met comfortdeadlines; vaste doelen voor boven en badkamer.
- Handmatige brontemperatuur als gedwongen bron met status, zones en eindmoment.
- Directe dev.9-schemasturing vervalt; financi�le planning volgt later.
- Bestaande schema's worden gearchiveerd en uitgeschakeld naar vensters omgezet.

## 0.1.0-dev.9

- Bewerkbaar weekschema beneden, standaard uit, met gekozen cv of airco.
- Handmatige wijziging pauzeert tot volgend schemamoment of HC hervatten.
- Actuele meting, comfortgrenzen, broncapaciteiten en achterdeur bewaken uitvoering.
- Geen herhaling van onzekere opdrachten; schema en pauze blijven bewaard.

## 0.1.0-dev.8

- Cv-temperatuurbediening hersteld wanneer climate.huiskamer geen stapgrootte meldt.
- Gebruik in dat geval de door de gebruiker bevestigde stap van 0,5 �C.

## 0.1.0-dev.7

- Bedieningsknoppen werken ook bij lokale HA-toegang via HTTP zonder randomUUID.
- Fouten bij het voorbereiden van een opdracht worden zichtbaar bij de knop.

## 0.1.0-dev.6

- Handmatige bronbediening voor cv, beide airco's en badkamerverwarming.
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

