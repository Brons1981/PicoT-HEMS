# HC-ADR-013 — Basisschema beneden en handmatige pauze

Status: eerste schema-uitvoering, door gebruiker gevraagd na bevestigde live
bronbediening en terugkoppeling van dev.8. Prijs- en aanwezigheidsregeling volgen.

## Contract

- Dashboardeditor: terugkerende weekdagen, tijden en temperaturen; lege start,
  standaard uit. Gebruiker kiest één bron: cv (ook boven) of airco beneden.
- Europe/Amsterdam; laatste moment geldt tot het volgende. Zomertijd: een niet
  bestaande lokale tijd wordt overgeslagen; een dubbel najaarsmoment loopt één keer.
- Activeren is een expliciete dashboardkeuze. Beneden vereist gekoppelde actuele
  °C-meting, meettijd en minimum/maximum. Meetleeftijd is instelbaar (start 900 s).
  Apparaatgrenzen en stapgrootte blijven gelden. Een andere actieve/onbekende bron
  blokkeert nieuwe sturing; HC kiest of schakelt geen bronnen automatisch om.
- Instellen gebeurt via `climate.set_temperature` met temperatuur en `hvac_mode:
  heat` in één HA-verzoek. De interne apparaatvolgorde wordt door de integratie
  bepaald; dit is geen bewijs van een atomaire fysieke wijziging. Beide instellingen moeten onafhankelijk terugkomen voordat de opdracht bevestigd is.
- Per schemadoel één duurzame opdracht, geen periodiek opnieuw instellen. Een
  onzekere opdracht wacht; fout/timeout vereist controleren en HC hervatten.
- Gewijzigde modus, doeltemperatuur of preset van cv/airco beneden via HA of
  thermostaat pauzeert het schema. Handmatige HC-bronbediening pauzeert vóór
  verzending. Hervat bij het eerstvolgende schemamoment of HC hervatten.
- Eigen opdrachten worden herkend aan geregistreerde gewenste/vorige waarden.
  Tijdens wachten is een oude waarde geen override; na bevestiging geldt een
  terugkeer naar de vorige waarde als wijziging. Activiteit is geen handmatige keuze.
  Detectie is op HA-uitlezingen; niet-gerapporteerde tussenliggende wijzigingen
  zijn niet zichtbaar. Een presetwissel tijdens het verwerken van een eigen opdracht
  kan zonder HA-causaliteitsbewijs niet van een gevolg daarvan worden onderscheiden.
- Vlak vóór verzenden: verse HA-uitlezing, opnieuw override, doel en blokkades toetsen.
  Collector, handmatige opdrachten en schemawijzigingen delen dezelfde uitvoeringslock.
- Achterdeur voor airco beneden: open-/sluitvertraging instelbaar (start 60/120 s).
  Langdurig open of onbekend blokkeert verwarmen; een door HC geregelde airco gaat
  uit, ook wanneer de temperatuurmeting inmiddels ontbreekt. Bij bevestigd gesloten hervat het actuele schemadoel na sluitvertraging.
  Handmatige pauze heeft voorrang. Cv-bovenregeling wordt hier niet toegevoegd.
- Schema uit stopt verdere opdrachten en laat de apparaatstand staan. Bron wisselen
  vereist eerst uitschakelen/opslaan; zet de oude bron zelf uit.
- Herstart bewaart schema en override. Een bevestigde actie wordt niet opnieuw
  afgespeeld; zonder bestaande override pauze tot volgend moment/hervatten.
  Onderbroken/onzekere actie blokkeert tot expliciete hervatting. Teruggezette klok
  blokkeert eveneens. Hervatten leest eerst de actuele HA-status.

Dit voegt uitsluitend opt-in schema-uitvoering toe aan HC-ADR-012. De eerdere regel
"geen automatische opdrachten" blijft gelden wanneer het schema uit staat. HEMS,
prijsoptimalisatie, aanwezigheid, bovenregeling en badkamervenster blijven ongewijzigd.

## Verificatie

Echte HTTP-/SQLite-tests van schema, gecombineerde opdracht, onafhankelijke
terugmelding, geen herhaling, handmatige override, hervatten, grensmoment, DST,
meetleeftijd, andere bron, deurvertragingen, storing, herstart en toegangscontrole.
Browser: editor, bewaren/herladen, concept behouden, activeren, externe wijziging,
HC hervatten, uitschakelen en mobiele breedte, met gesimuleerde HA-apparaten.
De gecombineerde opdracht en Ecowitt-rapportage moeten nog live worden bevestigd.

Bron: [HA set_temperature](https://www.home-assistant.io/actions/climate.set_temperature/).
