# Meetbasis voor een later CV-alternatief

HC verzamelt nu passief CV-opwarmmetingen tijdens een gewone, door HC gestarte voorverwarming beneden. De bestaande eenvoudige bronkeuze op basis van COP, gasprijs en ketelrendement blijft bestaan. Er worden in deze stap nog geen CV-kandidaten naar HEMS gestuurd: gemeten CV-opwarmprofielen en een verantwoorde toerekening van gas en elektriciteit ontbraken.

## Meting

De registratie neemt vlak vóór een bestaande CV-startopdracht een nulmeting van de temperatuur beneden, buitentemperatuur en huishoudelijke gasmeter. Ze volgt daarna uitsluitend de bijbehorende HC-opdracht van uit naar verwarmen, inclusief bevestiging door de bestaande controller. De CV moet het geselecteerde doel blijven volgen. De airco beneden moet uitstaan; zijn aparte elektriciteitsmeter wordt nergens als CV-meter gebruikt.

Het doel moet minstens twee minuten achtereen zijn bereikt. De geregistreerde opwarmduur loopt van de nulmeting tot het begin van die stabiele periode. Vervolgens wordt op een gasmeterbericht van na de stabilisatieperiode gewacht. Zo wordt een nog niet bijgewerkte gasstand niet als nulverbruik geïnterpreteerd. Gasberichten mogen bij uitlezen maximaal tien minuten oud zijn. De afzonderlijke begin- en eindtijd van de gasberichten worden opgeslagen, omdat deze niet noodzakelijk samenvallen met de temperatuurmeting.

Er wordt alleen gemeten bij een actief comfortschema met leren en automatische verwarming. Een onderbreking langer dan 90 seconden, tellerreset, teruglopende gasbrontijd, gewijzigd meetpunt, schemawijziging, handmatige overname, verlies van bevestiging, te sterke temperatuurdaling of meer dan 1,5 graad verandering buiten breekt de reeks af. Een poging duurt maximaal drie uur. Een afgebroken of bij herstart onderbroken opdracht wordt niet als nieuwe volledige opwarming hervat. Een voltooide meting vereist minimaal vijf minuten opwarmtijd en een positieve gasmeterverandering.

De meetpoging wordt bij de eerste waarneming na opdrachtverzending vastgelegd. Afgeronde waarnemingen worden bewaard in `hc_cv_warmup` in de bestaande HC-database, maximaal 96 metingen. De status toont alleen waarnemingen van de laatste dertig dagen. Een fout in deze passieve registratie wordt apart opgevangen en verandert geen verwarmingsopdracht.

## Interpretatie en grenzen

`household_gas_delta_m3` is de verandering van de huishoudelijke gasmeter in het gemelde interval. Deze kan ander gasverbruik bevatten, zoals warm water. De registratie noemt dit daarom niet zuiver CV-verbruik en rekent het niet om naar een vergelijkbaar warmte- of elektriciteitsprofiel. Elektrisch hulpverbruik van de CV is onbekend, niet nul.

Elke waarneming en de openbare status blijven `comparison_eligible=false`; de status blijft ook `execution_authorized=false`. Alleen de temperatuur beneden bepaalt of het doel bereikt is. Temperaturen boven en in de garage vormen geen stuurvoorwaarde. Hun eventuele mee-verwarming door de CV blijft onderdeel van het feitelijke huishoudelijke gasverbruik.

`/api/snapshot` bevat de meetstatus en laatste waarneming onder `cv_warmup`. Bij de bestaande opwarmgegevens toont het dashboard het aantal metingen, een lopende meetreeks en de ontbrekende onderbouwing voor een automatisch CV-alternatief. Een achtergebleven uitlegtekst over het nooit uitstellen van de gewone voorverwarmstart is daar tegelijk in overeenstemming gebracht met de vorige ontwikkelstap.

HEMS- en MEP-code zijn in deze stap niet gewijzigd. Voor vergelijkbare CV-plannen blijven gasafbakening, elektrisch hulpverbruik en voldoende passende meetreeksen nodig. Er worden geen besparingen of comfortequivalentie verondersteld.

## Verificatie

De nieuwe tests ontbraken eerst aan de CV-meetmodule. Daarna slagen ze voor een volledige opwarming met vijfminutelijkse gasberichten, opslag en herstart, geen dubbele registratie van dezelfde opdracht, afgebroken reeksen, ontbrekende of verouderde gasgegevens, verkeerde eenheid, toekomstige brontijd en gelijktijdige aircoverwarming beneden. De runtime-integratietest gebruikt echte HC-regeling en opslag met nagebootst HA-transport: één CV-start, één complete meetreeks, geen airco-startenergiemeting en geen extra opdracht bij een fout in de CV-meetregistratie.

De gerichte reeks telt 17 geslaagde tests. Ruff, F-controle op de HC-runtime en `node --check` op app.js slagen. Echte apparaten, gasmeterlatentie en browserweergave zijn niet live getest. Geen instellingen geactiveerd, commit gemaakt, release gebouwd of publicatie uitgevoerd.

Laatste volledige verificatie: **244 tests en 13 subtests geslaagd in 130,15 seconden**. Dit omvat `hc-comfort-work/tests`, de bestaande HC-reeksen voor energievoorstellen, outlook, opwarmenergie, opwarmplannen, volledige starts, uitgestelde starts, leren, startvoornemens en startuitvoering, plus de nieuwe CV-meetreeks. Uitgevoerd met Python 3.14 en pytest zonder cacheprovider, met de lokale gewijzigde HEMS-modules vóór de referentiemodules op het importpad. `git diff --check` slaagt eveneens.
