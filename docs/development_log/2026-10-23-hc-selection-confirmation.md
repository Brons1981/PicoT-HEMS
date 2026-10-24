# HEMS-keuze koppelen en terugmelden

HC kan nu een HEMS-keuze koppelen aan de eigen, nog geldige lokale variant,
die keuze opslaan en terugmelden. HEMS controleert de terugmelding tegen zijn
eigen laatst gepubliceerde beoordeling. Het betreft bevestiging van een advies;
het is nog geen definitieve uitvoeringsafspraak of energiereservering.

## HC-controles en opslag

De bestaande controle op verzoek, revisie, prognosebasis, vingerafdruk,
vervangingsbasis, vervaltijd en gekozen variant blijft gelden. Daarnaast moet
het verzoek in Home Assistant exact overeenkomen met het actuele lokale
voorstel. Alleen een variant waarvoor HC nog een bijbehorend lokaal recept
heeft, kan worden bevestigd. De voorstelgenerator heeft dat voorstel in
dezelfde regelronde opnieuw op de actuele voorwaarden gecontroleerd.

De gekozen variant wordt vóór publicatie in SQLite opgeslagen. Het bestand
bevat zowel de generieke bevestiging als de lokale temperatuur en eventuele
starttijd. Maximaal 96 keuzes blijven als historie bewaard. Een herstart
activeert geen opgeslagen keuze. Herhaalde bevestiging verlengt de vervaltijd
niet. Een ingetrokken of verlopen voorstel levert een ingetrokken bevestiging.

De nieuwe sensor `sensor.picot_hc_energy_selection` gebruikt contract
`hc-energy-selection:v1`. Het bericht bevat verzoek- en plan-ID's, revisie,
basisverwijzingen, vingerafdruk en geldigheid. Temperatuur en apparaten blijven
lokaal. `execution_authorized` is altijd false.

## Controle door HEMS

HEMS vergelijkt de terugmelding met zijn eigen actuele beoordeling. Een
onbekende variant, andere vingerafdruk, gewijzigde revisie, verlopen bericht
of uitvoeringsvlag true wordt geweigerd. Na het ophalen controleert HEMS
opnieuw of het verzoek nog hetzelfde en de bevestiging nog geldig is.
De geldige bevestiging blijft alleen tijdelijk in de adviesmodule beschikbaar;
de batterijroute en MEP worden hierdoor niet aangepast.

Tijdens opeenvolgende runtime-aanroepen kan de bestaande achtergrondworker
ook tussen de prognosepublicaties een bevestiging ophalen, begrensd op eenmaal
per vijftien seconden zolang een geldige gekozen beoordeling beschikbaar is.
De daadwerkelijke frequentie blijft afhankelijk van de aanroepen vanuit de
runtime. De volledige prognosepublicatie blijft begrensd op eenmaal per minuut.
Dezelfde worker-lock voorkomt overlappende controles; er is geen extra planner
of parallelle apparaatsturing toegevoegd.

## Weergave en grenzen

Het HC-dashboard toont welke temperatuur en eventuele starttijd lokaal zijn
gecontroleerd en teruggemeld. Het scherm claimt daarmee geen bevestigde
uitvoering of ontvangstbewijs van HEMS. Uitvoering, langdurige commitment,
reservering van energie en herstel bij een gemiste start moeten nog apart
worden gekoppeld. De huidige adviesgeldigheid wordt daarvoor niet stilzwijgend
verlengd. Er is geen release of live activering uitgevoerd.

## Verificatie

De gecombineerde regressiesuite slaagde met **155 tests in 28,69 seconden**.

Tests doorlopen een echte HEMS-beoordeling, HC-validatie, SQLite-opslag en
terugmelding naar HEMS. Ze controleren verkeerde ID's, revisies en
vingerafdrukken, ontbrekende lokale plannen, ongeldige uitvoeringsvlag,
verbindingverlies, vervallen en tijdens ophalen ingetrokken verzoeken,
herstart en ongewijzigde batterijroute. Een klokgestuurde test bevestigt dat
een antwoord tussen twee minuutpublicaties kan worden verwerkt zonder nieuwe
prognosepublicatie.

Ruff, JavaScript-syntaxcontrole en git diff-controle slaagden. Live Home
Assistant en browserweergave zijn niet getest; extern transport is in de
tests vervangen.
