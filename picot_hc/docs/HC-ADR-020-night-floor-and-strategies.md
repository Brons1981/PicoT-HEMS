# Nachtbasis en vergelijking van verwarmingsstrategieën

Status: basisregeling geïmplementeerd, financiële vergelijking ontworpen.
Opdracht Alex: 5 november 2026. Opgenomen in HC 0.1.0-dev.30.

## Basis die nu wordt uitgevoerd

Het bestaande schema bepaalt de tijden. Bij Alex begint om 22:00 een expliciet
17 °C-blok. Een schemadoel beneden de minimale verwarmingsstand van de airco
betekent nu een kamerondergrens. Het wordt niet als apparaatdoel doorgestuurd.
De woonkamerairco weigert 17 °C in verwarmingsmodus; de bevestigde ondergrens
voor `climate.airco_woonkamer` is 18 °C. Deze gerichte capability-correctie geldt
alleen voor Celsius en laat de algemene HA-grens intact.

- Bij een kamer boven 17 °C stopt de door HC bediende airco in dit schemablok.
- Bij een kamer van 17 °C of lager mag hij met apparaatdoel 18 °C starten.
- Stop na herstel tot 17,3 °C, met minimaal tien minuten draaitijd voor deze
  ondergrenscyclus en de bestaande herstartvertraging van drie minuten.
- Handmatige overname, uitschakelen van de regeling, bronstoringen, deurvoorwaarden
  en geldigheid van meetgegevens blijven voorrang houden. Een ontbrekende meting
  autoriseert geen start. De bestaande vijf minuten meetuitvalgratie blijft gelden
  voor reeds bevestigde verwarming; daardoor kan een stop bij meetuitval later komen.
- Een tijdelijk temperatuurdoel heeft voorrang. Een volgend comfortblok herstelt
  de normale regeling. De leerregeling en economische startrecepten vervangen het
  expliciete lage schemadoel in deze eerste versie niet; dus ook geen vervroegde
  opwarming binnen zo'n blok.
- Tijdens dit ondergrensblok is de fysiek uitgeschakelde CV geen alternatief.
  De bestaande bronkeuze tijdens comfortblokken is niet gewijzigd. Een expliciete
  beschikbaarheidsinstelling voor CV en latere inzet voor de 17 °C-grens volgen apart.

22:00 is geen nieuwe hardgecodeerde kloktijd. Bestaande expliciete lage dagblokken
hebben dezelfde ondergrenswerking. Het schema zelf wordt niet gemigreerd.
Een bestaande foutblokkering wordt niet automatisch gewist door deze wijziging.

## Meetbasis zichtbaar maken

Dashboard en diagnosedownload tonen per model het totaal bewaarde aantal,
metingen in de laatste zeven dagen, passende metingen en de beschikbaarheid van
een schatting. Er zijn aparte regels voor handhaven, handhaven op 18 °C,
opwarmen, starten vanuit uitstand en afkoelen. De 18 °C-regel toetst alleen de
meetdekking rond dat doel; dit is nog geen voorspeld temperatuurtraject.

De bestaande modellen gebruiken contextselectie en doorgaans minimaal drie
passende metingen. Veel opgeslagen woningmetingen betekenen daarom niet dat
alle strategieën berekenbaar zijn. Vooral de huidige opwarm- en startregistratie
begint bij voorverwarming; een gewone of late comfortstart levert niet vanzelf
zo'n complete leersessie op. De volgende bouwstap moet die sessies ook registreren,
met onderbrekingen, bronwissels en handmatige acties als expliciete uitsluitingen.

## Volgende bouwstappen

1. Complete leersessies: registreer normale comfortstarts naast voorverwarming,
   koude start versus warm doorbedrijf, afkoeltrajecten, buitentemperatuur,
   ingestelde en gemeten temperatuur, duur en geïntegreerde energie. Maak
   ontbrekende of afgewezen sessies uitlegbaar. Houd CV en airco gescheiden.
2. Eén vergelijkingsperiode: alle kandidaten beginnen bij dezelfde actuele
   toestand en eindigen op hetzelfde tijdstip, met hetzelfde volgende comfortdoel.
   Neem opwarmen én resterend handhaven tot dat eindpunt mee. Een kandidaat die
   comfort niet tijdig haalt is ongeschikt, niet goedkoop.
3. Maak drie trajecten: huidige comforttemperatuur handhaven; verlagen tot een
   geldige aircostand van minimaal 18 °C en later herstellen; uitschakelen met
   natuurlijke afkoeling, ondergrensbewaking en later opnieuw opwarmen. Controleer
   kamergrenzen, apparaatgrenzen, start/stopvertragingen en beschikbaarheid per stap.
   Extrapoleer geen afkoeling of COP buiten de ondersteunde meetcontext zonder
   zichtbare onzekerheid. Verwar de 17 °C-kamergrens niet met de 18 °C-apparaatstand.
