# 2026-09-19 — passieve historie: geïntegreerde lokale implementatie

Status: lokaal geïmplementeerd, standaard niet aangesloten. Geen commit, push,
release of wijziging aan de draaiende installatie. Basis: dev.263 / `1854229`.

## Verandercontract

1. Probleem/grens: de incidentregistratie kan volledig besluitbewijs vóór schrijven
   inkorten; de bestaande losse meetarchieven bieden niet de overeengekomen
   duurzame, geversioneerde historische gegevensvoorziening. Dit is een
   registratiegrens, geen aangetoond defect van MEP.
2. Beheersende afspraken: bevroren canonieke pipeline, ADR-019, ADR-028,
   ADR-037.13 en de door Alex bevestigde passieve bewaar-/vergelijkafspraken van
   19 september. Historie stelt geen nieuwe plannervoorwaarden.
3. Eigenaar: nieuwe `picot.v2.passive_history`; bestaande producenten blijven eigenaar
   van oorspronkelijke feiten, planbinding, uitvoering en financiële resultaten.
4. Buiten scope: MEP, selectie, Plan Store-transacties, actuation, bestaande
   financiële voorraad/prognose-inputs en alle HA-instellingen.
5. Invariant: capture-uitval, ontbrekend bewijs of historische verwerking kan geen
   plan weigeren, aanpassen of laten wachten op duurzame opslag. Een optionele
   callback mag uitsluitend een niet-wachtende aanbieding uitvoeren.
6. Bewijs: bytegelijke oorspronkelijke incidentuitvoer met capture aan/uit/fout;
   behoud van bronidentiteiten en revisies; echte diagnose 88/96; bounded werk,
   transactieherstel; bestaande MEP-/uitvoerings- en architectuurtests.
7. Terugval: optionele recorder niet meegeven en expliciete worker/importcommands
   niet starten. Oude bestanden blijven intact; nieuwe historie mag blijven staan.

## Geïmplementeerd

- `planning_incident_history.py`: één optionele `evidence_offer`-callback, standaard
  None. De bestaande volledige JSON-string wordt vóór de 8-MiB-reductie aangeboden.
  Callbackuitkomst/fout verandert de bestaande incidentuitvoer niet. Geen nieuwe
  callsite of workerinitialisatie in `live_runtime`.
- `passive_history/evidence.py`: expliciet aangemaakte recorder met niet-wachtende
  lockpoging, maximaal twee records inclusief actieve taak, 64 MiB aangehouden
  tekstobjecten, 32 MiB per object. Gzip-publicatie, digest, fsync en deduplicatie
  vinden buiten de producer plaats. Een bestaande corrupte kopie wordt niet
  overschreven. Afwijzingen/fouten krijgen beperkte counters.
- `storage.py` en `schema.sql`: eigen gemarkeerde directory, SQLite WAL/FULL,
  foreign keys, geversioneerde compacte waarden, append-only dag-/tarief-/financiële
  records, afzonderlijke herkomstverwijzingen, expliciete bewijsstatus en
  planidentiteiten. Schema-initialisatie gebeurt in één transactie.
- Planbewijs wordt op oorspronkelijke plan-, snapshot- en evaluation-ID gekoppeld,
  ongeacht of het planregister of de poll eerst wordt geïmporteerd. Herontdekken
  van een oud bronobject draait een nieuwere correctie niet terug. Een nieuw
  bronobject met een echte correctie levert een nieuwe revisie. Identieke
  waarden delen hun revisie met aanvullende bronverwijzingen.
- Meetarchieven leveren de werkelijk aanwezige kwartierwaarden, Nederlandse
  kalenderidentiteit, huishoudelijke dagsom en afzonderlijke overige stroomdagsommen.
  Een ongeldige/onvolledige waarde wordt niet nul. Ongeldige/partiële kwartieren
  tellen niet als volledig huishoudkwartier. Overige stroomdagsommen blijven
  uitdrukkelijk afgeleid en niet onafhankelijk gevalideerd.
- Brononderbrekingen uit de bestaande review krijgen gap/observation-records zonder
  een oorzaak of herstel te verzinnen. Negatieve huishoudbalansen blijven als
  ongeldige kwartieren met reden beschikbaar; geen versoepeling van strict replay.
- Originele importprijzen en onbekende aparte exportprijzen blijven onderscheiden.
  Geen nieuwe financiële rekenregel: oorspronkelijke financiële dagpayloads worden
  onveranderd bewaard als legacy-uitkomsten, met onbewezen financiële afsluiting.
