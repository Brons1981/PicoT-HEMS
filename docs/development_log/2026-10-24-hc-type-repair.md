# Typeherstel en browserverificatie HC/HEMS

24 oktober 2026. Uitvoering na Alex' opdracht "oke los op". Geen publicatie,
commit, push, versieophoging, installatie of echte apparaatbediening.

## Herstel

De 82 gemelde typefouten zijn verholpen met expliciete contracttypen voor
waarnemingen, forecastresultaten, profielen, SQLite-resultaten, JSON-grenzen en
planningsvensters. Optionele context en resultaten worden voor gebruik vernauwd.
Geen globale versoepeling van mypy en geen type-ignore-regels toegevoegd.

Reserveberekening weigert ontbrekende dagcontext of capabilitygegevens expliciet
met ValueError voordat een kandidaat of opslagmutatie ontstaat. Een regressietest
controleert beide gevallen en behoud van bestaande opdrachten en actief plan.
Zonder gecontroleerde bron-ID wordt geen gezamenlijke vervangingsforecast gemaakt;
de afzonderlijke modeled forecast blijft beschikbaar. Bestaande controles op
uitvoeringsmacht, eindreserve, dagdoelen en bronvervanging blijven gelden.

De nieuwe publieke testconfiguratie neemt zowel src als picot_hc op in pythonpath.
Daardoor kunnen de gezamenlijke tests ook via de gewone repositoryopdracht worden
verzameld. 23 geselecteerde tests zijn zonder aanvullende bronpaden verzameld.

De browserfixture is bijgewerkt voor de centrale benedeninstellingen: twee losse
zoneformulieren, geen tweede benedenformulier, aparte thermostaat/setback-invoer
en de huidige status bij uitgeschakeld schema. De controles op bewaren, herladen,
geen ongewenste dispatch en werkelijke opdrachten aan de fake HA blijven staan.

## Verse controles

- Mypy 2.4.0 met Linux-doel, strict repositoryconfiguratie: **263 bronbestanden groen**.
- De volledige mypy-bestandsselectie uit .github/workflows/ci.yml, inclusief de
  bestaande geselecteerde tests: **297 bestanden groen**, exit 0, ook na lintwerk.
- Ruff over de volledige src/picot-boom: **groen**. De 13 gevonden integratiemeldingen
  (11 lange regels en 2 importblokken) zijn hersteld. Vergelijking met dev.314 gaf
  daar nul meldingen. Regelafbrekingen zijn met AST-gelijkheid gecontroleerd;
  na importsortering slagen 13 dagovergang-/planning-inputtests opnieuw.
- Gerichte reserve/rechargecontrole: 9 tests groen, inclusief ontbrekende context.
- HC-browserproef: **geslaagd** met echte HC-server, lokale fake HA en Chrome
  Headless Shell 151 (Playwright build 1234). Instellingen, centrale thermostaat,
  handmatige opdrachten zonder randomUUID, terugmelding, herladen, automatische
  regeling, stoppen, badkamertimer en mobiele breedte zijn uitgevoerd.
- Edge bleef lokaal bij starten falen. De onafhankelijke testbrowser is uitsluitend
  onder hc-verification-temp/browsers geplaatst. Voor de ongewijzigde Linux-
  python3-opdracht is lokaal alleen het procespad naar de aanwezige Python vertaald.
- De Python-wheel wordt opnieuw gebouwd na de laatste bronwijzigingen. Dit is de
  HEMS-Pythonverpakking, niet de HC-container. Docker is hier niet geinstalleerd;
  containerbouw en Python-3.12/Linux-browser-CI blijven afzonderlijke controles.

De definitieve gecombineerde regressieresultaten volgen hieronder. Lokale tests
gebruiken Python 3.14 op Windows met expliciete tijdzonedata. Geen live woningproef
of vaststelling van uurweerondersteuning van de echte HA-weerbron.

## Definitief resultaat

Gecombineerde HC/HEMS-regressiereeks: **608 tests en 13 subtests geslaagd**,
490,99 seconden, exit 0. De selectie is dezelfde brede keten als de eerdere
607-reeks, plus de nieuwe ontbrekende-contexttest. Inclusief reservering tot
starttoestemming, reserve-only bijladen, opslag/herstart, dagovergang, bronvervanging,
CV-modelhistorie, opwarmplannen, leren en uurweer.

De afsluitende HEMS-wheelbouw slaagt eveneens, exit 0. Manifest en README-links
zijn gecontroleerd. Bronlint, uitgebreide mypyselectie en browserproef zijn groen.
Resterend voor publicatie: echte CI (Linux/Python 3.12) en HC-Dockerbuild; daarna
apart installatie en live woningverificatie. Geen release uitgevoerd.
