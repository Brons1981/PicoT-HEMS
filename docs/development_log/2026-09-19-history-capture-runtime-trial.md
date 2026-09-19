# 19 september — begrensde snapshotopname in de echte runtime

Status: lokale implementatie, standaard uit. Geen release, publicatie of wijziging
op de NUC in deze stap. HEMS-versie blijft dev.263; een toekomstige proefrelease
moet een eigen versie krijgen. Eerdere lokale historiewijzigingen zijn behouden.

## Verandercontract

- Ontbrekende grens: de beproefde recorder is nog niet aan de echte
  incidentregistratie verbonden; de losse testapp bewijst geen runtimebelasting.
- Autoriteit: bevroren canonieke pipeline, ADR-028 en de passieve eigenaargrens
  van ADR-037.13, plus Alex' akkoord op de beperkte praktijkproef.
- Eigenaar: historische registratie en de optionele samenstelling in live_runtime.
- Buiten scope: plannerregels, MEP, evaluatie, Plan Store, uitvoering, financiële
  berekeningen, automatische indexverwerking en afschaling/verwijdering.
- Invariant: oorspronkelijke incidentuitvoer en canonieke records blijven gelijk;
  geen wachten op duurzame opslag, geen herhaalpogingen bij opslaguitval.
- Bewijs: regressies voor aan/uit, echte MEP-records/commitments, grote snapshots,
  opslagfout, volle wachtrij, bezette lock, tijdgrens en bestaande pipelinesuites.
- Terugval: `history_capture_trial_enabled: false` en de app herstarten. Nieuwe
  bewijsbestanden blijven behouden. De draaiende installatie is nu niet aangepast.

## Voorafgaand NUC-bewijs

Het complete aangeleverde log `87e174c3_picot_history_probe_2026-09-19T21-20-34.194Z.log`
bevat de kleine proef en twee grote proeven. Beide grote proeven verwerken vier
records (1/2/4/8 MiB) met database-integriteit `ok`; overlap 0,640765 en 0,690408 s.
Controletik p95 baseline/opname: 0,274400/0,274514 ms respectievelijk
0,271880/0,257314 ms. Maximum tijdens opname: 0,383726 en 0,280489 ms.
Dit is synthetisch bewijs uit een afzonderlijke app, geen plannerkwalificatie.

## Implementatie en vaste grenzen

`HistoryCaptureTrial` wordt bij appstart uit de bestaande opties samengesteld.
Alleen de JSON-boolean `true` bij `history_capture_trial_enabled` activeert opname.
Ontbrekend/false maakt geen opslagdirectory en start geen capturethread. Het
HA-schema bevat de optionele boolean en de standaardwaarde false.

Ingeschakeld biedt de bestaande incidentregistratie haar ongewijzigde JSON-tekst
vóór 8-MiB-inkorting aan. Geen parsing/compressie/hashing/bestandsschrijven in de
callback. Er wordt alleen opgenomen wanneer de bestaande registratie een record
maakt; geen nieuwe plannerpolls of geforceerde herplanning. Volledigheid van elke
planbinding is daarmee nog niet bewezen.

Vaste proefgrenzen:

- 30 minuten vanaf recorderinitialisatie; daarna geen nieuwe opname. Een reeds
  begonnen bestandsoperatie mag afronden. Een OS-I/O-blokkade is niet afbreekbaar
  met deze thread; dit is geen harde muurkloktijdlimiet op een lopende schrijfactie.
- Maximaal twee aangehouden records, inclusief het actieve record; maximaal
  32 MiB per Python-tekstobject en samen 64 MiB gereserveerde tekstobjecten.
  Dit begrenst niet het totale runtimegeheugen, tijdelijke compressiebuffers of GIL.