- `calendar.py`: Europe/Amsterdam, UTC-microseconden, Nederlandse datums, ISO-week,
  weekdag en ordinaal; 92/96/100 kwartieren en drie/90-dagen/vijfjaarsclassificatie.
  Classificatie voert geen verwijdering uit.
- `worker.py`: expliciete eenmalige worker met 128 MiB virtuele-adresruimtelimiet
  en twee CPU-seconden, maximaal vier verwerkte bronrecords per normale batch.
  Directoryontdekking gebruikt een persistente bucket/naamcursor; pending queue
  maximaal 64. Iedere bucketinventaris is begrensd tot 4.096 entries. Onvoldoende
  vrije ruimte pauzeert verwerking; een geheugenlimiet levert uitstel op.
- `importer.py`: expliciete hervatbare diagnose-import, maximaal zestien nieuwe
  records per aanroep. Bronhash en ZIP-member/offset geven voortgang; geen
  extractie buiten de eigen directory. Originele bronbestanden blijven ongemoeid.

## Gebruik uitsluitend in een afzonderlijke proefdirectory

Er bestaat geen automatische activering, nieuwe HA-optie of gewijzigd startscript.
Een ontwikkelaar kan de constructor expliciet verbinden:

```python
recorder = EvidenceRecorder(history_directory)
incidents = PlanningIncidentHistory(incident_path, evidence_offer=recorder.offer)
```

Deze aansluiting wordt nergens door de huidige live-compositie gemaakt. Sluiten
van de recorder is een beheeractie, niet iets waarop een plannercyclus wacht.

Eenmalige taken vanuit een geïnstalleerde package of met `PYTHONPATH=src`:

```sh
python -m picot.v2.passive_history.importer DIAGNOSE_ZIP NIEUWE_HISTORIEDIRECTORY
python -m picot.v2.passive_history.worker HISTORIEDIRECTORY
```

De importer kan opnieuw worden gestart om zijn opgeslagen positie te hervatten.
De worker verwerkt één begrensde stap en eindigt. Geen onbeperkte scheduler of
onmiddellijke herstartlus. Importer is een expliciete offline migratietool: ZIP-hash
berekenen en seek in gecomprimeerde JSONL kan eerdere bronbytes opnieuw lezen;
die I/O is niet als live achtergrondlatentie gecertificeerd.

## Grenzen en nog niet vrijgegeven

- Geen automatische afschaling/verwijdering. Bestaande snapshotbewaarplichten en
  oudere afhankelijkheden worden hierdoor niet verkort. Het schema bevat de
  benodigde plaatsen voor dependency-/retentionregistratie; volledige geneste
  bewijsresolutie en een uitvoerende opschoner zijn nog niet gebouwd.
- De databasegrens is 256 MiB, het ingestelde bewijsbudget 512 MiB en de standaard
  vrije-ruimtereserve 128 MiB. Dit zijn proefinstellingen per onderdeel, geen
  bewezen totale installatiebegroting. WAL, tijdelijke bestanden, metadata en
  backups vragen extra ruimte. Er wordt niets verwijderd om ruimte te maken.
- De capturethread deelt GIL en procesgeheugen. De afzonderlijke indexworker heeft
  een OS-adresruimtelimiet; dat begrenst niet de volledige PicoT-runtime. Producer-
  en NUC-belasting, schedulerinterval, failover na een worker-CPU-kill en live
  resourcegrenzen vragen nog een gecontroleerde doelomgevingsproef.
- Bestandsbeschikbaarheid betekent verificatie op het verwerkingstijdstip. De view
  is geen permanente bestandsmonitor; toekomstig lezen/exporteren moet opnieuw
  verifiëren. Actuele rechecks en exports zijn nog geen live UI-functionaliteit.
- Een groot of ontbrekend record kan nog verloren blijven. De nieuwe aansluiting
  herstelt geen reeds ingekorte oude snapshots en biedt geen absolute garantie
  tussen planbinding en passieve capture.
- Dagafsluiting uit een geïmporteerd meetarchief betreft uitsluitend zijn manifest
  en de gearchiveerde dekking. Een volledige huishoudsom certificeert geen volledige
  financiële afsluiting, leveranciersafrekening of beslisreplay.
