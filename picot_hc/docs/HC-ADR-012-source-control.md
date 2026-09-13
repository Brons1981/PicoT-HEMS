# HC-ADR-012 — Bronbediening en terugmelding

Status: implementatie van de door gebruiker gevraagde eerste bedieningsstap.

## Wijzigingscontract

Tot dev.5 leest HC alleen en kan bronbediening niet worden beproefd. Deze wijziging
voegt expliciete handmatige opdrachten toe vanuit het HC-dashboard. Eigenaren:
HC-configuratie, bronadapter, opdrachtopslag en terugmelding; HC-ADR-006/010 blijven
leidend. HEMS, automatische zoneregeling en prijsplanning vallen buiten scope.
Elke opdracht is herleidbaar tot een klik, bron, gewenste waarde en tijdstip.

## Contract

- Alleen ingestelde bronnen: airco beneden, airco boven, cv en badkamerschakelaar.
- Klimaatmodus en apparaattemperatuur worden afzonderlijk ingesteld. De modus
  auto betekent de apparaatregeling, niet een actieve HC-planner.
- Actuele HA-capaciteiten, beschikbaarheid, grenzen en stapgrootte bepalen wat mag.
  Temperatuurbediening vereist een bevestigde HA-eenheid °C en een enkel setpoint.
- Bediening vereist Ingress/CSRF en een verse uitlezing. Geen actie bij starten,
  herstart, dashboardverversing of herstellen van een verbinding.
- Opdracht vóór verzending duurzaam registreren. Request-ID voorkomt dubbel
  verzenden bij herhalen van een HTTP-verzoek. Geen automatische retries.
- HTTP-succes bevestigt alleen ontvangst door HA. Een latere onafhankelijke
  uitlezing die de gewenste instelling rapporteert bevestigt de instelling.
- Een bestaande gelijke instelling veroorzaakt geen onnodige opdracht.
- Eén lopende opdracht per apparaat; een expliciete uit-opdracht mag voorgaan.
- Ontbrekende bevestiging na de instelbare wachttijd wordt zichtbaar. Herstart
  onderbreekt de bewaking en speelt een opdracht nooit opnieuw af.
- hvac_action en vermogen zijn aparte observaties. Een ingestelde modus heat
  bewijst geen geleverde warmte en een HA-terugmelding is geen fysieke meting.
- Opdrachten en laatste terugmelding blijven bewaard; interface toont recente
  opdrachten. Handmatige bronbediening zet geen automatische klimaatregeling aan.

## Vastgelegde vervolgbesluiten

Het basisschema beneden wordt bewerkbaar op het dashboard. Een wijziging via
thermostaat of HA geeft een tijdelijke override, tot het volgende schakelmoment
of de knop HC hervatten. Eigen HC-opdrachten en vertraagde terugmeldingen mogen
geen valse override geven. De gezamenlijke cv respecteert deze keuze ook voor boven.
De achterdeur hoort bij de eerste zoneregeling: instelbare open-/sluitvertraging,
airco beneden pauzeren en geen voorverwarmen bij langdurig openen. Cv-vraag boven
blijft een aparte afweging. Onbekende deurstatus is niet automatisch dicht.
Deze automatische regels zijn nog niet actief in deze handmatige bedieningsstap.

## Verificatie en terugrol

Echte HTTP-tests van opdrachten, onafhankelijke feedback, grenzen, afwijzingen,
timeout, idempotentie, opslagfouten en herstart. Browsercontrole van bediening.
Na merge: eerst bron voor bron testen op echte HA en apparaatrespons vergelijken.
Terugrol naar dev.5 verwijdert de bedieningsmogelijkheid maar draait een reeds
verzonden apparaatinstelling niet terug. Opdrachtdata blijven in een aparte tabel.

Interfacebronnen: [HA Climate](https://www.home-assistant.io/integrations/climate/)
en [HA Switch](https://www.home-assistant.io/integrations/switch/).
