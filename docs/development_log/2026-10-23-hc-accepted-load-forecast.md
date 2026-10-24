# Bevestigde HC-start meenemen in de HEMS-prognose

HEMS bewaart het zelf goedgekeurde energieprofiel voordat het starttoestemming publiceert. Pas nadat HC een daadwerkelijk bevestigde start meldt, wordt het resterende profiel meegenomen in volgende verbruiksprognoses. Alleen een keuze of toestemming activeert nog geen verbruik. Een opslagfout voorkomt nieuwe toestemming.

## Contract en levensduur

HC publiceert `hc-energy-execution:v1` op `sensor.picot_hc_energy_execution`, via de bestaande achtergrondpublisher. De melding bevat uitsluitend status, voorstelnummer, voorstelvingerafdruk, planidentiteit, verzendtijd van de bevestigde opdracht en meldtijd. HEMS gebruikt zijn eigen opgeslagen energieprofiel; HC kan via deze melding geen energiehoeveelheden of apparaatdetails toevoegen. MEP ontvangt alleen de aangepaste algemene verbruiksprognose.

Een melding vereist verse apparaatwaarnemingen en een bevestigde startopdracht. HEMS controleert de identiteit, de oorspronkelijke geldigheid van de starttoestemming, de profielperiode en een meldleeftijd van maximaal 120 seconden. Onbekende, toekomstige, verlopen of afwijkende meldingen activeren niets. Een verse melding mag een eerder uitgevoerde geldige start bevestigen nadat de oorspronkelijke toestemming is verlopen.

De SQLite-opslag `/data/picot_v2_accepted_loads.sqlite` bewaart uitgegeven profielen en de laatste uitvoering per meetbron. Verlopen advies, ontbrekende telemetrie en een HEMS-herstart wissen een bevestigde uitvoering niet. Een bevestigde uitstand beëindigt het profiel; een latere melding van dezelfde uitvoering kan dat niet ongedaan maken. Zonder beëindigingsmelding vervalt de toevoeging uiterlijk aan het einde van het oorspronkelijke profiel. Een gewijzigde temperatuur of onbekende apparaatstand geldt niet als bewijs van beëindiging.

## Verwerking in de prognose

De gezamenlijke HEMS-invoerroute past het profiel toe nadat echte metingen zijn opgeslagen. Meetgeschiedenis blijft ongewijzigd. De bewerking splitst prognose-intervallen op de relevante grenzen en rekent alleen het nog resterende deel mee. Herhaalde toepassing op dezelfde invoer voegt niets opnieuw toe.

Alleen een actuele, passende en aantoonbaar toegeschreven historische component wordt vervangen. Andere huishoudelijke belasting, afzonderlijk toegerekend EV-verbruik en het beschermde venster voor actuele extra belasting blijven behouden. Zonder passende onderbouwing wordt het profiel conservatief toegevoegd; tijdelijk dubbel tellen is dan mogelijk en wordt in `accepted_load_conservative` gemeld. De diagnostiek bevat ook toegevoegde en vervangen Wh en het aantal actieve profielen.

Tijdens deze toevoeging wordt geen nieuwe vervangingsbasis aangeboden: een volgend HC-voorstel mag dezelfde historische component niet opnieuw gebruiken. Herplanning van een al lopend profiel vraagt een afzonderlijk vervolgcontract. Een gewijzigd actief profiel verandert de HEMS-invoersignatuur. De bestaande regels voor behoud van batterijafspraken blijven van kracht.

## Afbakening

- Alleen de al ondersteunde economische start beneden meldt uitvoering. De verwarmingsregelaar zelf verandert in deze stap niet.
- Dit is verwerking na bevestigde start, geen batterij- of SOC-reservering vooraf.
- Het profiel geldt alleen voor de oorspronkelijk goedgekeurde periode, niet automatisch voor alle daaropvolgende comforturen.
- Werkelijke HA-transporttiming, apparaten en besparingen zijn niet live getest. Geen installatie, commit, publicatie of activering uitgevoerd.

## Verificatie

De gerichte reeks telt 37 geslaagde tests en 6 subtests. Deze gebruikt de echte HC-regelaar en opslag met nagebootst HA-transport, plus echte HEMS-beoordeling en keuzebevestiging. Getest zijn bevestiging vóór melding, behoud na verlopen toestemming en herstart, expliciet beëindigen, ongeldige meldingen, opslagfouten, vernieuwde prognose-invoer, proportionele vervanging, conservatieve toevoeging, EV-behoud en ongewijzigde opgeslagen batterijroute.

Ruff slaagt voor de gewijzigde energiemodules en tests; F-controles slagen voor de grote runtimebestanden en de gedeelde HC-testfixture. `git diff --check` slaagt.

De volledige relevante regressiereeks slaagt: **210 tests en 6 subtests in 44,79 seconden**. Dit omvat `hc-comfort-work/tests` en de HC-reeksen voor energievoorstellen, outlook, opwarmenergie, opwarmplannen, volledige starts, uitgestelde starts, leren, startvoornemens en startuitvoering. Uitgevoerd met Python 3.14, pytest zonder cacheprovider, de beschikbare testafhankelijkheden en de lokale gewijzigde HEMS-modules vóór de referentiemodules op het importpad. De eerdere fouten in deze stap betroffen onvolledig vernieuwde verwijzingen in de testgegevens voor een nieuwe meetronde; die zijn gecorrigeerd voordat deze volledige reeks is gedraaid.