- Platform-/functie-/installatiecontext kan in de geversioneerde definities worden
  bewaard; er is nog geen live bron die ontbrekende installatie- of versiehistorie
  aanvult. Er worden geen ingangsdatums verzonnen.

## Verificatie

Een afzonderlijke tijdelijke ontwikkelomgeving bevat pytest, Ruff en mypy;
repositoryrequirements en de live installatie zijn niet aangepast. De eerste
regressie faalde op het nog ontbrekende `evidence_offer`-argument en slaagt met
de optionele aansluiting. De bestaande bounded incidentbytes blijven gelijk.

De echte diagnose van 19 september is met de nieuwe modules geïmporteerd:
171 geregistreerde plannen, zeven gekoppelde oorspronkelijke beslisrecords,
288 kwartiertarieven en 88 bruikbare huishoudkwartieren op 18 september. De
huishouddag blijft gedeeltelijk, met 6.120,070153740213 Wh als gedeeltelijke som.
De bronhash blijft gelijk; herhaalde import maakt geen extra boekingen. Ook de
oudere daadwerkelijk aanwezige financiële dagrecords worden meegenomen, zonder
historie tot de drie replaydagen te beperken.

Gerichte verificatie omvat de nieuwe historie- en diagnoseproeven plus bestaande
incident-, meet-, review-, diagnose-export-, commitment-, MEP-, execution- en
architectuursuites. Zie afsluitende verificatieregel hieronder voor de verse
uitkomst. Ruff geldt voor de gewijzigde/nieuwe Python-bestanden; mypy is gericht
op de zeven betrokken modules met `--follow-imports=silent`. Dit is geen claim
dat volledige repository-CI of live-validatie al heeft gedraaid.

### Afsluitende verificatie van deze implementatie

- **118 tests geslaagd in 52,99 seconden**, inclusief de echte diagnose via
  `PICOT_TEST_DIAGNOSTIC`, de subprocesshersteltest en de bestaande MEP-,
  uitvoerings-, commitment- en architectuursuites.
- Ruff: alle gewijzigde/nieuwe Python-bestanden en nieuwe tests geslaagd.
- Mypy: zeven betrokken modules geslaagd met `--follow-imports=silent`.
- `git diff --check`: geslaagd.
- De enige wijziging aan bestaande uitvoerbare code is de optionele callback in
  `planning_incident_history.py` (negen toegevoegde regels). `live_runtime.py`,
  `mep_canonical_pipeline.py` en `plan_commitment_store.py` zijn ongewijzigd.
- Geen commit, push, CI-aanroep, release, HA-verzoek of live aansluiting uitgevoerd.

## Vervolg — bewaaroverzicht en afzonderlijke vergelijkkopie

Verandercontract: uitsluitend de nieuwe passieve opslag lezen en afschaling op een
nieuwe offline vergelijkkopie beproeven. Geen verwijderroute in de oorspronkelijke
opslag, geen vervanging van een bestaande database, geen automatische activering.
Hoofdrisico's zijn verlies van kwartierprijzen/kwaliteitsinformatie, verkeerd
afschalen van Nederlandse dagen, verouderde besluiten en publiceren van een
onvolledige kopie.

`passive_history/retention.py` voegt een alleen-lezen overzicht en een expliciete
kopieeropdracht toe. Het overzicht vermeldt per dag en meetsoort wat behouden
blijft, wat uitsluitend in de kopie mag vervallen en waarom. Een SHA-256-token
bindt dit aan beleid, Nederlandse peildatum en de volledige logische bronsnapshot.
De uitvoering leest opnieuw in één consistente SQLite-leestransactie en weigert
bij een gewijzigd token. Wijzigingen die na die snapshot worden vastgelegd horen
niet bij deze vergelijkkopie; de bron blijft altijd behouden.

Bewaarregels in deze stap:

- Vandaag, gisteren en eergisteren en alle overige dagen jonger dan 90 dagen:
  alle kwartierwaarden behouden. Ruwe bewijsobjecten blijven op alle leeftijden
  ongemoeid; snapshotafhankelijkheden worden hier niet verwijderd.
- Dag 90 tot de vijfjaarsgrens: uitsluitend bekende vijf energiestromen mogen hun
  kwartiergetallen in de kopie verliezen. Dit vereist één oorspronkelijke revisie,
  dezelfde herkomst, afgesloten dag, niet-overlappende intervallen, bekende
  aggregatiemethode en exact aansluitende dag-/deelsom en dekking. Geen nieuwe
  numerieke tolerantie. Onzekerheid betekent behoud.