4. Bereken kosten over het volledige profiel: kWh per tijdvak maal toepasselijk
   tarief; bij HEMS-afstemming de marginale impact op net, eigen opwek en batterij.
   Tel stroom niet dubbel als HEMS al het totale prijsverschil levert. Voeg CV-gas
   alleen toe voor een expliciet beschikbare CV en een afzonderlijk geldig model.
   Ontbrekende toekomstige tarieven of modellen geven een onvolledige vergelijking.
5. Publiceer eerst advies met kosten, onzekerheidsband, comfortmomenten,
   uitsluitingsredenen, gebruikte modellen en vergelijking met de vaste nachtregel.
   Bewaar de inputs, alternatieven en reden van de keuze in diagnosehistorie.
   Deze advieslaag mag geen broncommando verzenden.
6. Activeer uitvoering pas in een afzonderlijke vervolgstap: minimale aantoonbare
   besparing boven onzekerheidsmarge, stabiele keuze, bestaande HEMS-toestemming,
   verse controles en terugval naar de vaste basis bij onvoldoende bewijs.

## Acceptatie voor de vergelijking

Toets identieke start/eindvoorwaarden; kosten inclusief heropwarming;
tariefwisselingen en negatieve prijzen; onvoldoende passende meetcontext;
kouder weer; langdurige afkoeling tot de ondergrens; ontbrekende metingen;
herstart tijdens een traject; handmatige overname; onbeschikbare CV; en het
uitblijven van broncommando's vanuit advies. Vergelijk ramingen achteraf met
werkelijk gemeten energie en comfort, voordat autonome selectie wordt toegevoegd.

De huidige wijziging bevat geen volledige eurovergelijking en geen automatische
selectie tussen de drie strategieën. Ventilatoroptievertaling en de eerdere
melding/blokkering rond opdrachtbevestiging worden hier niet gewijzigd.


## Vervolgcorrectie 5 november 2026 (nog niet uitgebracht)

De eerste versie onderdrukte voorverwarmen tijdens expliciete lage blokken.
Dit is op verzoek van Alex herzien: een zacht blok met een lager doel mag binnen
het ingestelde voorverwarmvenster wijken voor het volgende hogere comfortdoel.
Een hard blok blijft leidend. Bij ontbrekende leeruitkomsten geldt de bestaande
initial_preheat_minutes (bij Alex 45 minuten); maximum en deadlinefeedback blijven
bepalend. Een lager volgend nachtelijk doel veroorzaakt geen voorverwarming.

CV-modus heat/auto is op zichzelf geen bewijs van actieve warmtevraag. Alleen bij
beschikbare, niet-pending terugmelding met hvac_action=idle en een doel minstens
0,3 °C onder de eigen gemeten kamertemperatuur mag HC concurrerende aircoverwarming
hervatten. De handmatige CV-instelling blijft onaangeraakt en die CV wordt niet als
automatische bron gekozen zolang de handmatige overname actief is. Heating,
ontbrekende actie/temperatuur of een hoger doel blijven conservatief blokkeren.
De bestaande minimum-uitduur van de airco blijft van toepassing bij hervatten.

Opwarmmetingen mogen nu ook tijdens een normale automatische comfortstart beginnen.
De energiemeter moet geldig zijn; handmatige aircoverwarming levert geen geldig
runtime-meetmonster. De grens van 0,5 °C, 90 seconden meetcontinuïteit, 120 seconden
bevestigd doel en consistentie van vermogen/teller blijven behouden. Een begonnen
maar niet voltooide sessie wordt na herstart niet gereconstrueerd. Maximaal 64
gebeurtenissen per model verklaren starten, voltooiing, wachten en afwijzing.
Diagnose bevat de afzonderlijke records en gebeurtenissen; bestaande records blijven
leesbaar. Een tevreden CV in idle sluit zuivere aircometingen niet langer uit.

De dagprognose kan de aparte volledige-startmetingen benutten. Expliciete lage
blokken krijgen uitperioden op basis van gemeten afkoeling; bij de kamergrens wordt
ondergrensverwarming met een geldige apparaatstand geraamd. Deze cyclusraming is
voorlopig: opwarmenergie wordt conservatief tot het apparaatdoel geraamd, terwijl de
kamertoestand tot de stopgrens wordt geprojecteerd. Minimale draaitijd is tien
minuten. Een ontbrekende afkoelraming wordt niet vervangen door onbeperkt gratis
uitstaan. Er worden nog steeds geen startcommando's uit de prognose verzonden.
Een bruikbare prognose ontstaat pas zodra voldoende relevante historie bestaat;
voorlopige schaling kan al een complete passende sessie benutten.
