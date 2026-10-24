# HC releasecontroles: volledige testdekking

Lokale vervolgstap op `2026-10-24-hc-reserve-completion.md`. Geen publicatie,
commit, push, installatie of echte HA-apparaatbediening.

## Afbakening

De HC-workflow gebruikte unittest discovery. Die verzamelt in deze werkboom
209 tests, terwijl pytest 428 tests verzamelt. Functietests voor onder andere
uurweer, CV-energie en planuitwisseling werden door de HC-workflow niet uitgevoerd.
De workflow installeert nu uitsluitend voor testen pytest/pytest-subtests en
voert vanuit picot_hc `PYTHONPATH=. python -m pytest tests -q` uit. De runtime en
container krijgen hierdoor geen nieuwe afhankelijkheid. De lokale testinstructie
in README is gelijkgetrokken. Planner, regeling en opslagbeleid zijn ongewijzigd.

## Gereproduceerde regressies in de testserver

De eerste volledige pytest-run gaf 9 fouten, 419 geslaagde tests en 30 geslaagde
subtests (259,84 seconden). Alle negen betroffen de nieuwe statuspublicaties:
de oude fake HA telde POST /states/sensor.picot_hc_* mee als apparaatopdracht en
probeerde in de statuspayload een entity_id voor apparaatbediening te lezen.

De testserver kent nu een expliciete lijst van de vijf gepubliceerde HC-sensoren.
Deze berichten worden afzonderlijk geregistreerd en beantwoorden de echte
HTTP-aanvraag. Alle overige writes blijven onder de bestaande commandocontroles
vallen. Twee opname-/exporttests laten uitsluitend deze vijf statuspaden extra
toe; onverwachte services of andere writes blijven fouten. Geen blanketfilter op
POST en geen wijzigingen aan de werkelijke regeling.

De negen gereproduceerde gevallen slagen na deze wijziging: 9 passed, 70
deselected, 12,63 seconden, exit 0. De volledige herhaling volgt hieronder.

## Overige controles en grenzen

- Node-syntax van app.js, heating.js en climate-charts.js geslaagd; de bestaande
  klimaatgrafiekproef slaagt (zones, volgorde, ontbrekende metingen, eenheden, nul).
- Geisoleerde HC-import, Python-syntaxis en aanwezigheid van dashboardassets
  slagen met expliciet beschikbare tijdzonedata. De eerste geisoleerde poging
  miste Windows-tijdzonedata; de container installeert tzdata al in de Dockerfile.
- Ruff F-controle meldt twee bestaande ongebruikte lokale variabelen in
  test_control.py. Dezelfde twee meldingen zijn gereproduceerd op dev.314;
  geen nieuwe F-meldingen. Geen algemene lintopschoning uitgevoerd.
- De browserproef kon Edge niet starten in deze omgeving (proces gesloten,
  Windows-toegangsfouten), voordat dashboardasserties konden draaien. Geen
  browserbewijs afleiden uit de geslaagde Node-controles.
- Docker en mypy zijn hier niet aanwezig. Containerbouw, volledige typecontrole
  en de echte CI-run zijn niet uitgevoerd. De lokale Python-versie is 3.14;
  CI gebruikt 3.12. De oorspronkelijke unittest-run is onderbroken nadat de
  onvolledige discovery was vastgesteld en vervangen door de volledige pytest-run.
- De daadwerkelijke HA-uurweerondersteuning en woningproef blijven open zoals
  vermeld in het vorige overdrachtsdocument.

## Nog richting publicatie

De actuele gebruikershandleiding moet ook inhoudelijk worden bijgewerkt:
verschillende hoofdparagrafen beschrijven nog dev.19 (onder andere stoppen op het
doel, invloed van boven op CV-keuze en nog niet beschikbaar leren/voorverwarmen).
Deze stap wijzigt alleen de testinstructie. De nieuwe functionele werking en
beperkingen staan in de ontwikkellogs van 22-24 oktober. Er is nog geen
releaseversie toegekend of verklaring dat de release volledig gereed is.

## Definitieve herhaling

Alle 428 HC-tests en 30 subtests geslaagd in 302,46 seconden, exitcode 0.
Opdracht: vanuit picot_hc `python -B -m pytest tests -q -p no:cacheprovider
--tb=short`, met PYTHONPATH voor de lokale testafhankelijkheden en HC, expliciete
Windows-tijdzonedata en tijdelijke opslag onder hc-verification-temp.
Dit omvat de oude controle-, verwarmings-, schema-, dashboard-API- en weertests
naast alle nieuwe functietests. Het integratiemanifest bevat de workflow,
testfixtures, README en dit document; alle genoemde bestanden bestaan, er zijn
geen dubbele vermeldingen en alle opgenomen Python-bestanden zijn syntactisch geldig.

De eerdere gecombineerde HC/HEMS-run van 607 tests en 13 subtests uit de vorige
stap is historisch bewijs en is in deze stap niet opnieuw uitgevoerd. Er is geen
productiecode gewijzigd; dit resultaat betreft de volledige HC-testreeks.

Vervolg: de handleiding is inmiddels inhoudelijk bijgewerkt. Zie
2026-10-24-hc-documentation-and-types.md voor geslaagde Python-pakketbouw en
de aangetoonde 82 nieuwe typefouten tegenover een schone dev.314-basis.