- Huisverbruik, alle import-/exporttariefrevisies, dagelijkse waarden, financiële
  bronuitkomsten, kalenderidentiteit, contexten, gebeurtenissen, gaten en
  bewijsverwijzingen blijven bewaard. Onbekende toekomstige meetsoorten blijven
  eveneens behouden. Meerdere revisies vereisen eerst afzonderlijke beoordeling.
- Gegevens van vijf jaar of ouder krijgen beoordeling, geen automatische
  verwijdering. Ook oudere configuratieankers blijven dus aanwezig.
- Van weggelaten kwartiergetallen blijft elke kwaliteits-/herkomstverwijzing met
  tijdvak, revisie en registratietijd bestaan in `compacted_interval_quality`.
  `revision_source` blijft daarbij intact en kan voor deze intervallen aan die
  tabel gekoppeld worden. De kopie maakt ontbrekende of ongeldige metingen niet
  geldig; onvolledige dagsommen blijven onvolledig.

De nieuwe SQLite-kopie krijgt een eigen application-ID. `HistoryStore` weigert
haar als schrijfbare historie, vóór WAL-initialisatie. Het is een vergelijkbestand
met externe bewijsverwijzingen naar de bron, **geen zelfstandige replayback-up en
geen vervanging van de actieve database**. Bestaande onveranderlijkheidstriggers
blijven in de kopie werken; de oorspronkelijke triggers worden nooit uitgeschakeld.

Voorbeeld, uitsluitend in een ontwikkel-/proefomgeving:

```sh
python -m picot.v2.passive_history.retention HISTORIEDIRECTORY --today 2026-12-18
python -m picot.v2.passive_history.retention HISTORIEDIRECTORY --today 2026-12-18 --output /PAD/BUITEN/BRON/vergelijk.sqlite --expected-token TOKEN_UIT_OVERZICHT
```

Zonder `--today` geldt de huidige datum in Europe/Amsterdam. De uitvoer mag nog
niet bestaan. De tijdelijke kopie wordt pas na foreign-key-/integriteitscontrole,
commit en fsync atomair beschikbaar gemaakt zonder overschrijven. Een gewone
fout ruimt het tijdelijke bestand op. Een harde processtop kan een ongepubliceerd
`.history-projection-*`-bestand achterlaten; er is geen automatische opruimer.

Dit is een volledige offline scan, geen begrensde live workerbatch: maximaal
256 MiB brondatabase, 20.000 meetsoort/daggroepen, maximaal 101 detailrecords per
beoordeelde groep en SQLite-voortgangscontrole met een tijdgrens van 120 seconden
voor lezen respectievelijk schrijven. Vooraf moet ruimte bestaan voor tweemaal de
bronomvang plus 128 MiB reserve. Die controle reserveert geen schijfruimte en is
geen bewijs van NUC-geheugen- of latentiebudgetten.

### Verse verificatie van deze vervolgstap

- Nieuwe tests begonnen met de verwachte ontbrekende-modulefout. Daarna zijn de
  bewaarranden, 92/100-kwartierdagen, onbekende toekomstige meetsoorten, ontbrekende
  waarden, revisies, verouderd token, lage schijfruimte, fout na kopieertransactie,
  onveranderlijkheid en weigering als actieve historie getoetst.
- De echte diagnose is opnieuw geïmporteerd en uitsluitend in de proef op
  18 december 2026 beoordeeld. Er vervallen 480 overige stroomkwartiergetallen van
  18 september in de kopie. De open dag 19 september blijft behouden. Alle overige
  inhoudstabellen zijn rij voor rij vergeleken; huishoudkwartieren blijven exact
  gelijk, evenals 288 tarieven en zeven bruikbare plankoppelingen. De oorspronkelijke
  diagnose-ZIP blijft bytegelijk. De huishoudelijke conclusie blijft 88/96; dit
  levert geen volledige strikte replay op.
- Proefomvang: bron-SQLite 856.064 bytes, vergelijkkopie 843.776 bytes. Dit is geen
  meerjarenraming: extra auditinformatie kost ruimte en de bron plus bewijsobjecten
  blijven bestaan. Deze stap bespaart dus nog geen ruimte op de actieve installatie.

Automatische afschaling/vervanging, verwijderen van ruwe objecten en plansnapshots,
verwerking van complexe revisieafhankelijkheden en praktijkmeting op de NUC blijven
buiten deze stap. Planner, MEP, uitvoering en live-samenstelling blijven ongemoeid.

