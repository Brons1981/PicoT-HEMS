# Automatisch HC-voorstel voor temperatuur handhaven

HC kan nu bij een actief comfortschema en ingeschakeld leren automatisch
een voorstel voor voortgezet temperatuur handhaven beneden aan HEMS aanbieden.
Dit is de eerste onderbouwde variant, geen volledige warmteoptimalisatie.
Er is geen uitvoering van een HEMS-keuze toegevoegd en niets live geactiveerd.

## Meetbasis

Het nieuwe energiemodel gebruikt uitsluitend de bevestigde aparte meter van
de airco beneden. HC moet de airco zelf beheren, de gewenste temperatuur moet
bevestigd zijn, de CV moet uit staan en de bestaande controles voor verse
sensoren, deur, handmatige bediening en storingen moeten geldig zijn.
De kamertemperatuur moet binnen 0,3 graden van de doeltemperatuur liggen.

Een meetperiode duurt minimaal twintig minuten. Onderbrekingen, tellerresets,
wijzigingen van bron, doeltemperatuur of ventilatorinstelling en te grote
temperatuurvariatie breken de periode af. Het gemeten kWh-verschil wordt
vergeleken met het geïntegreerde vermogen. Onverklaarbare afwijkingen worden
niet als leervoorbeeld opgeslagen. Alleen afgeronde perioden blijven na
een herstart bewaard; een onderbroken periode wordt nooit hervat.

Voor een raming zijn drie passende, niet-overlappende perioden nodig.
HC vergelijkt bron, instellingen, binnentemperatuur en buitentemperatuur.
De raming gebruikt het hoogste passende gemiddelde vermogen plus 25%.
Deze marge is een praktische schatting, geen statistische bovengrens.
Maximaal 96 perioden uit de afgelopen zeven dagen worden bewaard.

## Voorstel en geldigheid

HC verstuurt één kandidaat via het bestaande v2-vervangingscontract. HEMS
ontvangt een energieprofiel en basisverwijzingen; apparaatinstellingen blijven
lokaal. Het voorstel blijft binnen het lopende comfortvenster en de door HEMS
aangeleverde vervangingsperiode, met maximaal dertig minuten vooruitblik.
Een voorstel vereist minimaal tien minuten bruikbare profielduur.

Een actuele passende HEMS-basis is verplicht. Een aangeboden voorstel krijgt
maximaal twee minuten geldigheid en behoudt zijn oorspronkelijke vervaltijd.
HC herhaalt geen nieuw verzoek voor dezelfde recent gebruikte basis.
Het lokale voorstel wordt vóór verzending opgeslagen, inclusief de
meetonderbouwing en schema-revisie. De publicatie loopt via één achtergrondworker;
een intrekking vervangt een nog wachtend voorstel.

Bij ontbrekende metingen, een gewijzigd schema, gewijzigde omstandigheden of
uitgeschakelde regeling wordt het voorstel ingetrokken. Fouten in deze
adviesketen onderbreken de thermostaat niet. De interface toont of HC wacht
op meetbewijs of een voorstel heeft aangeboden. De bestaande HEMS-beoordeling
toont afzonderlijk de uitkomst.

## Grenzen en vervolg

Dit model schat alleen kort voortgezet stabiel verwarmen. Het voorspelt nog
geen opwarmenergie, CV-verbruik, wind- of bewolkingseffecten, ontdooicycli of
opgeslagen warmte in muren en meubels. Er worden daarom nog geen automatische
opwarm-, afkoel- of CV-alternatieven aangeboden. Het voorstel verandert geen
apparaatcommando's, batterijplanning of energiereservering. MEP krijgt geen
apparaatkennis.

Een volgende stap vereist een afzonderlijk onderbouwd model voor opwarmenergie
en vervolgens vergelijkbare plannen binnen dezelfde comfortgrenzen.

## Verificatie

De gecombineerde gerichte suite slaagde met **86 tests**. Daarin zitten het
energiemodel, publicatie en intrekking, de echte HC-runtime, de bestaande
HEMS-historie en vervangingsbeoordeling en de keten van automatisch HC-verzoek
tot HEMS-uitkomst. De tests gebruiken echte lokale logica en SQLite; externe
Home Assistant-communicatie wordt vervangen door testtransport.

Ruff op de nieuwe Python-bestanden, Python-syntaxcontrole, JavaScript-syntaxcontrole
en git diff-controle slaagden. Geen live Home Assistant-test of browsercontrole
uitgevoerd; lokale sockettoegang is in deze omgeving geblokkeerd.
