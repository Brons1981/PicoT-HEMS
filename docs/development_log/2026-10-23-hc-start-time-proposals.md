# Voorstellen voor verschillende starttijden

HC kan nu vóór een verwarmingsvraag verschillende starttijden als één pakket
aan HEMS aanbieden. De airco beneden en de CV moeten op dat moment uit staan.
Alle varianten gebruiken hetzelfde schemadoel en dezelfde beoordelingsperiode.
Deze stap voegt advisering toe; de keuze van HEMS wordt nog niet uitgevoerd.

## Onderbouwing van iedere variant

Een kandidaat vereist meetbewijs voor vier onderdelen: afkoeling, standby,
een volledige start en handhaven. De bestaande leermodellen voor afkoeling,
volledige starts en handhaven worden hergebruikt. Zonder passend bewijs valt
de kandidaat af. Het comfortschema en ingeschakeld leren zijn verplicht.

Voor standby bewaart HC een lopende reeks van minimaal vijftien minuten met
verse vermogens- en kWh-metingen terwijl beide warmtebronnen uit staan.
Meetgaten boven negentig seconden, andere bronnen of instellingen, tellerreset
en onwaarschijnlijk hoog uitstandsvermogen boven 100 W beginnen de reeks
opnieuw. Het kWh-verschil wordt gecontroleerd tegen geïntegreerd vermogen;
meer dan 2 Wh of 30% verschil maakt de raming onbruikbaar. De raming neemt
het hoogste gemeten vermogen of gemiddelde tellervermogen, met 25% plus 2 W
marge. Dat is een empirische schatting, geen gegarandeerde bovengrens.
Deze actuele reeks wordt niet over een herstart heen voortgezet.

Tijdens wachten berekent HC een temperatuurinterval tussen de huidige
binnentemperatuur en de temperatuur na afkoeling volgens de bestaande
voorzichtige afkoelraming. De laagste temperatuur moet boven het huidige
benedendoel buiten comfort blijven; dit doel komt uit de centrale
schemaregeling, inclusief eventueel adaptief verlagen.

Over het hele temperatuurinterval wordt in stappen van maximaal 0,25 graden
passend bewijs voor volledige starts gevraagd. Elk punt vereist minimaal drie
passende trajecten. De hoogste energie en langste duur over dat interval
bepalen de opwarmfase. Er wordt geen lineaire energiebesparing per graad
verzonnen. Handhaven na opwarmen vereist opnieuw drie passende meetperioden.

## Tijdgrenzen en profiel

De eerste onderzochte start ligt minimaal twee minuten vooruit en niet vóór
de door HEMS toegestane vervangingsperiode. Daarna worden stappen van vijftien
minuten onderzocht, met maximaal vijf onderzochte opties en een uiterste
start binnen één uur. Door die uurgrens passen in de huidige uitvoering
maximaal vier starttijden in een pakket.

Iedere kandidaat moet volgens de raming uiterlijk bij de start van het
comfortvenster op het schemadoel uitkomen. Het energieprofiel omvat eventuele
standby tot de gekozen start, de volledige opwarmfase en daarna handhaven.
De gezamenlijke eindtijd ligt uiterlijk vijftien minuten na het comfortbegin,
begrensd door het comfortvenster en de HEMS-horizon. Alle tijdvakken sluiten
aan; ontbrekende standby wordt nooit stilzwijgend als nul ingevuld.

Voor de gemeenschappelijke periode vóór de beoordelingsstart blijven de
bronnen bij alle varianten uit. Die periode valt buiten de vervanging. De
bestaande HEMS-uitsplitsing voorkomt dubbeltelling binnen de beoordeelde
periode. HEMS ontvangt generieke tijdvakken en energie; apparaatinstellingen,
temperaturen en lokale bewijsvoering blijven in HC. MEP is niet gewijzigd.

## Geldigheid en weergave

De bestaande publicatie, maximale geldigheid van twee minuten en beperking
tot één nieuw verzoek per recent gebruikte HEMS-basis blijven gelden.
Herpublicatie verlengt de geldigheid niet. Voor een nog geldig pakket worden
alle oorspronkelijke starttijden opnieuw getoetst. Verhoogde ondergrenzen,
verdwenen meetonderbouwing, hogere ramingen of gewijzigde omstandigheden
kunnen het pakket intrekken. De interface toont de aangeboden starttijden en
het gemeenschappelijke doel.

## Grenzen

Deze eerste starttijdvergelijking kijkt maximaal één uur vooruit en gebruikt
de huidige buitentemperatuur. Wind, zon, bewolking en warmteopslag in het huis
worden nog niet afzonderlijk voorspeld. De opwarmenergie wordt gelijkmatig
over de geraamde duur verdeeld; het kwartierprofiel is daarmee een benadering.
Ook met marges zijn comfort en kosten geen garantie.

Een HEMS-keuze verandert nog geen apparaatcommando's of batterijroute. Er
zijn geen CV-alternatieven toegevoegd en er is geen release of live activering
uitgevoerd. De bestaande regeling blijft actief zolang uitvoering van een
gekozen voorstel nog niet is gekoppeld.

## Verificatie

De gecombineerde regressiesuite slaagde: **145 tests in 61,58 seconden**.

Gerichte tests gebruiken echte meetmodellen en SQLite en controleren onder
meer energie in alle drie fasen, gelijke tijdgrenzen, de comfortdeadline,
ontbrekend bewijs en bescherming van de ondergrens. Een ketentest laat HEMS
een pakket met vier starttijden beoordelen en leest het antwoord terug via
HC. Daarbij blijft de opgeslagen batterijroute gelijk. Een aangescherpte
ondergrens trekt het oorspronkelijke pakket in.

Een runtime-test verzamelt vijftien minuten standby vóór warmtevraag en
controleert dat daarbij geen apparaatcommando wordt gegeven. Python-lint,
Python-syntax, JavaScript-syntax en git diff-controle slaagden. Live Home
Assistant en de browserweergave zijn niet getest.
