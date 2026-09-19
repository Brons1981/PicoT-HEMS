# Eerste beperkte NUC-proef voor passieve historie

Status: voorbereid en lokaal uitgevoerd. Niet op Alex' NUC uitgevoerd. Geen
release, plannerwijziging, installatieopdracht of live-aansluiting. De testhelper
staat in `tools/passive_history_probe.py`; de bestaande productiecode is voor
deze voorbereiding niet gewijzigd.

## Doel en grens

Een eerste indicatie krijgen van CPU, procesgeheugen, schijfgebruik en scheduling
bij de werkelijke EvidenceRecorder en indexworker. Het is een zelfstandige
synthetische proef. Zij raakt geen HA-entiteiten of bestaande PicoT-opslag.
De controletik is geen plannercyclus. Het programma bewijst daarom geen maximale
vertraging van de draaiende planner en beslist niet zelfstandig over vrijgave.

Vier JSON-records van ongeveer 256 KiB worden vooraf opgebouwd, met willekeurige
hex-inhoud en verschillende recordnummers. Eén record per seconde wordt aangeboden.
Dat voorkomt dat deduplicatie alle schrijfwerk wegneemt. Er zijn drie opeenvolgende
kindprocessen:

1. Vier seconden een controletik van 50 ms zonder opname, met dezelfde vooraf
   opgebouwde records in het geheugen.
2. Dezelfde tik met de echte opnamethread in hetzelfde proefproces. Meting van
   aanbiedduur en te late ticks, plus afwijzingen en publicatie-uitkomsten.
3. Ontdekking van de vier eigen bestanden en verwerking van één batch van vier.
   De proef doorloopt eenmalig alle 256 digest-prefixen om de testbestanden te
   vinden. Dit is extra proefwerk; de normale worker doet één prefixstap.

## Begrenzing

- Expliciete bestaande proefdirectory als bovenliggende directory. De helper maakt
  daar zelf een unieke tijdelijke subdirectory; alleen die wordt opgeruimd.
- Vooraf minimaal 512 MiB vrije ruimte. Dit is een momentopname, geen reservering.
- 8 MiB budget voor bewijsobjecten en afzonderlijk 8 MiB voor SQLite, plus de
  bestaande 128 MiB vrije-ruimtereserve bij opname/verwerking. Dit is geen totale
  bestandssysteemquota; journal- en tijdelijke bestanden tellen afzonderlijk mee.
- Ieder kindproces: maximaal 128 MiB virtuele adresruimte. CPU-grens vijf seconden
  voor baseline/opname en twee seconden voor indexverwerking.
- Per kindproces vijftien seconden timeout; de ouder beëindigt uitsluitend zijn
  eigen kindproces. Een geblokkeerde kernel-I/O is daarmee geen gegarandeerde
  harde tijdgrens. Gewone fouten leveren een rapport en een niet-nul exitcode.
- Geen permanente dienst, scheduler, netwerkverkeer of automatische herstart.

## Uitvoering later op de NUC

Gebruik een afzonderlijke checkout met deze wijzigingen en Python 3.12 of nieuwer
in een afgesproken proefomgeving. De helper gebruikt alleen de standaardbibliotheek
en PicoT-broncode. Hij is nog niet beschikbaar in de draaiende dev.263-installatie.
Installeer hiervoor geen ontwikkelpakketten in de actieve add-on en wijzig geen
HA-beveiligingsinstellingen. Eerst moet vaststaan welke afzonderlijke Linux-omgeving
op de NUC beschikbaar is; containerlimieten kunnen de meting beïnvloeden.

Vanuit de root van die afzonderlijke checkout:

```sh
PYTHONPATH=src python tools/passive_history_probe.py --scratch-parent /PAD/NAAR/PROEFDIRECTORY
```

Het JSON-rapport verschijnt op stdout; indien gewenst kan de uitvoerder dit naar
een nieuw rapportbestand omleiden. Geef nooit de actieve PicoT-directory als
proefdirectory op. De interne `--phase`/`--probe-root`-opties zijn uitsluitend voor
de door de helper gestarte kindprocessen.

Leg naast het JSON-rapport vast: datum/tijd, NUC-model, RAM, gebruikte schijf/mount,
HA OS/Core/Supervisor-versies indien van toepassing, containerlimieten en of PicoT
of andere zware taken gelijktijdig actief waren. Een releasepagina bewijst niet
welke HA-versie daadwerkelijk is geïnstalleerd. Het programma registreert Python,
kernel, architectuur en hashes van de drie gebruikte historiebronbestanden.

## Beoordeling en stopregels

