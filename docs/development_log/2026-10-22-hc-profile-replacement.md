# HC-voorstellen beoordelen zonder historische dubbeltelling

Deze stap verbindt de gemeten uitsplitsing met de bestaande HEMS-beoordelaar.
HEMS kan nu een aangeleverd volledig verbruiksprofiel voor airco beneden
beoordelen door het bijbehorende historische aandeel te vervangen. Dit is
advisering op de behouden batterijroute; er is geen live uitvoering toegevoegd.

## Herleidbare prognosebasis

De parallelle raming uit de vorige stap is onvoldoende om automatisch iets
van de actieve huisprognose af te trekken. De nieuwe strikte variant gebruikt
dezelfde historische perioden en alle geselecteerde meetmomenten als de
werkelijke huisprognose. Ieder geselecteerd meetmoment moet een geldige
attributie aan dezelfde meter hebben. Ook een onbekende meting met toevallig
hetzelfde totale vermogen blokkeert deze bewijsvoering.

De uitkomst wordt per tijdvak vergeleken met de historische huisprognose vóór
actuele correcties. Fallback, ontbrekende attributie of afwijkende weging
leveren geen vervangingsbasis op. De bestaande prognose wordt hiervoor niet
aangepast en oude historie wordt niet herschreven. Het kan dus langer duren
voordat vervanging mogelijk is dan voordat een parallelle raming beschikbaar is.

De basis bevat intern de componenttijdlijn en een vingerafdruk van de actieve
prognose, inclusief batterij-uitgesloten verbruik. Naar HC gaan alleen een
basis-ID, ondoorzichtige bron-ID en de toegestane periode. De basis blijft in
HEMS, buiten de MEP-contracten. De bestaande worker bewaart maximaal twee
recent gepubliceerde prognoses met hun bijbehorende basis, maximaal 120 seconden.

## Actuele correcties en EV

De actuele extra-verbruikscorrectie wordt behouden. Als die actief is, mag
vervanging pas na haar vijftienminutenvenster beginnen. HEMS meldt deze
vroegste starttijd expliciet. Een voorstel dat eerder begint wordt geblokkeerd.

In het aangevraagde venster geldt:

`nieuwe huisvraag = bestaande huisvraag - bewezen airco-aandeel + voorgesteld aircoverbruik`

Buiten dat venster blijft het verbruik ongewijzigd. Tijdvakken worden waar
nodig gesplitst, ook op gedeeltelijke kwartieren. Afzonderlijk toegevoegd
EV-verbruik en de batterij-uitsluiting daarvan blijven behouden. HEMS kapt
een onmogelijke aftrek niet af tot een schijnbaar geldig profiel.

## Aanvraagcontract

De bestaande `hc-energy-proposals:v1` blijft voor extra vraag geldig.
Het nieuwe contract `hc-energy-proposals:v2` gebruikt:

- `demand_basis: replace_controlled_load` en een HEMS-`replacement_basis_id`;
- dezelfde aanvraag-ID, revisie, prognose-ID, TTL en comfortverklaring als v1;
- één tot vijf voorstellen, ieder met maximaal twaalf aansluitende tijdvakken;
- `energy_wh` als volledig verbruik van de betreffende component per tijdvak;
- `non_electric_cost_eur` als niet-elektrische kosten van dat voorstel.

Alle alternatieven moeten hetzelfde begin en einde hebben. Een gat is geen
stilzwijgende nulmeting: nulverbruik moet expliciet worden aangeleverd. Het
vermogen wordt binnen een tijdvak gelijkmatig verdeeld. De aanvraag kan niet
zelf bepalen hoeveel historische vraag wordt afgetrokken.

De bestaande fysieke en financiële beoordeling, bescherming van eindvoorraad
en behouden route blijven gelden. Niet-elektrische plankosten worden bij het
verschil in elektriciteitskosten opgeteld. Dit is een vergelijking ten opzichte
van de bestaande elektrische route, geen uitspraak over onbekend historisch
gasverbruik. Bij een onhaalbaar profiel worden kleinere profielen daadwerkelijk
doorgerekend. Ook nulverbruik moet daarbij getest worden: een nulvervanging is
niet dezelfde situatie als de ongewijzigde prognose.

Het antwoord blijft `hc-energy-assessment:v1`, met de nieuwe scope
`replacement_demand_on_retained_route` en het basis-ID. HC controleert deze
naast de bestaande aanvraagvingerafdruk. De uitkomst blijft
`execution_authorized: false`. Het dashboard toont of beoordeling zonder
dubbeltelling mogelijk is en benoemt relevante blokkades.

## Grenzen en volgende koppeling

HC genereert nog niet automatisch thermisch onderbouwde voorstellen. De
comfortverklaring en energieprofielen moeten daarvoor nog uit het leermodel
komen; hetzelfde geldt voor betrouwbare CV-kosten. Het meteraandeel is het
elektrische verbruik van de airco, inclusief eventuele andere bedrijfsmodi en
stand-by, en is op zichzelf geen model van warmteafgifte.

De batterijroute wordt nog niet heroptimaliseerd voor extra laden. Definitieve
reservering en uitvoering volgen later. Er is geen release, commit, push of
wijziging aan live apparaten gemaakt.

## Verificatie

Nieuwe tests bewijzen vervanging zonder dubbeltelling, nul extra kosten bij
een identiek profiel, afzonderlijke niet-elektrische kosten, behoud buiten het
venster, gedeeltelijke kwartieren, EV-behoud en het beschermde correctievenster.
Verder: ontbrekende attributie ondanks gelijke totalen, echte broninvoer met
historie, ongeldige basis/negatieve vraag/gaten/afwijkende vergelijkingsvensters,
een opnieuw getoetst kleiner profiel en transport naar HC inclusief de vorige
prognosebasis en verloop daarvan.

De lokale gedeeltelijke checkout gebruikt dezelfde HEMS-importbasis als de
eerdere stappen. Live HTTP en browserweergave zijn niet getest; de bekende
netwerkbeperking wordt niet omzeild.

Eindresultaat: 121 tests geslaagd in 62,79 seconden, waaronder 16 nieuwe tests
voor deze vervangingsstap. De run omvat ook de eerdere advieskoppelingen,
meterhistorie, HC-runtime, huislastprognose, actuele verbruikscorrecties en
EV-advies. Ruff op de gewijzigde HEMS-adviesmodules en nieuwe tests,
Python-syntaxcontrole, JavaScript-syntaxcontrole en diffcontrole zijn geslaagd.
