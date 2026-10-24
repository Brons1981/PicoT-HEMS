# Opwarmvoorstellen voor beoordeling door HEMS

HC kan de gemeten opwarmenergie en het gemeten handhaafverbruik nu samen
gebruiken voor een pakket voorstellen. Deze stap betreft alleen voortzetting
van een al bevestigde opwarming met de airco beneden. Er is geen uitvoering
van de HEMS-keuze, release of live activering toegevoegd.

## Varianten en voorwaarden

Bij een flexibel comfortvenster onderzoekt HC het schemadoel, een halve graad
lager en een halve graad hoger. Alleen doelen binnen de comfortband en binnen
de ondersteunde temperatuurstappen van de airco komen in aanmerking. Bij een
hard comfortvenster wordt alleen het schemadoel onderzocht. Het pakket bevat
dus één tot drie kandidaten, binnen het bestaande maximum van vijf.

Iedere kandidaat vereist afzonderlijk minstens drie passende opwarmmetingen
en drie passende perioden van temperatuur handhaven. Ontbrekend bewijs
verwijdert die kandidaat; zonder kandidaten wordt geen voorstel aangeboden.
De bestaande marges en vergelijkingsgrenzen van beide modellen blijven gelden.
Er wordt niet geëxtrapoleerd naar andere doeltemperaturen zonder meetbewijs.

Een voorstel vereist een actief schema, ingeschakeld leren, een lopende
voorverwarmingsfase zonder huidig comfortvenster en geldige metingen van de
airco beneden. De CV moet uit staan. De bestaande controles op handmatige
bediening, deur, storingen en sensoren blijven via de meetcontext gelden.

## Gemeenschappelijke beoordelingsperiode

Alle kandidaten gebruiken dezelfde begin- en eindtijd. De begintijd ligt
minimaal twee minuten vooruit en binnen de toegestane HEMS-vervangingsperiode,
maar maximaal vijftien minuten vooruit. Voorafgaand daaraan blijft de bestaande
regeling voor alle kandidaten hetzelfde uitgangspunt.

Vanaf de begintijd reserveert het profiel de volledige geraamde opwarmenergie
en opwarmduur vanaf de huidige gemeten binnentemperatuur. Er wordt geen
veronderstelde voortgang vóór die tijd afgetrokken. Daarna volgt geraamd
handhaafverbruik, tot uiterlijk vijftien minuten na de comfortdeadline, begrensd
door het comfortvenster en de HEMS-horizon. Iedere kandidaat moet volgens de
raming uiterlijk bij aanvang van comfort zijn doel bereiken.

Opwarmenergie wordt gelijkmatig over de geraamde duur verdeeld. Dat is een
benadering van het vermogensprofiel; startpieken en ontdooicycli worden niet
afzonderlijk voorspeld. De volledige reservering en bestaande 25%-marges
beperken optimisme maar garanderen geen bovengrens of tijdig comfort. Dit is
advisering en geen bewijs dat automatisch uitvoeren verantwoord is.

## Uitwisseling en opslag

De kandidaten gebruiken het bestaande v2-vervangingscontract. HEMS ontvangt
alleen generieke tijdvakken en energie, zonder apparaten of temperatuurdoelen.
De lokale vertaling naar doelen en meetonderbouwing wordt vóór publicatie in
SQLite opgeslagen. MEP is niet gewijzigd.

Geldigheid is maximaal twee minuten en blijft vast bij herpublicatie. Verlies
van meetcontext, een gewijzigd schema of een relevante temperatuurverandering
trekt het voorstel in. Eén recent gebruikte HEMS-basis veroorzaakt niet telkens
een nieuw verzoek. De bestaande worker verzorgt publicatie en intrekking.
De interface toont het aantal varianten, doelen en beoordelingsperiode.

## Grenzen

De voorstellen plannen geen uitgestelde koude start of uitschakelperiode.
Startenergie vóór de eerste geldige opwarmmeting is nog niet gemodelleerd.
CV-alternatieven, wind, bewolking en volledige optimalisatie over de avond
blijven vervolgwerk. HEMS beoordeelt op de behouden batterijroute; een
geselecteerd voorstel stuurt geen apparaten en reserveert geen batterijenergie.

## Verificatie

De gecombineerde regressiesuite slaagde: **125 tests in 52,07 seconden**.

Tests bouwen de modellen op met echte waarnemingsreeksen en SQLite. Ze
controleren de drie varianten, dezelfde tijdgrenzen, energie in beide fasen,
harde comfortdoelen, ondersteunde stappen, deadline, ontbrekend bewijs,
uitgeschakeld schema, bronbinding, herpublicatie en intrekking. Een ketentest
stuurt het pakket door de echte HEMS-beoordelaar en leest het antwoord terug
via HC. De opgeslagen batterijroute blijft gelijk en uitvoering blijft uit.

Python-lint, JavaScript-syntaxcontrole en git diff-controle slaagden. Live
Home Assistant en browserweergave zijn niet getest; tests vervangen het
externe transport.