`workload_complete=true` betekent alleen: vier records gepubliceerd en verwerkt,
geen pending werk over, en SQLite-integriteit in orde. Het is geen oordeel over
acceptabele live-latentie. Bij afwijzingen, fouten, niet-afgeronde opname of een
proceslimiet: stoppen en het rapport beoordelen; niet automatisch opnieuw proberen
of limieten verhogen.

Vergelijk p95 en maximale tikvertraging tussen baseline en opname, maximale
`offer`-duur, CPU-seconden, piek-RSS per proces en tijdelijke bestandsbytes. RSS is
een Linux-procespiek, geen nauwkeurige incrementele geheugenmeting van PicoT.
Er wordt geen nieuwe numerieke acceptatietolerantie voor de planner geïntroduceerd.
Bij zichtbare verslechtering van de draaiende installatie: proef afbreken en geen
volgende belastingstap. De bestaande PicoT-werking blijft leidend.

Deze eerste korte proef mist grotere echte snapshots, langdurige inventarisgroei,
werkelijke plannercycli, gelijktijdige recorder/indexbelasting en andere NUC-taken.
Pas na beoordeling bepalen we of een volgende, afzonderlijk begrensde proef nodig
is. Automatisch verwijderen en actieve opname blijven uitgeschakeld.

## Lokale controle bij voorbereiding

De eerste lokale uitvoering op Linux/x86_64 met Python 3.12.14 verwerkte alle vier
records, zonder afwijzingen of pending werk; integriteit `ok`. Tijdelijke bestanden
samen 775.497 bytes. Baseline-p95 tikvertraging circa 0,125 ms; opname-p95 circa
0,136 ms; maximale aanbiedduur circa 0,018 ms. Dit zijn eenmalige metingen in de
ontwikkelomgeving, geen NUC-resultaten, capaciteitsraming of grenswaarden.

De eindcontrole na toevoegen van `workload_complete` slaagt eveneens: vier records
verwerkt, geen achterstand, `workload_complete=true`. In die uitvoering bedroeg
p95 baseline/opname circa 0,120/0,162 ms; maximale tikvertraging 0,394/1,095 ms.
Die variatie onderstreept dat één korte proef geen prestatiegarantie geeft.
Ruff en mypy (`MYPYPATH=src`, `--follow-imports=silent`) slagen; `git diff --check`
slaagt. Geen wijzigingen aan productiecode of bestaande tests in deze stap.

## Afzonderlijke Home Assistant-testapp voorbereid

Alex bevestigde Terminal & SSH. De screenshot toont HA OS 18.3, Core 2026.9.3,
x86_64, Git 2.54.0 en circa 202 GB vrij op `/share`. De gecorrigeerde Python-opdracht
geeft volgens Alex `command not found`. Er zijn geen pakketten in de terminal
geïnstalleerd. Alex heeft de voorbereiding van een afzonderlijke testapp goedgekeurd.

