# HC: CV-start beneden en overdracht van boven

## Doel en oorzaak

Een HC-eigen airco boven mag een haalbaar gekozen CV-plan voor beneden niet
laten vervallen. De oude CV-kandidatenfilter wees iedere bovenownership af.
Daarnaast kon EnergyStart bij gekozen CV ook boven in desired houden, waardoor
de bestaande conflictbeveiliging de CV-start terecht blokkeerde.
Een tweede oorzaak zat in herbeoordeling van het hele voorstel: een onhaalbaar
geworden niet-gekozen vroeg CV-alternatief trok ook de gekozen latere optie in.

## Wijziging

- CV-opties toetsen overdracht per starttijd: bekende begintijd, minimaal 300 s
  looptijd en max(60, 2 * poll_seconds) marge voor uitschakelbevestiging.
- Een vast gekozen plan behoudt zijn overdrachtsgrens tijdens planvernieuwing.
- Met actuele toestemming voorkomt HC een nieuwe korte bovenrun en stuurt de
  bestaande HC-eigen bron op tijd uit via de bestaande guard/feedbackroute.
- CV-start vereist boven daadwerkelijk off, geen pending opdracht en vrijgegeven
  ownership. Handmatige overname, faults, 180 s rust en het startvenster van 30 s
  worden niet omzeild. Geen automatische herhaling van onzekere stopopdrachten.
- Een gewijzigde batch kan eenmalig op dezelfde basis worden beperkt tot het
  nog haalbare gekozen CV-tijdstip. Dit is een nieuwe aanvraag met nieuwe HEMS-
  beoordeling/toestemming, geen hergebruik van een oude startvergunning.
- Een volledig geldig voorstel blijft ongewijzigd, ook in zijn laatste minuut.
  De oorspronkelijke toekomstige profielgrens blijft bij dezelfde-basis-
  beperking behouden zodat de volgende poll het standbydeel niet afkeurt.

## Verificatie

De nieuwe regressies faalden vooraf op echte controlleropdrachten of het
ontbreken van CV-kandidaten. Gerichte tests dekken boven starten ruim vooraf,
minimale looptijd, veilige overdracht, late bovenstart voorkomen, pending/timeout,
handmatige overname, ontbrekende toestemming, dezelfde-basisvernieuwing,
ongewijzigde herhaling, oude toestemming weigeren en de laatste geldigheidsminuut.
De volledige runtimeproef gebruikt fake HA met teruggelezen publicaties en een
nagebootste actuele HEMS-vooruitblik, inclusief voldoende CV-idlehistorie.
Definitieve suite- en Linux-CI-resultaten worden in PR #725 vastgelegd.

Geen wijzigingen aan HEMS/MEP-broncode, nachtelijke herstelregels, versienummers,
installatie of live regeling. PR blijft concept tot vrijgave.
