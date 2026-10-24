# Gewone voorverwarmstart laten wachten op de gekozen HEMS-start

De proefoptie in het comfortschema kan nu ook de gewone voorverwarmstart beneden uitstellen tot het gekozen HEMS-moment. Tot deze stap kon de economische start alleen eerder komen: zodra de gewone voorverwarming warmte vroeg, startte die direct en verviel het latere voornemen.

## Wanneer uitstel is toegestaan

Uitstel geldt uitsluitend vóór het volgende comfortvenster, bij een geldige keuze en actuele, exact passende HEMS-starttoestemming. Automatische verwarming, schema, leren en de bestaande proefoptie moeten aanstaan. Beide warmtebronnen beneden moeten uitstaan, zonder lopende opdracht of door HC beheerde bron. Bestaande handmatige bediening, bronstoringen, deurvoorwaarden, meetversheid en schema-/verwarmingsrevisies blijven leidend.

HC verwijdert alleen de warmtevraag die uit de gewone voorverwarming voortkomt. De actuele ondergrens uit het comfortschema blijft bewaakt, inclusief een eventueel hogere grens van adaptieve temperatuurverlaging. Het afkoelmodel moet voorspellen dat de temperatuur tot het gekozen moment boven die grens blijft.

Vervolgens schat het gemeten opwarmmodel de benodigde energie en tijd vanaf de verwachte temperatuur op het gekozen startmoment. Die moeten binnen het goedgekeurde profiel blijven. Tot de comfortdeadline moet bovendien minstens één regelinterval, met een minimum van 30 seconden, extra ruimte bestaan. De minimale uitschakeltijd moet het gekozen startmoment toelaten. Ontbreekt onderbouwing of wordt een grens overschreden, dan blijft het gewone verwarmingsbesluit gelden.

## Uitvoering en terugval

Tijdens het wachten toont de regeling `hems_waiting_start` met de reden “Wachten op gekozen HEMS-start; ondergrens bewaakt.” Het startvoornemen blijft beschikbaar voor nieuwe voorstellen en de voorlopige HEMS-reservering blijft vernieuwbaar. De bestaande bescherming tegen verschuiven van het vastgelegde startmoment blijft gelden.

Op het gekozen moment loopt de opdracht via de bestaande controller, minimale uitschakeltijd, verse HA-uitlezing, opslag vóór verzending en opdrachtbevestiging. Een verlopen of ingetrokken toestemming veroorzaakt vóór starten terugval op de gewone comfortregeling. Zodra die daadwerkelijk start, vervalt het uitgestelde voornemen. Er wordt geen reeds draaiende bron uitgezet om op een goedkoper moment te kunnen wachten. De bestaande temperatuurhandhaving na een economische start blijft bestaan.

Warmtevraag boven en de badkamerregeling blijven zelfstandig. Wanneer de oorspronkelijke bronkeuze CV voor beneden zou kiezen, wordt tijdens toegestaan uitstel de zelfstandige aircowarmtevraag boven behouden. Deze stap voegt geen economische CV-start of nieuwe batterijregels toe. Wachten en economische starts worden niet als een gewone volledige voorverwarmproef gebruikt om de vaste voorverwarmtijd te kalibreren.

De toelichting bij de bestaande proefoptie is bijgewerkt. De optie blijft standaard uit. Er zijn geen live instellingen veranderd en geen apparaten aangestuurd.

## Verificatie

De nieuwe regressietest faalde eerst doordat de echte HC-controller via het nagebootste HA-transport onmiddellijk een verwarmingsopdracht verstuurde op het gewone voorverwarmmoment. Na de wijziging blijft hij wachten, vernieuwt de reservering en start hij eenmaal op het gekozen moment. De test gebruikt de echte gemeten opwarm- en handhaafmodellen en opslag; alleen HA-transport en HEMS-berichten zijn nagebootst.

Aanvullend gecontroleerd: terugval naar gewone verwarming na verlopen toestemming zonder latere uit-opdracht; te lage temperatuur; ontbrekende meter of toestemming; gewijzigde buitentemperatuur; handmatige bronbediening; ontbrekende opwarmduur; onvoldoende tijdmarge; en zelfstandige verwarming boven terwijl CV in de oorspronkelijke bronkeuze goedkoper was. De gerichte reeks slaagt met 30 tests en 13 subtests. Ruff, `node --check` op app.js en `git diff --check` slagen.

Praktische opwarmprestaties, netwerktiming en financiële besparing zijn niet live bewezen. Geen commit, release of publicatie uitgevoerd.

Laatste volledige regressiereeks na alle codewijzigingen: **227 tests en 13 subtests geslaagd in 116,97 seconden**. Dit omvat `hc-comfort-work/tests` en de HC-reeksen voor energievoorstellen, outlook, opwarmenergie, opwarmplannen, volledige starts, uitgestelde starts, leren, startvoornemens en startuitvoering. Uitgevoerd met de lokale gewijzigde modules vóór de referentiemodules op het importpad, Python 3.14 en pytest zonder cacheprovider.