`picot_history_probe/` bevat nu config, Dockerfile, instructies, proefprogramma en
uitsluitend de benodigde passieve modules/schema. `startup: once`,
`boot: manual_only`, geen HA-/Supervisor-/Docker-API, hostnetwerk, rechtenuitbreiding,
poorten of gedeelde map. Alleen eigen `/data`; AppArmor blijft aan. Dit volgt de
[officiële appconfiguratie](https://developers.home-assistant.io/docs/apps/configuration/).

De Dockerfile gebruikt een expliciete Python 3.12/Alpine 3.20-basistag en kopieert
het lokale pakket; geen git-clone tijdens de bouw. Een bronmanifest en test bewaken
bytegelijkheid met de beoordeelde canonieke bronnen. Dit voorkomt dat publicatie
van alleen de testapp een release of wijziging aan dev.263 nodig maakt.

Acceptatie van deze voorbereidingsstap: geïsoleerde configuratie, overeenkomende
bronbestanden, en uitvoering vanuit uitsluitend het meegeleverde runtimepakket
met vier verwerkte records en behoud van een vreemd bestand naast de tijdelijke
proefdirectory. Docker/Podman ontbreken hier: imagebouw, imagebeschikbaarheid en
Supervisor-start/stopgedrag zijn niet uitgevoerd. Geen publicatie, installatie of
NUC-test. De imagebouw zelf veroorzaakt NUC-belasting buiten de gemeten proef.

Verse pakketcontrole: **3 tests geslaagd in 8,16 s** (`test_history_probe_app.py`),
inclusief de volledige proef vanuit uitsluitend de meegeleverde runtime. Ruff
slaagt voor pakket en tests; mypy slaagt voor de meegeleverde runner met de eigen
runtime als zoekpad. `git diff --check` slaagt. Docker-buildcontext sluit Python-
cachebestanden uit. De bestaande productiecode bleef in deze stap ongemoeid.

## Publicatie van uitsluitend de testapp

Met Alex' expliciete akkoord gepubliceerd via PR #659:
https://github.com/Brons1981/PicoT-HEMS/pull/659

Samengevoegd op main als `27ec942abd3b7955eaa69ac43096f1fe2c5c2a50`.
De remote vergelijking tegen dev.263 toont exact 18 nieuwe bestanden: alleen
`picot_history_probe/` plus `.github/workflows/history-probe.yml`. Nul bestaande
bestanden gewijzigd. Remote HEMS-config blijft `2.0.0-dev.263`; testapp is `0.1.0`,
`startup: once`, `boot: manual_only`. Alle overige lokale historiewijzigingen en
lokale overdrachtupdates zijn niet gepubliceerd.

Verse GitHub-verificatie: containerbouw en proef met uitgeschakeld netwerk,
read-only rootfilesystem, geen capabilities en begrensde resources geslaagd;
vier records verwerkt en `workload_complete=true`. De eerste CI-containerproef
faalde op eigenaarschap van de tijdelijke bindmount. Opgelost door uitsluitend in
CI als eigenaar van die testmap te draaien; geen toegangsrechten versoepeld.
V2-checks: 686 tests geslaagd. Volledige PR-suite: 1.618 tests geslaagd in 290,65 s.
Ook de afzonderlijke push-checks zijn geslaagd voordat de repositoryregel de merge
toestond. Geen bypass of wijziging aan repositorybeveiliging.

De app is nu via de bestaande GitHub-repository beschikbaar na verversen van de
Home Assistant-appwinkel. Nog niet op Alex' NUC geïnstalleerd of uitgevoerd.
Volgende handeling voor Alex: alleen PicoT History Probe installeren, handmatig
één keer starten, wachten op stoppen en het JSON-log delen. HEMS hoeft niet te
worden bijgewerkt of herstart.

## Eerste echte NUC-uitvoering — log ontvangen 19 september

Alex leverde `87e174c3_picot_history_probe_2026-09-19T20-39-18.188Z.log` aan.
SHA-256 van dit log:
`571dd7ad118a3fd79e1d122e4d40122d65f12d5e98ceeacb42664c720d2ea4d1`.
De drie gerapporteerde bronhashes komen exact overeen met het gepubliceerde
proefmanifest. Omgeving: Python 3.12.12, kernel 6.18.52-haos, x86_64.

Uitkomst: `workload_complete=true`, vier aanbiedingen geaccepteerd en gepubliceerd,
vier jobs verwerkt, geen pending werk, opname netjes gesloten, integriteit `ok`.
De p95/maximale controletikvertraging was zonder opname 0,279/0,309 ms en tijdens
opname 0,271/0,285 ms. In deze korte steekproef is geen toename zichtbaar; de iets
lagere cijfers bewijzen geen verbetering. Maximale aanbiedduur: 0,060 ms.
Opnamefase: 3,954 s wandtijd, 0,098 s CPU en 20,23 MiB piek-RSS voor dat proces.
Indexfase: 1,023 s wandtijd, 0,194 s CPU en 20,14 MiB piek-RSS voor dat proces.
Tijdelijke bestanden samen 775.813 bytes (0,740 MiB). Dit is geen totale NUC- of
alle-proces-geheugenmeting.

Beoordeling: eerste beperkte synthetische NUC-proef geslaagd. Nog geen bewijs voor
grote echte plansnapshots, langdurige inventarisgroei, gelijktijdige opname/index
of werkelijke plannercycluslatentie. De actieve planner is niet aangesloten.
Volgende voorgestelde stap: eerst een begrensde proef met representatievere
recordgroottes en gelijktijdige opname/verwerking ontwerpen; geen automatische
verhoging van limieten, vrijgave of live-aansluiting uit dit resultaat afleiden.

## Tweede proef — grotere records en gelijktijdig indexwerk

Met Alex' akkoord na de eerste NUC-uitkomst is de tweede proef uitgewerkt in
`tools/passive_history_large_probe.py`, meegeleverd als `large_probe.py` in testapp
0.2.0. De diagnose bevat een huidige incidentregel van 1.219.256 bytes en een
maximale oudere aanwezige regel van 7.964.333 bytes. Dat motiveert synthetische
records van ongeveer 1, 2, 4 en 8 MiB; dit bewijst niets over grotere ontbrekende
snapshots of identieke object-/compressiestructuren.

Twee meetfasen van circa acht seconden: baseline en opname met een onafhankelijke
indexworker. De indexworker doet maximaal vier rondes, elk één volledige begrensde
inventaris van 256 prefixen en maximaal vier jobs. Hij houdt voor die gehele fase
het bestaande 128-MiB-adresruimtebudget en twee CPU-seconden. Meetprocessen krijgen
ieder 128 MiB en vijf CPU-seconden. Bij fase-timeout wordt uitsluitend de eigen
procesgroep beëindigd; een lokale subprocess-proef bevestigt ook opruiming van een
nakomeling wanneer zijn faseleider al beëindigd is.

Werkelijke publicatietijdvakken en indexrondes worden op dezelfde monotone klok
geregistreerd. Alleen hun doorsnede geeft `overlap_observed=true`. Een eerste run
verwerkte alle records maar had geen echte overlap en gaf terecht een niet-nul
exitcode. De indexplanning is vervolgens 75 ms verschoven om het 50-ms-pollen van
de recorder mee te nemen. Geen retry of gefingeerde overlap. Indexperioden omvatten
ook ontdekking en I/O; de uitkomst is geen bewijs van gelijktijdige CPU-instructies.

Lokale run daarna: 4/4 gepubliceerd en verwerkt, integriteit ok, circa 0,081 s
werkelijke overlap; p95 controletik circa 0,144/0,196 ms voor baseline/opname,
maxima circa 0,293/5,118 ms. Maximaal aanbod circa 0,040 ms. Circa 44,6 MiB proces-
piek-RSS en 8,57 MiB tijdelijke bestanden. Dit is ontwikkelbewijs, geen nieuwe
NUC-uitkomst en geen numerieke plannergoedkeuring.

Voor dit afzonderlijke grotere proefprofiel is het bewijsbudget 64 MiB en de
SQLite-grens 8 MiB. Geen productie-instelling gewijzigd. Volledige testapp blijft
handmatig/eenmalig met uitsluitend eigen data en zonder API-/hosttoegang.
Vier zelfstandige pakkettests slagen, inclusief kleine en grote proef. Ruff/mypy
slagen. Publicatievoorbereiding verloopt via PR #660; uitsluitend testapp en eigen
CI-workflow, geen wijziging van canonieke historiecode, MEP of HEMS dev.263.

Containercontrole PR #660 is geslaagd met één CPU als containerlimiet: 4/4 verwerkt,
integriteit ok en circa 0,390 s gemeten overlap. De maximale controletikvertraging
was circa 20,822 ms tegenover 0,233 ms in de baseline (p95 circa 0,137 tegenover
0,135 ms). Dit is een concrete uitschieter die niet door de functionele groene
uitkomst wordt weggepoetst; geen bewijs van onmerkbare plannerbelasting.
Nog geen tweede NUC-meting. De productieregels en budgetten zijn niet aangepast.

Publicatie 0.2.0 afgerond via PR #660:
https://github.com/Brons1981/PicoT-HEMS/pull/660
Merge: `a1f00bfe9111b6b0e05b2a349352f723751a1e91`.
Vier pakkettests en containerproef groen; core/v2-controles en volledige PR-/push-
tests groen vóór merge. PR-suite: 1.618 tests geslaagd in 224,59 s. Alleen negen
bestanden binnen testapp/eigen CI veranderd; HEMS blijft remote dev.263.
Volgende handeling: uitsluitend PicoT History Probe naar 0.2.0 bijwerken, één keer
handmatig starten en het volledige nieuwe JSON-log delen. Nog geen tweede NUC-log.

## Tweede NUC-log ontvangen — verwerking aantoonbaar, vertraging nog onbekend

Ontvangen bestand `87e174c3_picot_history_probe_2026-09-19T20-59-04.200Z.log`,
SHA-256 `d1ac05b7a9e20824f2a6b74cf2eb7046139ebf2a7346dbda59d2d6c1a99f6505`.
Het bestand bevat precies 100 regels (2.524 bytes) en begint midden in de
`offers`-lijst; het is geen compleet JSON-rapport. Baseline en heartbeatmetingen
ontbreken. Geen ontbrekende gegevens uit de eerdere proef overgenomen.

Zichtbaar: alle 1/2/4/8-MiB-records geaccepteerd, 4 gepubliceerd, 4 verwerkt,
geen pending werk, integriteit ok, opname gesloten. `workload_complete=true` en
`overlap_observed=true`; gemeten overlap 0,641 s. Maximale zichtbare aanbiedduur
0,064 ms. Beide gerapporteerde processen piek-RSS 50,11 MiB; tijdelijke bestanden
8,57 MiB. Indexfase 9,479 s wandtijd en 0,690 s CPU; opnamefase 9,718 s wandtijd
en 1,004 s CPU. Geen conclusie over controletik-/plannervertraging mogelijk.

Vervolg: bestaand app-log met meer regels ophalen, niet opnieuw draaien.
Officiële CLI-bron bevestigt `logs [slug]`, alias `addons`, en `--lines`/`-n`.
Opdracht: `ha addons logs 87e174c3_picot_history_probe --lines 300`.
Geen instellingen of productiecode gewijzigd.