Verse eindcontrole: **43 tests geslaagd in 10,89 s** met
`PICOT_TEST_DIAGNOSTIC` ingesteld op de diagnose-ZIP, voor
`test_v2_passive_history_retention.py`, `test_v2_passive_history.py`,
`test_v2_passive_history_diagnostic.py`, `test_v2_planning_incident_history.py`
en `test_architecture_ownership.py`. Ruff slaagt voor het passieve package,
incidentregistratie en de gewijzigde tests. Mypy met `--follow-imports=silent`
slaagt voor acht bronbestanden; `git diff --check` slaagt. Geen volledige nieuwe
repositorytest of live-/NUC-test uitgevoerd.

## Vervolg — tijdelijke bronuitval en expliciete hercontrole

De integrale uitvaltoets vond een reproduceerbaar hersteldefect: één tijdelijke
`OSError` bij lezen werd `invalid_record`; herstart en herontdekking lieten het
inmiddels geldige bestand onverwerkt. Alex heeft de gerichte reparatie bevestigd.
Verandergrens: uitsluitend de passieve worker en bijbehorende controles, geen
planner, MEP, automatische retry, release of live-aansluiting.

`worker.py` onderscheidt nu `source_unavailable` van `invalid_record`.
Gzip-/decompressiecorruptie, verkeerde digest, ongeldige inhoud en onveilig pad
blijven ongeldig. Een I/O-fout bewijst geen corruptie en krijgt de afzonderlijke
onbeschikbaarheidsstatus. Dit garandeert niet dat een onbeschikbare bron later
herstelt. De observatie blijft bewaard; eerder bruikbaar planbewijs is tijdens
onbeschikbaarheid niet meer bruikbaar volgens de bewijsindex. Meetrevisies worden
hierdoor niet herschreven. Na succesvolle hercontrole kan de bewijskoppeling weer
bruikbaar worden; volledige strikte replay wordt daarmee niet gecertificeerd.

`recheck_unavailable` neemt uitsluitend 1–16 expliciet gekozen SHA-256-digests aan,
zet alleen onbeschikbare jobs terug naar pending en bewaart eerdere pogingen en
observaties. De totale pending-wachtrij blijft maximaal 64. Capaciteitscontrole en
inplannen gebeuren onder één SQLite-schrijftransactie. Herontdekking, herstart en
normale verwerking plannen geen nieuwe hercontrole. Na een tweede leesfout stopt
de taak opnieuw op onbeschikbaar. Ongeldige records worden via deze route nooit
opnieuw ingepland. Historische `invalid_record`-statussen uit de oude versie worden
niet automatisch geherclassificeerd.

Expliciete beheeropdracht, uitsluitend voor de afzonderlijke proefopslag:

```sh
python -m picot.v2.passive_history.worker HISTORIEDIRECTORY --recheck-digest SHA256
```

De optie mag tot zestien keer worden opgegeven. De opdracht plant in en verwerkt
één normale batch van maximaal vier pending jobs; andere eerder ingeplande jobs
kunnen daarin eerst aan de beurt komen. Geen scheduler of onbeperkte herhaallus.
De bestaande proceslimieten blijven gelden.

Verificatie: de twee eerste regressietests faalden vóór de wijziging op de oude
classificatie en ontbrekende hercontrolefunctie. Daarna 47 tests geslaagd in
10,62 s voor passieve opslag/retentie, echte diagnose, incidentregistratie en
architectuur. Een aanvullend subprocess-test van de nieuwe CLI slaagt afzonderlijk
(1 test). Gedekt: herstart zonder automatische retry, expliciet herstel, behoud
pogingteller/observaties, corrupte gzip geweigerd, maximaal 16 selecties, volle
wachtrij, herhaald ontbrekend bestand en intrekken/herstellen van planbewijs.
Ruff en mypy slagen. NUC-belasting en gedeelde procesresources blijven onbewezen.

## Vervolg — optionele runtime-opnameproef

De latere lokale aansluiting en de actuele grenzen staan in
`2026-09-19-history-capture-runtime-trial.md`. Daarmee is de eerdere status
"geen live callsite" voor de lokale broncode achterhaald: er is nu een expliciete
optie die standaard false is, uitsluitend voor capture. Geen indexworker of
verwijdering gestart. Er is nog geen HEMS-release of live-optiewijziging uitgevoerd.