- Eigen directory `/data/picot_history_capture_trial`, maximaal 512 MiB aan
  reguliere bestandsbytes inclusief achtergebleven tijdelijke bestanden; reserve
  van 128 MiB vrije schijfruimte plus conservatieve ruimte voor het volgende object.
  Inventaris maximaal 100.000 entries. Metadata/blokallocatie van het filesystem
  vallen buiten de bytebegroting. Andere processen kunnen vrije ruimte gebruiken.
- Eén capturewriter; geen indexworker, SQLite-import of andere schrijver in deze
  proefdirectory starten. Geen bestaande bestanden wissen om ruimte te maken.
- Iedere publicatiefout stopt verdere verwerking; wachtende teksten worden
  vrijgegeven en als `discarded` geteld. Geen automatische herstart of retry binnen
  de sessie. Bij een appherstart met de optie nog true begint een nieuwe proef.
- Een volle wachtrij/bezette lock/groot record geeft direct een getelde afwijzing;
  een gemist record wordt niet later ongemerkt opnieuw aangeboden.

Een initialisatiefout laat de runtime zonder callback doorgaan en wordt expliciet
`initialization_failed`. Er zijn dan geen betrouwbare gemiste-recordtellers.
Op het einde van iedere poll verschijnt één compacte JSON-regel
`picot_v2_history_capture_trial`, ook bij uitgeschakelde opname als baseline.

De regel bevat sessie-ID, starttijd, totale polltijd zonder wachttijd, proces-CPU
tijdens die poll (inclusief overige threads), actuele/piek-RSS, aanbiedduur,
aanbieduitkomsten, publicaties, gemiste records, wachtrij en laatst gemeten
opslagbytes. `storage_bytes=-1` betekent nog niet gemeten/onbekend. Bij een bezette
statuslock wordt de meting overgeslagen (`status_available=false`, onbekende
verlies-/publicatietelling), zonder op de schrijver te wachten. De bestaande
pipeline-stage timings blijven de bron voor de eigenlijke plannerduur; polltijd
bevat ook I/O, observatie en publicatie. De nieuwe logregel zelf valt buiten die
polltijdmeting. Een diagnostiekfout onderbreekt de runtime niet.

`missed` telt afgewezen aanbiedingen plus mislukte/afgebroken geaccepteerde records.
Afwijzingen na de tijdgrens zijn apart herkenbaar in `offer_outcomes.expired`.
In-flight records zijn nog geen geslaagde publicaties. Tellers zijn per proces;
bestanden blijven na herstart bestaan, tellerhistorie staat alleen in de logs.
Er is nog geen nieuwe diagnose-export/UI voor deze bewijsdirectory.

## Praktijkprotocol na een afzonderlijke proefrelease

1. Eerst 30 minuten draaien met de optie false; baseline-log en diagnose bewaren.
2. Optie true instellen en app herstarten, 30 minuten normaal gebruik. Geen nieuwe
   belasting of planwijziging forceren om bewijs te produceren.
3. Log bewaren met sessie-ID, opgeslagen/gemiste records, CPU/RSS en looptijden.
   Daarna optie false en herstarten. Bij ongewenst runtimegedrag direct stoppen.
4. Vergelijk vergelijkbare planneractiviteiten, niet alleen alle pollgemiddelden.
   Opstartpieken apart houden. Te weinig echte opnamen/plannerruns betekent
   onvoldoende bewijs; geen universele veiligheidsclaim uit één gemiddelde.
5. Een opslagfout/afwijzing of herhaald langere cycli vergt beoordeling voordat
   verder gebruik of indexverwerking wordt toegestaan. Geen automatische live
   goedkeuring op basis van tests of de losse NUC-proef.

Dit protocol is voorbereid, niet uitgevoerd. Optiewijziging vereist een herstart;
het is geen directe dashboardschakelaar. Een proefrelease/CI en NUC-meting blijven
volgende stappen. Automatische afschaling blijft uit.

## Verse lokale verificatie

Wordt hieronder aangevuld met de daadwerkelijk afgeronde controles.

