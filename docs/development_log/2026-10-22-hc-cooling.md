# HC: afkoelmetingen, voorzichtige verlaging en eerder afbouwen

Vervolg op `2026-10-22-hc-learning-start.md`, uitsluitend lokaal in de
bestaande HC-werkmap. Geen release, commit, push of live aansturing.

## Gebruikersgedrag

Het comfortschema heeft twee nieuwe, standaard uitgeschakelde opties:
`adaptive_setback_enabled` en `coast_enabled`. Beide vereisen een actief
schema, ingeschakelde automatische verwarming en `learning_enabled`.
`max_coast_minutes` is instelbaar van 0 tot 60 minuten (standaard 60).
Ontbrekende velden in bestaande instellingen worden compatibel aangevuld.

Bij adaptief verlagen begint HC maximaal 1 graad onder het volgende
comfortdoel, begrensd door `setback_temperature`. Na drie geslaagde,
volledig gemeten opwarmbeurten met passende afkoelevidentie mag de verlaging
0,5 graad groter worden. Dan wordt de opwarmtijd niet tegelijk ingekort.
Een gemist comfortminimum neemt een halve graad verlaging terug en verlengt
de opwarmtijd volgens de vorige stap. Zonder passende afkoelgegevens geldt
hoogstens de beginverlaging (of een inmiddels voorzichtiger ingeleerde waarde).
Dit is een begrensd comfortexperiment, geen bewezen energiebesparing.

Eerder afbouwen verlaagt het doel maximaal 0,5 graad. Alleen bij een flexibel
venster met voldoende marge, een lager doel daarna en passende afkoelgegevens.
Een aansluitend comfortvenster dat weer warmte vraagt verhindert afbouwen.
De voorspelde eindtemperatuur moet minstens 0,15 graad boven het toegestane
minimum blijven. Bij onvoldoende marge herstelt HC het normale doel en
probeert het afbouwen niet opnieuw binnen hetzelfde venster. Dit blokkeer-
geheugen is tijdelijk; na herstart wordt opnieuw beoordeeld op actuele data.

De airco wordt hiervoor niet uitgestuurd: de bestaande temperatuurhandhaving
blijft werken met een lager setpoint. Kan de huidige bron het berekende doel
niet instellen (bijvoorbeeld alleen hele graden), dan blijft het schemadoel
gelden. Handmatige thermostaat zonder schema, boven, badkamer en garage
krijgen geen nieuwe tijdsturing.

## Meetmodel en grenzen

- Alleen beneden; verse binnen- en buitentemperaturen, gesloten deur na
  herstelvertraging, geen handmatige overname of bekende bronstoring.
- Beide benedenbronnen moeten uit staan of in heat expliciet `hvac_action=idle`
  melden. Een onbekende activiteit in heat is onvoldoende bewijs voor afkoeling.
- Eerst 15 minuten rust; daarna niet-overlappende intervallen van 20 minuten.
  Meetgaten, duidelijke tussentijdse opwarming, bron-/sensorwissel of meer dan
  2 graden buitenverandering onderbreken het traject.
- Minimaal drie bruikbare intervallen, maximaal zeven dagen oud, met binnen
  maximaal 2 en buiten maximaal 3 graden verschil met de huidige situatie.
- Afkoeling wordt genormaliseerd op het binnen-buitenverschil. Voor voorspelling
  geldt de grootste passende coëfficiënt, maal 1,5, plus 0,1 graad per uur.
- SQLite bewaart maximaal 64 intervallen. Meettrajecten worden na herstart
  opnieuw begonnen; dashboardreads wijzigen het model niet.

Dit is een conservatieve empirische schatting, geen volledig thermisch model.
Wind, zon/bewolking, toekomstige buitentemperaturen en de warmte-inhoud van
muren/meubels worden nog niet afzonderlijk gemodelleerd. De marges garanderen
daarom geen comfort onder alle omstandigheden. Zonder expliciete idle-melding
kan een ingeschakelde airco geen nieuwe afkoelgegevens leveren; HC verzint die
activiteit niet en zet hem ook niet uit om gegevens te verzamelen.

## Verificatie

De eerste vier nieuwe tests faalden voor implementatie op het ontbrekende
instellingencontract. Daarna zijn de tests uitgebreid met een echte reeks
temperatuurmetingen door Runtime/Heating/Schedule en SQLite, met alleen het
HA-transport nagebootst. Getest: beginverlaging, centrale ondergrens, geen
schema, modelopbouw/persistentie/verval, deur, ontbrekende bronactiviteit,
kouder weer, oude buitensensor, harde comfortgrens, aansluitend venster,
herstel na te snelle afkoeling, geen herhaalde afbouwpoging, apparaatstappen,
werkelijk lager setpoint zonder off, en drie successen gevolgd door een misser.

De meerdaagse test gebruikt lokale deadlines over de wintertijdovergang en
ververst de testprijzen per dag. Zonder actuele prijsbasis werd terecht niet
bijgeleerd; de oorspronkelijke eendaagse testfixture moest daarvoor worden
uitgebreid. Er zijn geen productiecontroles versoepeld om tests te laten slagen.

Verse eindcontrole: 37 tests (12 afkoeling, 9 opwarmtijd, 12 benedencontract,
4 meetregistratie) en 31 regressietests (29 verwarming met nagebootst
HA-transport, 2 schema) geslaagd: 68 totaal. Python-AST, JavaScript-syntax
en git diff --check geslaagd.

Echte HA/HTTP- en browsercontrole blijven nodig voor release. De bestaande
omgevingsbeperkingen zijn beschreven in de eerdere ontwikkelnotities.
HC/HEMS-planuitwisseling en financiële optimalisatie zijn niet gewijzigd.
