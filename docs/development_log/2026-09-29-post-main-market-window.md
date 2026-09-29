# 29 september — marktroute na de hoofdlaadroute

Alex koos om 18:37 Europe/Amsterdam voor het beperkte venster na de hoofdlaadroute
van de eigen kalenderdag tot lokale middernacht. Om 18:46 is de eenmalige overgang
voor nog niet begonnen ochtendroutes goedgekeurd. Zie ADR-019.7.

## Contract en oorzaak

Dev.280 maakte een toekomstige dagmarktopdracht en liet ochtendexport toe omdat
laden later diezelfde dag het herstel bewees. De avond van die dag viel vóór
Evaluation af wegens ontbreken van het volgende dagherstel. Een uitgevoerd
handelsbudget sloot die avond vervolgens af. De diagnose van 29 september en
replay van beide oorspronkelijke marktbeslissingen bevestigen dit.

Candidate beperkt nieuwe toelating tot na de eigen hoofdlaadroute, of haar echte
voltooiing, tot middernacht. De volgende dagelijkse hoofdlaadopdracht moet herstel
bewijzen; een aanvullende top-up vervangt dat bewijs niet. De pipeline biedt de
huidige handelsdag aan. Economische selectie, tarieven, simulator, reserve,
100%-doelen en uitvoering blijven dezelfde autoriteiten gebruiken.

## Eenmalige overgang

Een nog niet begonnen, niet gestopte ochtendroute kan als expliciete kandidaat
worden vrijgegeven. Alleen de betrokken exportintervallen worden slim ontladen;
laadopdrachten, hun tijden en hun voltooiingsherkomst blijven behouden. De bestaande
simulator toetst reserve en laadverplichtingen. Evaluation en Builder publiceren
de vervanger; een ongeldige kandidaat of mislukte opslag publiceert niets.

De Store archiveert het oude bindingbewijs atomair bij de vervangende uitvoering.
De dagopdracht blijft pending, met maximaal het reeds resterende exportvolume.
Ingekort volume komt niet terug. Oude plannen/revisies blijven leesbaar. Een
expliciete herstelbare plankoppeling voorkomt dat een plan zonder handelssegment
na herstart eigenaarloos wordt. Nieuwe toelating gebruikt dezelfde opdracht en
het opgeslagen volumeplafond; gewone revisies blijven alleen behouden/inkorten/
verwijderen. Begonnen of afgesloten handel wordt niet heropend.

De overgang geeft geen recht om aanvullende laadopdrachten, andere handel of
historie te wijzigen. De Store kiest geen exportmoment. Uitvoering en apparaat-
adapter krijgen geen nieuwe economische bevoegdheid.

## Verificatie

Gerichte regressies omvatten ontbrekende herstelprijzen ondanks dure ochtend,
canonieke vrijgave, behoud van dagdoelen/budget, herstart, begonnen/gestopte route,
opslagfout en controle van gewijzigd archiefbudget. Bestaande winterfixtures zijn
omgezet van ochtendexport met herstel dezelfde dag naar handel na het dagdoel met
herstel morgen; controles op gecombineerd laden, uitvoering en opslag blijven.

De echte diagnose-replay gebruikt een afzonderlijke lokale Store en geen apparaat-
of netwerkacties. Vrijgave gevolgd door herstart levert een behouden laadplan en
een wachtende woensdagopdracht, zonder nieuwe ochtendroute. De bron-ZIP en ruwe
huishoudelijke gegevens blijven buiten de repository.

Volledige verificatie wordt hieronder afgesloten. Geen versieverhoging, commit,
push, release of livewijziging uitgevoerd. Dev.280 blijft de directe codebasis;
de afgesproken operationele terugvalbasis dev.268 blijft ongewijzigd.

## Verificatie-uitkomsten

- De ochtendregressie faalt op de ongewijzigde dev.280-bronnen: de verwachte
  weigering ontbreekt. De gerepareerde versie laat deze test slagen.
- Brede suite: 1.886 geslaagd, één overgeslagen, één fout in 418,98 seconden.
  De fout betrof de eerste overgangsversie: laden van overgangsmetadata stond
  buiten de bestaande foutafhandeling voor een corrupt Store-bestand. Dit is
  hersteld; daarna slagen alle 22 gerichte opslagherstel-/overgangscontroles,
  inclusief een aanvullende proef die verhoging van het vrijgegeven budget weigert.
- Eerdere gerichte markt-, uitvoerings- en herstelcontroles: 26 geslaagd;
  aanvullende bestaande Store-/revisie-/herberekeningscontroles: 55 geslaagd.
- Ruff op `src/picot`, v2-tests en alle gewijzigde/nieuwe tests: geslaagd.
  Mypy zonder incrementele cache: alle 236 bronbestanden geslaagd. Een eerdere
  cachefout in mypy is hiermee geïsoleerd; geen dependencies gewijzigd.
- Laatste diagnose-replay: oorspronkelijke dagdoelen en handelsidentiteiten
  ongewijzigd; exact het resterende exportbudget behouden. Na herstart nul
  nieuwe kandidaten en bytegelijk Store-behoud. Bronhash ongewijzigd.

De afsluitende gerichte suite op de definitieve bronversie volgt hieronder;
de volledige brede suite is niet als volledig groen na de correctie voorgesteld.
CI en release zijn nog niet uitgevoerd.

Afsluitende gerichte suite op de definitieve bronversie: **42 geslaagd** in
80,44 seconden, inclusief alle nieuwe overgangsgevallen en de herstelde
corruptieafhandeling. Diffcontrole geslaagd. Lokale uitvoering afgerond;
publicatie blijft een afzonderlijke opdracht.

## Releaseopdracht

Alex heeft op 29 september om 19:14 en opnieuw om 19:35 Europe/Amsterdam
expliciet publicatie gevraagd. Release dev.281 bevat uitsluitend deze afgeronde
reparatie, regressietests en bijbehorende documentatie. Publicatie verloopt via
een PR met alle drie CI-workflows geslaagd vóór samenvoegen. Installatie en
livecontrole volgen afzonderlijk; de private diagnose en replay blijven lokaal.