- Nieuwe tests faalden eerst door de ontbrekende `passive_history.trial`-module.
  Daarna slagen de functies voor uit/aan, bytegelijkheid boven 8 MiB, stop bij
  schrijffout met vrijgeven van de wachtrij, tijdgrens, niet-wachtende status,
  behouden tijdelijke bestanden, lage vrije ruimte en foutisolatie van logging.
- Brede reeks: **134 tests geslaagd in 52,50 s**, inclusief echte diagnose via
  `PICOT_TEST_DIAGNOSTIC`, passieve opslag/retentie, bestaande incidentregistratie,
  MEP, canonieke pipeline/uitvoering, commitments/herstel, architectuur en packaging.
- Daarna **13 gerichte tests geslaagd in 2,03 s**. Deze bevatten de elf proefchecks
  uit de brede reeks plus twee aanvullingen: echte MEP-recordopname met bytegelijke
  commitmentopslag/ongewijzigde run, en lage vrije ruimte met expliciete verlies-
  telling. Daarmee 136 verschillende checks afgedekt, niet 147.
- Ruff geslaagd voor het passieve package, live_runtime, incidentregistratie en
  de nieuwe proefchecks. Mypy `--follow-imports=silent`: tien bronbestanden groen.
- `git diff --check` geslaagd. Geen wijziging aan planner/MEP/commitment-/
  uitvoeringsmodules; de live-runtimewijziging betreft samenstelling en meting.
- Geen volledige repository-CI, containerbouw, publicatie, proefrelease of
  echte opname binnen PicoT op de NUC uitgevoerd. Runtimebelasting blijft te meten.

Lokale opdracht voor de brede reeks:

```sh
PICOT_TEST_DIAGNOSTIC=/pad/naar/diagnose.zip python -m pytest -q \
  tests/test_v2_passive_history_trial.py tests/test_v2_passive_history.py \
  tests/test_v2_passive_history_diagnostic.py tests/test_v2_passive_history_retention.py \
  tests/test_v2_planning_incident_history.py tests/test_v2_mep_canonical_pipeline.py \
  tests/test_v2_canonical_pipeline.py tests/test_v2_canonical_execution_runtime.py \
  tests/test_v2_plan_commitment_store.py tests/test_v2_plan_commitment_recovery.py \
  tests/test_v2_mep_single_planner_architecture.py tests/test_architecture_ownership.py \
  tests/test_v2_addon_runtime_packaging.py
```

## Release dev.264 — voorbereiding na akkoord

Alex heeft publicatie van de proefrelease bevestigd. De releasebranch is gebaseerd
op actuele main `a1f00bfe9111b6b0e05b2a349352f723751a1e91`; de afzonderlijke History
Probe-app wordt niet gewijzigd. HEMS-manifest en Python-versie worden samen dev.264.
De eerder lokale passieve historiecode en bijbehorende regressies worden in deze
release opgenomen; alleen de expliciete captureschakelaar heeft een runtimepad.
Offline import-, index- en retentietools worden niet automatisch aangeroepen.

Verse releasecontrole: Ruff voor alle `src/picot`-code en de nieuwe tests is groen;
volledige mypy op `src/picot` slaagt voor 222 bronbestanden (v2: 85 bestanden).
De bron bevat geen diagnose-ZIP of meetgegevens. Publieke tests slaan de externe
privédiagnose over; die wordt in de lokale releasecontrole afzonderlijk gebruikt.
De praktijkproef begint na installeren met de optie false, dus zonder captureworker.
Publicatie is pas afgerond na groene GitHub-controles en samenvoeging.

De volledige gerichte releasecontrole is opnieuw uitgevoerd op dev.264:
**136 tests geslaagd in 55,69 s**, inclusief de echte diagnose. Dit vervangt
voor deze release de eerdere opgesplitste 134+13-resultaten. `git diff --check`
is schoon. Volledige repositorytests volgen via de verplichte GitHub-workflows.
