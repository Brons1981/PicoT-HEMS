# Volledige opstartenergie van de airco beneden

HC meet nu een start vanuit de gemelde uitstand vanaf een geldige meterstand
vóór de eigen startopdracht. Daarmee worden de wachttijd tot bevestiging en
het verbruik in die fase meegenomen. Dit is de meetbasis voor later te bouwen
voorstellen met een verschoven starttijd; zulke voorstellen worden in deze
stap nog niet aangeboden of uitgevoerd.

## Aansluiting op de regeling

Direct vóór de bestaande regelaar handelt, controleert HC of deze een
voorverwarmingsopdracht voor airco beneden wil geven. Alleen bij een gemelde
uitstand, zonder lopende opdracht, worden temperatuur, vermogen en kWh-teller
als mogelijke beginmeting bewaard. De meting stuurt zelf geen apparaat aan.

Na de regelstap moet een daadwerkelijk opgeslagen HC-opdracht aansluiten:
bron beneden, oorsprong schema, opdracht verwarmen, dezelfde doeltemperatuur,
vooraf gemelde stand uit en een verzendtijd ná de beginmeting. De beginmeting
mag op dat moment maximaal negentig seconden oud zijn. De verse-uitlezing-
en apparaatbeveiligingen in de bestaande regelaar blijven gelden.

De meetcontext behoudt de controles op verse temperatuur en meters, geldige
deurtoestand, storingen en handmatige bediening. De CV moet beschikbaar en
uitgeschakeld zijn. Het begin van een startmeting vereist een actief schema,
ingeschakeld leren en automatisch voorverwarmen. Een al verwarmende airco
krijgt geen verzonnen eerdere beginmeting.

## Afgeronde start en afbreken

Tijdens wachten op terugmelding blijft het gemeten energieverbruik meetellen.
Afronden mag pas na bevestiging van de verwarmingsopdracht en nadat de
doeltemperatuur twee minuten achtereen bereikt blijft. De opgeslagen duur
loopt vanaf de beginmeting tot dat afronden. De bevestigingsvertraging wordt
apart opgeslagen; die is niet hetzelfde als een direct gemeten compressorstart.

Een mislukte, onzekere, handmatige of vervangen opdracht telt niet mee.
Ontbrekende metingen, een gewijzigde bron of doeltemperatuur, schemawijziging,
verlies van een eerder bevestigde verwarmingsstand en de bestaande grenzen
voor meetgaten en temperatuurvariatie breken de poging af. Een herstart kan
een gedeeltelijke meting niet hervatten. De poging voor dat comfortvenster
wordt vóór verdere verwerking opgeslagen, zodat dezelfde poging niet alsnog
als een volledige start kan meetellen.

## Model en weergave

Volledige starts worden in een afzonderlijke SQLite-tabel bewaard. Bestaande
metingen van al lopende opwarming blijven behouden en worden niet achteraf
als volledige starts aangemerkt. De modellen delen de controle op energie,
de bewaargrenzen en het matchen van vergelijkbare omstandigheden.

Een raming vereist drie passende volledige starts uit de afgelopen zeven
dagen. De hoogste passende energie en langste duur krijgen de bestaande
25%-schattingsmarge. Het is geen gegarandeerde bovengrens. De interface toont
het aantal volledige starts, passende metingen en of een meting nog op
bevestiging wacht. Bij voldoende bewijs toont zij de raming inclusief deze
startfase.

Wind, zoninstraling, bewolking en warmteopslag in het gebouw zijn nog geen
modelvariabelen. Een gemelde uitstand bewijst ook niet dat de hele unit fysiek
afgekoeld is. Daarom blijft dit een empirisch model van waargenomen starts.
De HEMS-voorstellen, MEP-contracten en daadwerkelijke verwarmingsregeling zijn
niet uitgebreid met uitgestelde uitvoering. Er is geen release gemaakt of
live systeem gewijzigd.

## Verificatie

De gecombineerde HC- en HEMS-regressiesuite slaagde met **135 tests in
24,25 seconden**.

De tests controleren afzonderlijke opslag, herstel van afgerond meetbewijs,
afbreken bij herstart, ontbrekende of te late beginmeting, ongeldige opdrachten,
meetgaten, schemawijziging, ontbrekende bevestiging en verlies van verwarmen.
Een runtime-test doorloopt de echte collector, regelaar en SQLite met
vervangen HA-transport. Bij twee minuten vertraagde bevestiging wordt
655 Wh over 34 minuten gemeten, inclusief de startfase. Daarbij wordt precies
één verwarmingsopdracht gegeven en geen uitschakelopdracht.

Ruff, JavaScript-syntaxcontrole en git diff-controle slaagden. Live Home
Assistant en de browserweergave zijn niet getest.
