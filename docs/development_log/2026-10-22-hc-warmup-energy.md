# Gemeten opwarmenergie beneden

HC legt nu naast stabiel handhaven ook opwarmtrajecten van de airco beneden
vast. De bestaande comfortregeling blijft leidend. Deze stap levert de
meetbasis en een lokale raming; opwarmalternatieven aanbieden aan HEMS volgt
in een volgende stap. Er is geen release of live activering uitgevoerd.

## Gedrag

Een meting start tijdens automatisch voorverwarmen met ingeschakeld leren en
comfortschema. De airco moet onder beheer van HC staan, met bevestigde
verwarmingsstand en doeltemperatuur. De CV moet uit staan. De bestaande
voorwaarden voor geldige sensoren, deur, storingen en handmatige bediening
blijven gelden. Zowel de aparte kWh-teller als het vermogen worden gebruikt.

De beginmeting moet minimaal 0,5 graden onder het doel liggen. HC meet vanaf
de eerste geldige waarneming tot de doeltemperatuur twee minuten achtereen
bereikt blijft. Dit is dus een gemeten traject vanaf de opgeslagen
begintemperatuur; eventuele commandowachttijd en energie vóór die eerste
waarneming zijn niet inbegrepen. Een latere planner mag dit niet zonder meer
gelijkstellen aan een volledige koude start.

Een traject duurt minimaal vijf minuten en maximaal drie uur. Onderbrekingen
langer dan negentig seconden, tellerresets, gewijzigde bron of instellingen,
een gewijzigd schema, meer dan 1,5 graden verandering buiten of meer dan 0,3
graden daling vanaf de hoogste binnentemperatuur maken het traject onbruikbaar.
Het kWh-verschil moet overeenkomen met het geïntegreerde vermogen binnen
maximaal 10 Wh of 30% van het kWh-verschil. Dat is een plausibiliteitscontrole,
geen nauwkeurigheidsgarantie.

Een poging wordt vóór het meten opgeslagen. Een onderbroken poging wordt in
hetzelfde comfortvenster niet opnieuw gestart, ook niet na een herstart.
De overgang van voorverwarmen naar hetzelfde actieve comfortvenster mag wel
doorlopen. Alleen afgeronde geldige trajecten tellen als bewijs.

## Raming

Minimaal drie vergelijkbare trajecten zijn vereist. Bron, instellingen en
doeltemperatuur moeten overeenkomen; de begintemperatuur mag hoogstens 0,25
graden verschillen en de buitentemperatuur hoogstens 1,5 graden. Er wordt niet
naar een grotere temperatuurstijging geëxtrapoleerd. Maximaal 96 afgeronde
trajecten worden opgeslagen; alleen de afgelopen zeven dagen tellen mee.

De raming neemt de hoogste gemeten energie en de langste gemeten duur, beide
met 25% marge. Deze empirische marge biedt geen statistische garantie. Wind,
bewolking, zoninstraling en warmteopslag in muren en meubels zijn nog geen
modelvariabelen. CV-verbruik wordt niet afgeleid uit de algemene gasmeter.

De runtime en het dashboard tonen afgeronde en passende metingen, een lopende
meting en eventueel een raming. Er worden door deze stap geen nieuwe
apparaatcommando's gestuurd. Het bestaande onderhoudsvoorstel aan HEMS behoudt
zijn eigen meetbasis; de HEMS- en MEP-contracten zijn niet aangepast.

## Verificatie

De gecombineerde suite slaagde met **117 tests in 20,56 seconden**: de
HEMS-advies- en vervangingstests, HC-voorstellen, runtime, opwarmenergie en
bestaand leren van voorverwarmen. Alle onderstaande statische controles slaagden.

Gerichte tests controleren gemeten energie en duur, drie benodigde trajecten,
opslag en herstart, niet-passende omstandigheden, verlopen bewijs,
onderbrekingen, tellerreset, schemawijziging, uitgeschakeld leren en de overgang
naar comfort. Een runtime-integratietest voert een echte HC-opwarmperiode uit
met testtransport en controleert dat de adviesstap geen extra klimaatcommando's
geeft. De onafhankelijke referentie is 32 minuten bij 1.200 W = 640 Wh;
met 25% marge wordt de raming 800 Wh en 40 minuten.

Python-lint, Python-syntaxcontrole, JavaScript-syntaxcontrole en git
diff-controle zijn uitgevoerd. Live Home Assistant en de browserweergave zijn
niet getest; de externe communicatie is in de tests vervangen door transport
onder testbeheer.
