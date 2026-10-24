# Benedenmeter en gekoppelde verbruikshistorie

Alex heeft bevestigd dat sensor.kwh_meter_airco_energie_import uitsluitend
de airco beneden meet. De bijbehorende vermogenssensor is
sensor.kwh_meter_airco_vermogen. Deze stap bouwt de meetbasis voor de
verbruiksraming; automatische thermische voorstellen en correctie van de
actieve huisprognose zijn nog niet aangesloten.

## Ingebouwde gegevensstroom

HC registreert de actuele benedenmeting in zijn bestaande SQLite-samples en
publiceert sensor.picot_hc_load_measurement. Dit werkt ook als de automatische
verwarming uit staat. Publicatie gebeurt in maximaal een achtergrondworker,
zonder opdrachten aan klimaatapparaten. Uitval wordt onbekende informatie
door de controle op meettijd, nooit een nulmeting.

De bevestigde combinatie van vermogens- en energiemeter is expliciet begrensd.
Een gewijzigde meterconfiguratie wordt niet automatisch als dezelfde fysieke
belasting beschouwd. Een bronhash omvat beide meters en de gekoppelde airco.
HEMS ontvangt alleen die ondoorzichtige bronidentiteit, vermogen en tijdstippen.

HEMS leest dit als een optionele bron. De fysieke totale huislast wordt
ongewijzigd opgeslagen, met daarnaast controlled_power_w en
controlled_source_id. De bestaande JSONL-historie blijft schema 1 en is
achterwaarts leesbaar. Oude records zonder attributie blijven onbekend;
ongeldige optionele attributie laat de fysieke totaalmeting intact.

Een meting telt alleen mee als het vermogen eindig en niet-negatief is,
de eenheid W klopt, de meet- en publicatietijden geldig zijn en de vijf
metingen voor de huisbalans voldoende recent zijn. De maximale afwijking
tussen meetmomenten is 30 seconden. Een aircovermogen groter dan de huislast
na bekende EV-aftrek wordt afgewezen, niet passend gemaakt door afkappen.

## Afzonderlijke prognose

Een parallel model berekent totaal, restverbruik en gecontroleerde belasting
uit exact dezelfde gekoppelde meetmomenten. De bestaande regels voor
klokkwartieren blijven gelden: minstens twee historische perioden met minimaal
twee samples die minstens een half kwartier beslaan, maximaal zeven perioden
uit veertien dagen, met meer gewicht voor recentere perioden. De implementatie
indexeert de historie eenmaal per kwartier, zodat niet drie keer per toekomstig
kwartier de volledige historie doorlopen wordt.

Dit model is nog niet gelijk aan de actieve huisprognose: die kan andere
historische samples, fallback en actuele lastcorrecties gebruiken. Daarom wordt
de afzonderlijke raming nog niet van die prognose afgetrokken. De bestaande
HC-aanvraaggrondslag additional_to_forecast blijft onveranderd; volledige
verwarmingsplannen mogen daar nog niet als extra vraag worden ingestuurd.

HEMS meldt via de energierichtlijn of gekoppelde metingen ontbreken, historie
wordt verzameld of het parallelle historische model voldoende dekking heeft.
HC toont dit bij het comfortschema. De melding kent geen energiebudget toe.
MEP en apparaatuitvoering ontvangen geen nieuwe apparatenkennis of opdrachten.

## Nog te verbinden

Voor echte planselectie moet de historische component herleidbaar worden
vervangen binnen dezelfde prognosebasis, inclusief de actuele lastcorrectie.
HC moet daarnaast warmtebehoefte en verbruik per voorgestelde temperatuurroute
ramen. Het hele gasverbruik mag daarbij niet als uitsluitend benedenverwarming
worden behandeld. Er is geen automatische planpublicatie of uitvoering toegevoegd.

## Verificatie

Nieuwe controles dekken de keten HC-meter naar HEMS-attributie naar opslag,
onbekend tegenover echte nul, oude en corrupte attributie, meettijdverschil,
onmogelijke vermogensbalans, EV-aftrek, gedeeltelijke kwartieren, oorspronkelijke
historische weging, behoud van energie en behoud van de actieve huisprognose.
Collector- en publicatiecontroles dekken meten met HC uit, geen klimaatacties,
maximaal een worker, transportuitval en de melding terug naar HC.

De verificatie gebruikt de lokale gedeeltelijke checkout met de bestaande
HEMS-bronboom als importbasis. Live HA-transport en een browsercontrole zijn
niet uitgevoerd. Er is geen release, commit, push of live wijziging gemaakt.

Eindresultaat: 186 tests geslaagd in 159,92 seconden. Dit omvat de nieuwe
meetketen, de eerdere HC/HEMS-advieskoppeling, leren/afkoelen, opslag en
huislastprognose, broninvoer en de EV-adviesregressies. De eerste brede run is
afgebroken toen de bestaande HTTP-tests netwerkfouten gaven; een afzonderlijke
controle bevestigde WinError 10013 bij localhost. Die HTTP-tests zijn niet als
geslaagd aangemerkt en zijn uit de daaropvolgende netwerkloze run gelaten.
Ruff op de nieuwe HEMS-module/tests en gewijzigde publicatieworker, F-controles
op de overige nieuwe Python-wijzigingen, Python-syntax en JavaScript-syntax
zijn geslaagd. Diffcontrole vond geen whitespacefouten.
