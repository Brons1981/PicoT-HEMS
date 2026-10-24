# HC: eerste lerende opwarmtijd beneden

Lokale vervolgstap op `2026-10-22-hc-downstairs-comfort.md`. Geen release,
versieverhoging, commit, push of wijziging aan een draaiende installatie.

## Gedrag

- Comfortschema bevat opt-in `learning_enabled` (standaard uit),
  `initial_preheat_minutes` (45) en `max_preheat_minutes` (180).
  Beide tijden zijn gehele minuten tussen 15 en 180; begin <= maximum.
- Met actief schema, ingeschakelde HC en ingeschakeld leren wordt beneden
  vooraf op het doel van het volgende comfortvenster gezet. Een lopend
  comfortvenster behoudt zijn doel; andere zones veranderen niet.
- Bij een volledig waargenomen opwarmbeurt wordt de temperatuur bij aanvang
  beoordeeld: onder de comfortondergrens verhoogt de volgende voorlooptijd met
  15 minuten, begrensd door het maximum. Minstens 15 minuten onafgebroken op
  het doel geeft 5 minuten korter, met een minimum van 15 minuten.
- Onderbrekingen, te late activering, open deur/herstelvertraging, ongeldige
  sensormetingen, ontbrekende kostenbasis en handmatige overnames leveren
  geen leerresultaat. Er moet daadwerkelijk een bron in heat zijn waargenomen.
- SQLite bewaart maximaal 32 resultaten en de bijgestelde voorlooptijd.
  Een lopende proef wordt niet hervat na een herstart. Wijzigingen in de
  schema-instellingen starten een nieuwe leerreeks; oude instellingen worden
  compatibel aangevuld met de nieuwe opt-in uitgeschakeld.
- De bestaande bronkeuze, verse-meetcontrole, handmatige voorrang en
  temperatuurhandhaving blijven in de regelroute. Dashboardweergave leert
  zelf niets bij en verstuurt geen opdrachten.

## Afbakening

Dit is terugkoppeling op de begintijd, nog geen thermisch woningmodel.
De voorlooptijd geldt voor het schema als geheel, niet afzonderlijk per
bron, weekdag of weersituatie. Gebruikte bronnen worden bij het resultaat
geregistreerd. Een bron in heat bewijst geen compressoractiviteit; dit model
leidt daarom geen vermogen, rendement of COP af uit die status.

Automatisch verdiepen van de temperatuurverlaging, vroeger afbouwen,
weersafhankelijkheid, afkoelcurves en de HC/HEMS-planuitwisseling volgen in
aparte stappen. Deze versie claimt geen economisch optimum of gegarandeerd
tijdig comfort. Bestaande schema's gaan niet stilzwijgend voorverwarmen.

## Verificatie

De eerste vier nieuwe tests faalden voor de wijziging op het ontbrekende
instellingencontract. Daarna: 9 nieuwe leertests, 12 bestaande
beneden-contracttests en 4 gebouwregistratietests geslaagd (25 totaal).
Deze gebruiken echte regelcode en SQLite met een nagebootste HA-transportlaag.
De nieuwe tests dekken voorverwarmen, handhaven, te late en vroege aankomst,
persistentie, maximum, opt-in, handmatige voorrang, ontbrekende sensor,
deur/meetgat en behoud van een bestaand comfortvenster.

Aanvullend slaagden 29 bestaande verwarmingstests met nagebootst HA-transport
en 2 schematests (weekoverlap/validatie en zomertijd). Totaal 56 geslaagde
tests in deze stap. Python-syntax, JavaScript-syntax en git-diff-whitespace gecontroleerd. Echte HA/HTTP- en
browsercontrole blijven nodig voor release; de beperkingen uit de vorige
ontwikkelnotitie gelden nog. Geen apparatuur aangestuurd tijdens verificatie.
