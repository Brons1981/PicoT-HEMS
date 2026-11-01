## Release HEMS dev.325 en ED dev.14 - 1 november 2026

Alex heeft release van de gezamenlijke EV/batterijreparatie aangevraagd. Basis main:
e72f0bfa3fedb5a26149416a9bf55d958fe47a27. Werkmap: joint-ev-repair.
Volledige vergelijking van EV en batterij via bestaande canonieke onderdelen;
expliciete acceptatie met duurzame batterijbevestiging voordat ED mag starten.
Installeer eerst ED dev.14, daarna HEMS dev.325 en vraag nieuw laadadvies aan.
HC blijft dev.26. Geen planreset vereist. Publicatie via PR na groene CI.
Zie V2ADR-068 en docs/development_log/2026-11-01-joint-ev-battery-repair.md.

## Release HC dev.26 - 31 oktober 2026

Alex vraagt release van de nachtelijke PV-reparatie. Basis main ec64f5e74983eb3971c90684b4c2a2f088130b24.
Publicatie via PR na groene CI; HC dev.26, HEMS ongewijzigd. Geen live installatie.
Zie docs/development_log/2026-10-31-tablet-night-pv.md voor scope en verificatie.

## Reparatie tablet nachtelijke PV - 31 oktober 2026

HC dev.25 gepubliceerd via PR #735, merge ec64f5e74983eb3971c90684b4c2a2f088130b24.
Alex meldt wisselend ontbrekend huisvermogen bij slapende PV en vraagt reparatie.
Lokale wijziging: tablet.py neemt alleen bij sun.sun below_horizon 0 W aan voor
ontbrekende/verouderde PV; verse PV en controles op net/batterij blijven leidend.
Zie docs/development_log/2026-10-31-tablet-night-pv.md. Nog niet gepubliceerd.

## Release HC dev.25 - 31 oktober 2026

Alex heeft publicatie van het lokale tablet-dashboard en de tijdelijke
kamertemperatuur aangevraagd. Basis main 58bf87278ae88cee0a5dab6a720da9ac1a75ded6.
HC wordt 0.1.0-dev.25; HEMS blijft dev.324. Publicatie via PR na groene CI.
Geen planreset. Installatie, tabletactivering en fysieke iPad-controle volgen
apart. Zie docs/development_log/2026-10-31-tablet-dashboard.md.

## Lokaal tablet-dashboard - 31 oktober 2026

Alex heeft opdracht gegeven het goedgekeurde tabletontwerp lokaal met HC te
koppelen. Werkmap tablet-dashboard-work, basis dev.324/HC dev.24. Lees
`docs/development_log/2026-10-31-tablet-dashboard.md`. Nieuwe opt-in lokale
tablettoegang, actuele energiemetingen en tijdelijke kamerdoeltemperatuur tot
de volgende schemagrens. HEMS-planner en andere zones ongewijzigd.
29 gerichte Python-tests, 17 JS-tests en HTTP/browsercontrole geslaagd.
Brede HC-suite: 451 geslaagd, bestaande LF/CRLF-testfout en een eenmalige
netwerkfout (afzonderlijk groen). Linux-CI en fysieke iPad/livecontrole volgen.
Geen versieophoging, release, push of installatie uitgevoerd.

## Release HEMS dev.324 - 31 oktober 2026

Alex heeft release van de praktische planbeschrijving aangevraagd. Basis main:
79c442b523ec39750918b0b7e91a85c7a5a2c8d5 (dev.323). Publicatie via PR na groene CI.
Lokale geintegreerde verificatie: 162 tests groen, Ruff en gerichte Mypy groen.
Home Climate blijft dev.24; geen planreset. Installatie volgt afzonderlijk.

## Praktische planbeschrijving - vervolg op dev.323, 31 oktober 2026

Alex wil de verwachte zonne- en netlaadhoeveelheden, overblijvende zonne-energie
voor huis/teruglevering, laadvensters, verwachte 100%-tijd en onderbouwd voordeel
van stand-by tegenover batterijondersteuning zichtbaar op het dashboard.
Geimplementeerd in `plan-explanation-fix`; zie
`docs/development_log/2026-10-31-practical-plan-explanation.md`.
Read-only weergave van bestaande simulatiegegevens; geen nieuwe plankeuze.
Nog geen nieuwe release of installatie. Dev.323 zelf is gepubliceerd via PR #733,
merge 79c442b523ec39750918b0b7e91a85c7a5a2c8d5.

## Release HEMS dev.323 - 31 oktober 2026

Alex heeft release van de totale-routekostenreparatie en dashboarduitleg aangevraagd.
Basis main 967c3b38ff9f297a40fcb2b7721396a0f99d1b40; gewijzigde basisbestanden
zijn met GitHub-blobhashes gecontroleerd. Publicatie via PR en volledige CI.
Home Climate blijft dev.24. Geen planreset nodig. Installatie en livecontrole
volgen afzonderlijk. Zie het ontwikkellog van 31 oktober en V2ADR-067.

## Totale routekosten en planuitleg - lokaal, 31 oktober 2026

Alex vraagt reparatie van de inconsistente optionele laadherziening en uitleg op
het dashboard. Werkmap `plan-explanation-fix`, basis de lokale dev.322-bronkopie
`recovery-continuity-refactor`. Lees V2ADR-067 en het ontwikkellog
`docs/development_log/2026-10-31-complete-route-decision.md`.
Optionele revisies van een geldige route vergelijken totale EUR bij gelijke
eindvoorraad; de bestaande 1-centdrempel blijft. UI toont echte beslisgegevens.
Geen release, versieophoging, commit, push of livewijziging uitgevoerd.

## Release HEMS dev.322 - 26 oktober 2026

Alex heeft publicatie van de cumulatieve herstel-, routekeuze- en meldingsverbeteringen aangevraagd.
Versie dev.322 gaat via PR en volledige CI naar main. Zie de vier ontwikkellogs hieronder.
Lokale geintegreerde suite: 369 geslaagd; Ruff/mypy groen. Release-CI wordt op de PR vastgelegd.
Geen planreset nodig. Home Climate blijft dev.24. Installatie en livecontrole volgen afzonderlijk.
Onderstaande lokale statusblokken beschrijven de voorafgaande implementatiefasen.

## Vier verbeterpunten herstel en meldingen - lokaal, 26 oktober 2026

Alex gaf akkoord op herstelbeslissingen samenbrengen, herstartveiligheid,
incidentreeksen en een meldingsroute. Lees
`docs/development_log/2026-10-26-recovery-consolidation.md` en
`docs/development_log/2026-10-26-single-health-notification-route.md`.
Een nieuwe runtime wacht op verse plantoestemming. Tijdelijk uitvoeringsbewijs
verloopt ook bij de start van een ongebonden nieuw dagdoel. Vijf vergelijkbare
failurepaden gebruiken dezelfde behoud/blokkeerbeslissing; legitieme fysieke
verschillen blijven bestaan. PlanningFallbackNotifier is verwijderd; HealthNotifier
is de enige meldingseigenaar na publicatie, met oorzaakdeduplicatie over herstart.
Opstartwachten en bewijsverloop zijn geen actuatorstoringen of herstelbewijs.
De eerdere lokale routekeuze-input en uitvoeringscontinuiteit zijn behouden.
Geintegreerde eindsuite: 369 geslaagd; Ruff en mypy groen. Web/volledige release-CI
en livewerking zijn nog niet aangetoond.
Geen release, versieophoging, Home Assistant-opdracht of externe melding uitgevoerd.

## Vervolg: routekeuze in Planning Input - lokaal, 26 oktober 2026

Op verzoek van Alex is routekeuze uit de tussentijdse planner-Store-reads gehaald.
Lees `docs/development_log/2026-10-26-route-choice-planning-input.md`.
Pending en selected consent worden onveranderlijk vastgelegd bij inputopbouw;
hoofdroute en handel gebruiken dezelfde gegevens. Definitieve opslagcontroles blijven.
De eerdere lokale herstelwijziging is behouden. Geen release of livewijziging.
Webtestverificatie is lokaal beperkt door geblokkeerde loopback sockets (WinError 10013),
ook gereproduceerd op de ongewijzigde dev.321-basis. Overige brede suite: 180 geslaagd;
finale routekeuze-integratie: 10 geslaagd, samen 181 unieke tests. Ruff/mypy groen.

## Lokale vereenvoudiging van herstel - 26 oktober 2026

Alex heeft de vereenvoudiging goedgekeurd na de stabiliteits-/ADR-audit.
Werkbasis is dev.321 / main e2206992c8ef86bce2c26aec31d7972b4d71795f.
Lees `docs/development_log/2026-10-26-current-execution-continuity.md`.
Een onopgeloste volledige herplanning kan de huidige actie alleen met expliciet,
begrensd fysiek bewijs behouden. Geen nieuwe winnaar, doelvoltooiing of storewijziging.
De volledige diagnose-replay behoudt NOM tot 14:15 en alle open laadopdrachten.
Routekeuze via immutable Planning Input is in de vervolgstap hierboven uitgevoerd;
overige herstelpaden blijven afzonderlijk vervolgwerk.
Geen release aangevraagd voor deze wijziging; versie en liveinstallatie ongewijzigd.

## Release HEMS dev.321 - NOM-continuiteit na reset, 26 oktober 2026

Alex heeft dev.320 live bevestigd; het herstel slaagt, maar het middag-NOM wordt opgeknipt.
Op akkoord is een gerichte vervolgcorrectie gemaakt. Lees
`docs/development_log/2026-10-26-recovery-nom-continuity.md`.
Valideer en behoud de passieve resterende oorspronkelijke route, ook voor een reeds
opgeslagen dev.320-resetroute. Geen herleving van geannuleerde laad-/handelsopdrachten.
Echte diagnose: NOM 09:00-15:00 hersteld en na restart behouden. Alex heeft release dev.321 aangevraagd; publicatie via PR en groene CI.
Installatie en livecontrole volgen afzonderlijk; Home Climate blijft dev.24.

## Release HEMS dev.320 - 26 oktober 2026

Alex heeft publicatie van het automatische herstel na historische dagvoltooiing aangevraagd.
Via PR en CI naar main. Geen planreset nodig; herstel volgt na opstart met geldige invoer.
Home Climate blijft dev.24. Installatie en livecontrole volgen afzonderlijk.
Zie `docs/development_log/2026-10-26-completed-day-recovery.md`.

## Automatisch herstel voltooid dagdoel - lokaal, 26 oktober 2026

Alex vraagt reparatie na HA Core-update en herstelreset. Lees
`docs/development_log/2026-10-26-completed-day-recovery.md`.
Een voltooid dagdoel zonder volgende sessie krijgt nu via de canonieke pipeline
weer een uitvoerbare resterende route, ook na reset. Voltooiing/historie blijven intact.
Meldingen verklaren de oorzaak en automatische vervolgstap; ontbrekende invoer wordt benoemd.
Echte diagnose voor en na reset offline succesvol herhaald. Nog geen release/live-update.

## Release HEMS dev.319 - 24 oktober 2026

Alex heeft publicatie van de uitvoeringsmelding- en kleurenreparatie aangevraagd.
Via PR en CI naar main; Home Climate blijft dev.24. Geen planreset nodig.
Installatie en livecontrole volgen afzonderlijk. Zie het onderstaande ontwikkellog.

## Dashboardmelding en kleuren - lokaal, 24 oktober 2026

Alex meldt na dev.318 onterecht 0% planningszekerheid en blauw netladen.
Lees `docs/development_log/2026-10-24-dashboard-execution-confidence.md`.
De nieuwe diagnose toont planbehoud en already_active Standby zonder blokkades.
Alleen de UI maakte een fictieve blokkade van ontbrekende kandidaatscores.
Readiness volgt nu de uitvoeringsrecords; kleuren volgen de bestaande prijsbalk.
Geen planner-/aansturingswijziging, release of live-update uitgevoerd.

## Release HEMS dev.318 en HC dev.24 - 24 oktober 2026

Alex heeft de gezamenlijke publicatie goedgekeurd. Dashboardvereenvoudiging en HC-bronrapportage gaan via PR en volledige CI naar main. Installatie volgt apart; beide apps bijwerken, geen planreset nodig. Zie de twee onderstaande ontwikkellogs voor scope en bewijs.

## Aanvulling HC-bronrapportage - lokaal, 24 oktober 2026

Alex heeft de HC-meetfout aan de dashboardreparatie toegevoegd. Lees
`docs/development_log/2026-10-24-hc-meter-reporting.md`.
Ook de aircovermogensmeter gebruikt nu de bestaande actuele HA-template-uitlezing;
geen nulvulling of TTL-verruiming. HEMS ontvangt concrete foutredenen.
63 gerichte tests geslaagd. Nu zijn HEMS én HC gewijzigd; nog geen release/live-update.

## Dashboard vereenvoudigen - lokaal, 24 oktober 2026

Alex heeft na dev.317 de verwijdering van ongebruikte panelen/uitklapvelden en een
vergelijking direct bij de routekeuze bevestigd. Lees
`docs/development_log/2026-10-24-dashboard-attention.md`.
Reset bovenaan, concrete fouten, grafische vergelijking van canonieke aangeboden
routes en bestaande historie. Geen planner-/dispatchwijziging of nieuwe release.
De actuele live invoerfout is nog niet aan ED toegeschreven: nieuwe diagnose ontbreekt.

## Release HEMS dev.317 - 24 oktober 2026

Alex heeft publicatie van planvergelijking en samenhangende plan/SOC-publicatie aangevraagd.
Lees `docs/development_log/2026-10-24-plan-history-publication.md`.
Twintig recente opgeslagen plannen zijn alleen-lezen te vergelijken. De actuele serverweergave
staat klaar voor de nieuwe-planmelding; financieel rekenwerk volgt via de bestaande overlay.
Plannerbeleid, kleine stand-bywisselingen en HC dev.23 blijven gelijk.
Publicatie via PR en CI; installatie volgt afzonderlijk. Geen planreset nodig voor deze update.

## Release HEMS dev.316 - 24 oktober 2026

Alex heeft publicatie van de gecombineerde nacht-NOM/dashboardreparatie aangevraagd.
Lees `docs/development_log/2026-10-24-night-nom-live-status-repair.md`.
Vrijgegeven bridge-blokken volgen dezelfde PV-overschotcontrole als hoofdlaadblokken.
Een uitsluitend lezende modusobserver maakt de actuele dashboardstatus onafhankelijk
van plannerlooptijd; stand-by heeft een eigen legenda. Geen wijziging van dagdoelen,
lopende-laadbescherming of HC dev.23. Publicatie via PR en CI; installatie volgt apart.
Na installatie Planning opnieuw berekenen voor reeds opgeslagen foutief nacht-NOM.

# PicoT HEMS — mandatory session start

## Aanvullend laden op noodzaak - HEMS dev.308, 19 oktober 2026

Alex heeft controle en release aangevraagd. Lees
`docs/architecture/ADR-037.25-conditional-supplemental-charge-necessity.md` en
`docs/development_log/2026-10-19-conditional-supplemental-charge.md`.
Toekomstige aanvullende opdrachten mogen via de canonieke keten vervallen als
de volledige vervangende route hun overbrugging niet meer nodig heeft. Geen
anonieme netlaadrestanten; marktexport, dagdoelen en lopend laden blijven beschermd.
84 gerichte tests en de gereconstrueerde diagnose-replay slagen. Publicatie via
PR en CI; installatie en liveverificatie volgen afzonderlijk.

## EV-eindtijdadvies — HEMS dev.300 / Energy Devices dev.7, 17 oktober 2026

Alex heeft release aangevraagd. Lees
`docs/architecture/decisions/V2ADR-064.5-ev-deadline-advice.md` en
`docs/development_log/2026-10-17-ev-deadline-advice.md`.
Afzonderlijke duurzame adviesaanvraag; HEMS vergelijkt begrensde aaneengesloten
laadblokken met canonieke simulatie, tariefafrekening en Evaluation. Het bestaande
batterijplan en de batterijvoorraad blijven beschermd. Geen automatische EV-
uitvoering en geen parallelle tariefberekening in Energy Devices. 70 lokale
tests en statische controles slagen; publicatie via PR en CI. Installatie en
livecontrole volgen afzonderlijk.

## Stabiel lopend hoofd-netladen - release dev.286, 6 oktober 2026

Alex heeft de eerste reparatie om 18:38 Europe/Amsterdam bevestigd. Lees
`docs/architecture/ADR-037.23-stable-running-charge-and-minimum-improvement.md`
en `docs/development_log/2026-10-06-charge-continuity.md`. Basis dev.285 / main
158c61b; lokale branch fix/charge-continuity. Lopende hoofd-netlaadblokken
blijven beschermd tot hun einde of werkelijk 100%. Optionele vervanging vraagt
minstens EUR 0.01 expliciet voordeel. Noodzakelijk herstel blijft mogelijk.
Exacte invoerreplay voorkomt alle drie reductietriggers van 6 oktober.
Alex heeft release dev.286 aangevraagd. IMPLEMENTED; PR/CI volgt voor merge.
Installatie en livecontrole volgen afzonderlijk. BMS-afbouw volgt apart.

## Begrensde marktexportmeting — release dev.285, 4 oktober 2026

Alex heeft de gerichte reparatie en release via PR en CI aangevraagd.
Lees `docs/architecture/ADR-019.10-bounded-market-export-measurement.md` en
`docs/development_log/2026-10-04-market-export-measurement.md`.
Uitvoeringsbewaking verwerkt herstelde meetgaten <=2 seconden met maximaal
5 Wh gezamenlijke onzekerheid. Gemeten en geschatte export blijven gescheiden;
de bovengrens telt voor het budget. Planner, marktselectie en EV-aansturing gelijk.
75 lokale tests, Ruff, mypy en de exacte diagnosemeting slagen.
CI en livewerking zijn nog niet bevestigd; installatie volgt na publicatie.

## Doorlopende kalenderhistorie huisverbruik — release dev.284, 3 oktober 2026

Alex heeft automatische registratie naast de huidige methode aangevraagd, met
bestaande historie en vergelijking van maandag t/m zondag en werkdagen/weekenden.
Lees `docs/architecture/ADR-037.22-passive-household-calendar-history.md` en
`docs/development_log/2026-10-03-household-calendar-history.md`. Branch
`feat/household-calendar-history` vanaf main `3c6aff4` / HEMS dev.283.
Afzonderlijk begrensd proces, standaard actief na installatie, hervatbare aanvulling,
meetdekking, diagnose-export en weergave onder Historie. De huidige planner en
Solcast blijven gelijk. 193 tests, Ruff en mypy (239 bestanden) geslaagd.
Alex heeft om 08:51 Europe/Amsterdam release dev.284 via PR en CI aangevraagd.
Installatie en NUC-belastingsbewijs volgen afzonderlijk.

Upload this file at the start of every PicoT development session together with
the latest development handoff.  Read both completely before diagnosing,
designing or changing code.

This file is a routing index and guardrail.  The linked Accepted ADR files are
the architectural authority.  Current code, tests, comments, diagnostics and
earlier assistant memory are evidence, but they do not redefine ownership.

## Instelbare Solcast-basis — release dev.283, 30 september 2026

Alex heeft lower, gemiddelde lower–central, central en upper aangevraagd.
Lees `docs/architecture/ADR-019.9-configurable-solcast-basis.md`. De standaard
blijft het huidige gemiddelde. Bronprognoses, dagdoelen en commitmentregels
blijven behouden. Alex heeft release dev.283 aangevraagd via PR en CI; central-failsafe blijft uitgesteld.

## Betaald marktherstel — release dev.282, 30 september 2026

Alex heeft release van uitsluitend de herstelfix aangevraagd via PR en CI.
Lees `docs/architecture/ADR-019.8-paid-recovery-surplus.md` en
`docs/development_log/2026-09-30-paid-market-recovery-surplus.md`. Eerste
markttoelating mag volledig betaald voorraadoverschot behouden nadat beide
projecties werkelijk 100% bereiken. Alle kosten tellen mee, overschotwaarde is
nul; bestaande revisievergelijkingen blijven strikt. De central-regel blijft
uitgesteld. Installatie en livecontrole volgen afzonderlijk.

## Marktroute na de hoofdlaadroute — release dev.281, 29 september 2026

Alex heeft het beperkte avondvenster en de eenmalige overgang voor nog niet
begonnen ochtendroutes goedgekeurd. Lees `docs/architecture/ADR-019.7-post-main-market-window.md`
en `docs/development_log/2026-09-29-post-main-market-window.md`. Werkbranch
`fix/market-after-main-charge` vanaf dev.280. Nieuwe handel hoort na de eigen
hoofdlaadroute tot middernacht, met bewezen herstel via de volgende dagopdracht.
Dagbudget, 100%-doelen en historie blijven behouden. Lokale verificatie is
afgerond; lees het log voor de brede run en 42 geslaagde afsluitende controles.
Alex heeft op 29 september expliciet release dev.281 aangevraagd via PR en CI.
Installatie en livecontrole volgen afzonderlijk.

## Expliciet opnieuw berekenen — release dev.280, 2026-09-29

Alex heeft om 23:48 Europe/Amsterdam reparatie van de bestaande resetknop
gevraagd. Lees `docs/development_log/2026-09-28-daily-plan-recalculation.md`.
De oude knop wiste alleen legacy-commitments en bereikte het opgeslagen native
dagplan niet. De knop vraagt nu expliciete dagelijkse herberekening aan via de
bestaande Monitor/MEP-keten. Dagidentiteiten, werkelijk behaalde doelen, andere
dagverplichtingen en historie blijven behouden. Het verzoek en de vervangende
planversie worden gezamenlijk afgehandeld in Plan Store. Werkbranch:
`fix/daily-plan-recalculation`, vanaf dev.279. Alex heeft op 29 september om
00:23 Europe/Amsterdam release dev.280 aangevraagd via PR en CI. Installatie en
livecontrole volgen afzonderlijk. Gebruik na installatie eenmalig **Planning
opnieuw berekenen** om een eerder opgeslagen plan expliciet te laten herzien.

## Begrensd MEP-herstel — release dev.279, 2026-09-28

Voor het latere, om 22:23 goedgekeurde lokale hersteltraject: lees eerst
`docs/development_log/2026-09-28-mep-recovery-boundaries.md` en
`docs/architecture/ADR-037.21-bounded-recovery-and-execution-continuity.md`.
Vijf bewezen grenzen zijn in de bestaande keten lokaal hersteld en gezamenlijk
geverifieerd: 1.869 tests geslaagd, één overgeslagen; typecontrole, onafhankelijke
review, diagnose-replay en herstartcontrole geslaagd. De oorspronkelijke code
reproduceert het opgenomen plan van 19:01 exact; het herstel behoudt de eerdere
route zonder extra nacht-NOM of exportgerichte standby. De werkbranch is
`fix/mep-recovery-boundaries`. Alex heeft om 23:04 Europe/Amsterdam afzonderlijk
release dev.279 aangevraagd via PR en CI. Installatie en livecontrole volgen
afzonderlijk.

## Dashboard bij grote marktroutevergelijking — lokaal, 2026-09-28

Alex heeft om 20:17 Europe/Amsterdam de gerichte dashboardfix goedgekeurd.
Lees `docs/development_log/2026-09-28-dashboard-market-payload.md` voor contract,
reproductie en verificatie. Gedeelde verliesvrije bewijsreeksen en één volledige
webvergelijking voorkomen de 8M-overschrijding. Bij te veel extra schermdetail
blijven het plan en de uitvoeringsstatus behouden, met een zichtbare beperking.
MEP, aansturing en financiële afleiding blijven gelijk. 832 tests geslaagd,
1 overgeslagen; beide echte planstatussen publiceren compleet. Alex heeft om
20:37 Europe/Amsterdam release dev.278 aangevraagd via PR en CI. Installatie
en livecontrole volgen afzonderlijk; dev.268 blijft de eerste terugvalbasis.

## Financiële kwartierbalans en nachtstatus — lokaal, 2026-09-27

Alex heeft om 20:43 Europe/Amsterdam de gerichte financiële reparatie bevestigd.
Lees `docs/architecture/ADR-037.20-financial-quarter-and-night-evidence.md` en
`docs/development_log/2026-09-27-financial-quarter-night.md`. De financiële
afleiding gebruikt volledige getroffen klokkwartieren en geregistreerde
dag/nachtstatus van `sun.sun`. MEP, voorraadkosten en ruwe metingen blijven gelijk.
De echte diagnose van vandaag levert lokaal 9 van 9 bedragen; oude zonstatussen
ontbreken in de ZIP en worden niet verzonnen. Dev.276 is door Alex live bevestigd.
Alex heeft om 21:00 Europe/Amsterdam akkoord gegeven op afzonderlijke publicatie
als dev.277 via PR en CI. Installatie en controle van de historische nachtbron
volgen afzonderlijk. Dev.268 blijft de eerste terugvalbasis.

## Daggebonden marktherstel — 2026-09-27

Alex koos voor wachten op bekende herstelprijzen vóór een nieuwe marktroute.
ADR-019.6 (`docs/architecture/ADR-019.6-daily-market-recovery.md`) preciseert
ADR-019.5 en vervangt de optionele toelating zonder herstelbewijs uit ADR-019.1.
Een herstelvraag van vandaag heropent geen export na het laden van morgen.
Fysieke vooruitblik en financiële herstelgrens zijn afzonderlijke grenzen.
Zie `docs/development_log/2026-09-27-market-day-recovery-contract.md` voor
de lokale wijziging, verificatie en grenzen. Dit is geen releaseverklaring.

Alex heeft op 27 september 2026 om 20:00 Europe/Amsterdam akkoord gegeven
op de vervolgstap. Publicatie als dev.276 verloopt via PR en CI. Installatie
en livecontrole volgen afzonderlijk; dev.268 blijft de eerste terugvalbasis.

## Actuele eerste terugvalbasis — 2026-09-23

Alex heeft **2.0.0-dev.268** aangewezen als eerste terugvalbasis:
`7e49bf9eff507e7f277f5007d400bac731b07f25`.
Dit is de uitgebrachte versie vóór de nieuwe terugval op netbalans bij ontbrekende
PV. De lokale, nog niet uitgebrachte wijzigingen horen niet bij deze basis.
Dit besluit vervangt oudere verwijzingen naar dev.254 als eerste terugvalbasis;
dev.254 blijft een historisch checkpoint. Overige stop- en terugvalafspraken
blijven ongewijzigd. Zie `docs/development_log/2026-09-23-missing-pv-net-balance.md`.

## Authority and reading order

1. `docs/rebuild/CANONICAL_PIPELINE_CONTRACT.md`
2. `docs/architecture/ADR-015-execution-primitives.md`
3. `docs/architecture/ADR-016-execution-plan-architecture.md`
4. `docs/architecture/ADR-017-planning-decision-pipeline.md`
5. `docs/architecture/ADR-023-opportunity-engine.md`
6. `docs/architecture/ADR-024-candidate-engine.md`
7. `docs/architecture/ADR-026-evaluation-engine.md`
8. `docs/architecture/ADR-027-execution-plan-commitment.md`
9. `docs/architecture/ADR-028-runtime-resource-governance.md`
10. `docs/architecture/ADR-030-energy-path-capability-snapshot-contract.md`
11. `docs/architecture/ADR-031-candidate-scenario-construction-contract.md`
12. `docs/architecture/ADR-032-candidate-evaluation-contract.md`
13. `docs/architecture/ADR-033-winning-energy-path-to-execution-plans.md`
14. `docs/architecture/ADR-034-runtime-monitor-material-change-replanning-contract.md`
15. `docs/architecture/ADR-035-home-assistant-adapter-contract.md`
16. `docs/architecture/ADR-036-price-opportunity-detection-contract.md`
17. `docs/architecture/ADR-037-household-energy-requirement-storage-reserve-grid-use.md`
18. `docs/rebuild/V2ADR-050-timed-delegated-storage-control.md`
19. `docs/rebuild/V2ADR-052-persistent-plan-commitment-and-material-replanning.md`
20. `docs/rebuild/V2ADR-055-mep-sole-canonical-planner.md`
21. `docs/architecture/decisions/V2ADR-057-measured-pv-charge-admission-and-visibility.md`
22. `docs/architecture/decisions/V2ADR-058-adaptive-market-commitments-and-execution-feedback.md`
23. `docs/architecture/decisions/V2ADR-059-financially-bounded-late-grid-fallback.md`
24. `docs/architecture/decisions/V2ADR-060-fast-vendor-mode-dispatch-failure-containment.md`
25. `docs/architecture/decisions/V2ADR-061-committed-segment-clock-boundary-execution.md`
26. `docs/architecture/decisions/V2ADR-062-material-replanning-and-commitment-comparison.md`
27. `docs/architecture/decisions/V2ADR-063-committed-trajectory-materiality-thresholds.md`

When two decisions appear inconsistent, do not silently choose one.  Identify
the controlling baseline and explicit superseding clause before changing code.

## Frozen canonical pipeline

```text
PlanningInputSnapshot
→ Opportunity Engine
→ OpportunitySet
→ MEP Candidate Generation and Simulation
→ CandidateSet + complete EnergyPaths
→ CandidateOutcomeSet
→ Evaluation Engine
→ Winning Candidate + Winning EnergyPath + EvaluationRecord
→ Execution Plan Builder
→ ExecutionPlanSet
→ Plan Store / commitment persistence
→ Execution Engine
→ ExecutionPrimitiveRequest
→ Device Adapter
→ Vendor Command and observed result
```

No stage may be replaced by a diagnostic projection, private planner result,
runtime shortcut or synthetic automatically winning record.

## Ownership boundaries

| Layer | Owns | Must not |
|---|---|---|
| Planning Input | Immutable current facts, evidence and versions | Plan, score or choose |
| Runtime Monitor | Classify producer-accepted material changes and request a fresh snapshot | Suppress observations, plan or modify plans |
| Opportunity Engine | Evidence-only opportunities and constraints | Select devices, assign power, build candidates or choose winners |
| MEP Candidate Generation | Complete physical candidates, Energy Paths and simulation outcomes | Select the winner, retain plans or dispatch |
| Evaluation Engine | Compare canonical outcomes and select exactly one winner | Generate candidates, build plans or choose vendor commands |
| Execution Plan Builder | Exact Winning Energy Path, including source policy, to scope-specific plans | Add, remove, merge or reinterpret actions |
| Plan Store | Persist one admitted plan and its revision per scope | Evaluate economics or invent replacements |
| Execution Engine | Due segment, live validation, retries and primitive requests | Re-rank, replace or economically redesign plans |
| Device Adapter | Primitive-to-vendor translation | Plan, evaluate or reinterpret strategy |
| Projection/UI | Present canonical records and lineage | Recalculate or become an authority |

## Commitment rules

- MEP does not choose the winner; canonical Evaluation does.
- A commitment never prevents creation of a fresh challenger after an accepted
  material change.
- Incumbent and challengers are complete remaining-horizon Energy Paths.
- They are evaluated from the same fresh snapshot and current physical state.
- Past cost and revenue are sunk; persisted outcomes are provenance only.
- Strictly better valid and executable wins.
- Equivalent or worse retains the incumbent.
- Physical infeasibility, reserve failure, Safety and hard constraints cannot
  be hidden by a financial switching margin.
- Ordinary progress is non-material; material SoC, household, PV, price,
  forecast, capability or execution changes remain observable.
- Clock-boundary execution and material replanning are independent signals.

## Mandatory change contract

Before editing, state:

1. observed problem and first bad canonical boundary;
2. controlling ADRs;
3. responsible layer;
4. layers explicitly out of scope;
5. invariant to preserve;
6. regression evidence required;
7. rollback boundary.

If implementation requires changing an out-of-scope layer or contradicting an
Accepted ADR, stop and revise the contract or write an explicit superseding ADR
before continuing.

## Mandatory implementation rules

- Fix defects in the owning layer; never compensate in a downstream layer.
- Do not build a parallel pipeline, planner, evaluator, commitment path or
  dispatch path.
- Do not use current code structure as proof of architectural ownership.
- Do not let an adapter, projection or live runtime invent planning policy.
- Do not accept an empty canonical outcome set for evaluated candidates.
- Do not construct an `EvaluationRecord` around a winner selected before the
  canonical CandidateSet and CandidateOutcomeSet exist.
- Do not hand-build live Execution Plans outside the canonical Plan Builder.
- Do not suppress canonical input before the Runtime Monitor can classify it.
- Add diagnostics before policy when the first bad boundary is not proven.
- Keep each PR to one architectural boundary and one observable result.

## Required verification

Every functional slice needs:

- a regression replay that fails for the original defect;
- focused unit or contract evidence at the owning boundary;
- canonical lineage assertions across adjacent stages;
- architecture ownership checks;
- relevant golden end-to-end scenarios;
- Ruff, mypy and the affected pytest suites;
- explicit confirmation of unchanged out-of-scope behavior;
- live verification only after local and CI evidence passes.

Green CI alone is not architectural proof.  Diagnostics must show the same
canonical identities and records across the full affected chain.

## Current recovery checkpoint — 2026-08-31

Audit of pre-recovery `main` commit
`808c4cf0b81556c8095c228f8bbeb44a43b5084e` identified these repair targets:

Completed and merged through PR #575:

1. live observations reach general Runtime Monitor material classification;
2. MEP emits a complete CandidateSet and non-empty CandidateOutcomeSet before
   ADR-032 Evaluation selects a winner;
3. incumbents and challengers use one fresh snapshot and comparison horizon;
4. equivalent/worse retains the incumbent, invalid loses, and persisted
   financial results are provenance only;
5. diagnostics expose comparable incumbent/challenger outcomes.
6. the Winning Energy Path passes exclusively through the canonical ADR-033
   Execution Plan Builder; source policy and all segment intent are preserved.

The identified recovery checkpoint is merged on `main` as commit
`6e99c82f477fdb31ea613ab23652f9ea7ec99a08`; all three GitHub CI workflows
passed.  Releases dev.207 and dev.208 exposed and dev.209 repaired add-on
packaging and executable ownership defects.  Live dev.209 then proved two
functional defects: MEP used the full horizon when ADR-037 required earlier
storage recovery for projected household demand, and a persisted lifecycle
could expose a future top-level start despite a currently due first segment.

Live `2.0.0-dev.210` exposed that MEP derived the ADR-037 household requirement
deadline but did not publish the canonical projected balance or
`StorageEnergyRequirement`.  Consequently a persisted plan that reached the
target only after the fresh deadline remained valid and commitment could retain
it.  Native and committed paths also omitted the wear adjustment already used
by market-route outcomes, making equal paths financially asymmetric.

Release `2.0.0-dev.211` was merged and installed live.  Its diagnostics proved
that the published 100% record combined two different ADR-037 facts: the daily
maximum storage target and the independently simulated household reserve.  A
market route may reach the daily target before export and later use energy,
provided its complete projected path still respects the household reserve.

Release `2.0.0-dev.212` was merged and installed live.  The existing 100%
record is now explicitly typed as a `daily_storage_target` with `reached_by`
semantics.
Every MEP Candidate Outcome separately publishes the conservative target
completion time and whether household reserve remains respected across all PV
scenarios.  Candidate Generation and simulation still derive both facts;
ADR-032 Evaluation only consumes their validity and objective outcomes.  The
configured micro-charge suppression remains unchanged.  Confidence-dependent
reserve enlargement is not invented in this slice because the live Planning
Input does not yet contain the canonical relative-confidence baseline required
by the existing ADR-037 reserve policy.  The flat household dashboard line and
financial source-label ambiguity remain separate UI slices.

Live dev.212 then proved that the price-chart SoC line was not a projection of
the Winning Energy Path.  Projection/UI privately re-simulated Execution Plan
segments at their requested maximum power and ignored canonical market-route
storage checkpoints and per-interval export targets.  Dev.213 restores
ADR-030 ownership: native and market Candidate Energy Paths publish central
scenario Projected Energy States, and the UI renders only those immutable
states plus the actual starting SoC.  Hybrid NOM/PV plus residual-grid
Candidate construction remains a separate MEP Candidate Generation slice.


## 2026-09-09 — historical SOC recovery and market volume alignment

Accepted supplement: `docs/architecture/ADR-037.11-historical-main-completion-recovery.md`.
A raw 100% HA Recorder observation inside a then-valid admitted main window can
recover missed completion without claiming vendor execution by PicoT. The old
revision, actual timestamp and evidence remain durable; current identity is kept.
Only Candidate Generation / Evaluation / Plan Builder reconcile remaining actions.
The execution boundary refuses stale historically completed main segments until
reconciliation. Manual override is unchanged. Market capacity and final simulation
must use the same tariff/household boundaries; never relax volume validity to hide
an interval mismatch. See the development log for implementation/test status.

## 2026-09-11 — Passive grid-charge review and actual SOC

See `docs/architecture/ADR-037.13-passive-grid-charge-review.md`. This optional
observer estimates retrospective grid reduction without planning authority.
It must never feed MEP or replace the original canonical SOC projection.
Runtime/UI additions are locally implemented; no new release or live validation.

## 2026-09-12 — Pre-stable en begrensde proef verbruiksprognose

Lees `docs/architecture/ADR-037.14-clock-quarter-load-forecast.md` en
`docs/development_log/2026-09-12-clock-quarter-trial.md`.
Vaste terugvalbasis: dev.254 / `21314d87be70442d9643d75ee74e7beb3be97e89`.
Slechter gedrag: direct terug. Niet slechter: hoogstens één kleine optimalisatie;
bij daarna ongewenst gedrag terug naar pre-stable en opnieuw ontwerpen.

## 2026-09-12 — Bescherming bij lopende huisbelasting

Lees `docs/architecture/ADR-037.15-ongoing-household-load-protection.md` en
`docs/development_log/2026-09-12-load-protection-implementation.md`.
Extra huisvraag wordt tijdelijk meegenomen; lopend netladen wordt beschermd.
De kleine-tekortmarge vereist een strikt haalbare herstelproef binnen het bestaande
hoofdvenster. Werkelijk 100% blijft verplicht. Implementatie lokaal, nog geen release.
Dev.254 blijft de vaste terugvalbasis; werkdag/weekendweging is buiten scope.

## 2026-09-14 — Auditcorrecties, lokaal en nog niet uitgebracht

Lees `docs/development_log/2026-09-14-audit-repair.md` en
`docs/development_log/2026-09-14-diagnostic-evidence-repair.md`.
Monitor-vrijgave en native dagobservaties vormen één samenhangende wijziging;
klokuitvoering blijft onafhankelijk. SOC-bronidentiteit, uitvoeringsconstraints,
foutterugkoppeling en diagnostische herleidbaarheid zijn lokaal gecorrigeerd.
Punt 8 (volwaardige incumbentvergelijking) was aanvankelijk open wegens de expliciete
botsing tussen gelijkwaardig-behouden en ADR-037.12-netlaadvermindering;
het onderstaande besluit en vervolglog lossen dit op.
Geen stilzwijgende nieuwe rangschikregel, release of livewijziging. De bestaande
pre-stable terugvalafspraak blijft gelden. Zie het log voor verificatieresultaten.

### Punt 8 — expliciet besluit over netlaadduur

Alex heeft de gelijkspelregel bevestigd; zie
`docs/architecture/ADR-037.16-netlaadduur-bij-gelijkwaardige-plannen.md`.
Implementatie en verificatie: `docs/development_log/2026-09-14-grid-duration-comparison.md`.
Bij gelijke beschikbare financiële uitkomsten wint minder resterende netlaadduur
vóór lagere strategieprioriteiten en incumbentbehoud. PV/NOM-laadduur telt niet mee.
Geen nieuwe herplantrigger of versoepeling van dagdoel/reserve/belastingbescherming.

## 2026-09-14 — Afronding en release dev.260

Alex heeft de resterende punten inclusief de gezamenlijke release laten oppakken.
Lees `docs/development_log/2026-09-14-ha-followup.md` voor de vijf Gielz-templates,
recorderbeperkingen en livecontrole. Externe HA-YAML ontbreekt nog; snippets zijn
geen uitgevoerde reparatie van die automatisering. Geen databasegegevens wissen.
De codewijzigingen gaan via PR en CI naar main; installatie/livebewijs volgt apart.

## 2026-09-15 — Schakelhistorie, NOM-continuïteit en SOC-verwachting

Lees `docs/development_log/2026-09-15-observation-fixes.md` en
`docs/architecture/decisions/V2ADR-066-soc-display-expectation-history.md`.
Een vrijgekomen eigen netlaadsegment blijft NOM in de revisiekandidaat;
incumbent, Evaluation en uitvoeringsautoriteit blijven ongewijzigd.
Klokschakelingen verversen hun webhistorie onafhankelijk van herplanning.
De SOC-grafiek bewaart verstreken voorspellingen; de bestaande simulator levert
vanaf actuele SOC een verse verwachting voor het geldende plan, ook bij behoud.
Dit is weergavebewijs en kan geen plan of herplantrigger wijzigen.
Geen actuele invoer betekent geen actuele toekomstige prognose.
De wijzigingen zijn lokaal geverifieerd. Alex heeft release dev.261 aangevraagd;
publicatie via PR en CI. Installatie en livevalidatie volgen daarna.

## 2026-09-17 — HEMS dev.262: meetbewijs voor nacontrole

Alex heeft release van de afzonderlijke meetregistratie/nacontrole aangevraagd.
Begrensde, incrementele HA-history reads; gzip-archief van vandaag/gisteren in de
ZIP-diagnose; meetonderbrekingen per bron en tijdvak in UI en diagnose.
Geen ontbrekende data aangevuld en geen MEP-/commitment-/aansturingswijzigingen.
Bronuitval blijft een blokkade; 17 september bevat een echte SOC-onderbreking van
1,008294 seconde rond 09:31. Zie development_log/2026-09-17-review-measurement-evidence.md.

## 2026-09-17 — HEMS dev.263: aparte kwartierbalans

Alex heeft release aangevraagd van de observer-only kwartierintegratie.
De vermogensreeksen leveren afzonderlijk geïntegreerde Wh over gelijke kwartieren.
Afgeleid huisverbruik blijft gescheiden van ruwe metingen en de strikte replay;
geen nulvulling of nieuwe MEP-inputs. Op export 19:43: 74 afgeleide tijdvakken,
vijf ongeldig. Geen bewijs dat de volledige 1,7 kWh netladen vermijdbaar was.
Details: docs/development_log/2026-09-17-review-quarter-alignment.md.

## 2026-09-19 — geïntegreerde passieve historie, lokaal en standaard uit

Lees `docs/development_log/2026-09-19-passive-history-implementation.md`.
Alex heeft na de gezamenlijke ontwerpen en offline proeven de geïntegreerde
implementatiestap bevestigd. `picot.v2.passive_history` bevat opname, bewijsindex,
compacte records/revisies, kalender, diagnose-import en een begrensde worker.
De incidentregistratie heeft een optionele pre-reductiecallback; geen live callsite
of workerinitialisatie toegevoegd. Planner, MEP, Plan Store, uitvoering en
bestaande financiële/prognose-inputs blijven ongewijzigd. Geen release of live
activatie. Automatische afschaling, volledige dependencycertificering en
NUC-belasting blijven vóór activering te beoordelen. Geen oude bestanden wissen.

Vervolg 19 september: `passive_history.retention` biedt nu een alleen-lezen
bewaaroverzicht met bronsnapshottoken en een afzonderlijke offline vergelijkkopie.
Alleen bewezen dagaggregaten mogen daarin oudere overige kwartiergetallen
vervangen; huisverbruik, kwartierprijzen en kwaliteits-/herkomstinformatie blijven
behouden. Revisietwijfel, open dagen, onbekende meetsoorten en de vijfjaarsgrens
betekenen behoud/beoordeling. De kopie wordt geweigerd als actieve HistoryStore.
Geen bronverwijdering, automatische vervanging, live-aansluiting of release.
Lees de vervolgsectie in bovengenoemd ontwikkellog voor grenzen en proefbewijs.

Gericht herstel na uitvaltoets: tijdelijke I/O-uitval krijgt `source_unavailable`,
corruptie blijft `invalid_record`. Alleen expliciet geselecteerde digests kunnen
begrensd opnieuw worden ingepland (`worker --recheck-digest SHA256`, maximaal 16,
totale pending-wachtrij 64). Geen automatische retry na herstart/herontdekking.
Pogingen en observaties blijven bewaard; volledige replay wordt niet opgewaardeerd.
Zie ontwikkellog voor regressiebewijs. Nog geen live-aansluiting of release.

Voorbereiding eerste NUC-proef: lees
`docs/development_log/2026-09-19-passive-history-nuc-probe.md`.
`tools/passive_history_probe.py` meet een kleine synthetische belasting in eigen
kindprocessen/tijdelijke opslag: baseline, opname en indexverwerking. Lokaal getest;
niet op de NUC uitgevoerd. Geen installatie of aansluiting op dev.263. Eerst de
beschikbare afzonderlijke NUC-proefomgeving vaststellen; geen HA-instellingen wijzigen.

Terminal & SSH heeft volgens Alex geen `python3`. Daarom is met zijn akkoord
`picot_history_probe/` als afzonderlijke tijdelijke HA-testapp voorbereid:
handmatig/eenzelfde eenmalige proef, eigen `/data`, geen API-/hosttoegang of gedeelde
PicoT-bestanden. Bronnen zijn meegeleverd met hashcontrole. Nog niet gepubliceerd,
gebouwd met Docker of op de NUC geïnstalleerd; dev.263 hoeft niet te wijzigen.
Zie README/DOCS in die appmap en het NUC-proeflog voor de concrete grenzen.

Publicatie afgerond: PR #659, merge `27ec942abd3b7955eaa69ac43096f1fe2c5c2a50`.
Uitsluitend `picot_history_probe/` en eigen CI-workflow gepubliceerd (18 nieuwe
bestanden, geen bestaande wijzigingen); HEMS blijft dev.263. Containerproef,
686 v2-tests en 1.618 PR-tests geslaagd; pushchecks eveneens groen. Testapp 0.1.0
kan na appwinkelverversing worden geïnstalleerd en één keer handmatig gestart.
Nog geen NUC-resultaat. Overige lokale historiewijzigingen zijn niet gepubliceerd.

Eerste NUC-proef ontvangen: `workload_complete=true`, 4/4 gepubliceerd en verwerkt,
geen achterstand of integriteitsfout. Bronhashes passen bij testapp 0.1.0.
Opnametijd aanbod maximaal 0,060 ms; p95 controletik baseline/opname 0,279/0,271 ms;
opnameproces piek-RSS 20,23 MiB. Dit is uitsluitend een kleine synthetische proef,
geen bewijs over plannerlatentie of grote snapshots. Zie NUC-proeflog voor exact
bewijs en beperkingen. Nog geen actieve historieaansluiting of nieuwe HEMS-release.

Testapp 0.2.0 gepubliceerd via PR #660, merge
`a1f00bfe9111b6b0e05b2a349352f723751a1e91`. Grotere synthetische records
1/2/4/8 MiB met aantoonbare overlap van publicatie en indexwerk. Alleen testapp en
CI gewijzigd, HEMS blijft dev.263. Vier pakkettests, containerproef en alle
projectchecks geslaagd. Lokale/CI-tikvertraging kende uitschieters circa 5/21 ms;
geen plannergoedkeuring afleiden. Wacht op Alex' NUC-log van 0.2.0 na handmatige start.

Tweede NUC-log ontvangen: functioneel 4/4 en 0,641 s overlap, maar upload bevat
alleen de laatste 100 regels. Baseline en heartbeatmetingen ontbreken. Piek-RSS
50,11 MiB per gerapporteerd proces; maximaal aanbod 0,064 ms. Nog geen oordeel
over vertraging. Vraag bestaande logs met 300 regels op; proef niet opnieuw starten.

## 2026-09-19 — runtime-opnameproef, lokaal en standaard uit

Lees `docs/development_log/2026-09-19-history-capture-runtime-trial.md`.
Het complete NUC-log bevat twee geslaagde grote proeven inclusief tikmetingen;
de eerdere ontbrekende-baselineblokkade is opgeheven. Dit certificeert geen planner.
Alex heeft de optionele opnameaansluiting bevestigd. De lokale HEMS-optie
`history_capture_trial_enabled` staat standaard false. Alleen capture wordt
verbonden, met 30 minuten aanbiedvenster, begrensde wachtrij/eigen opslag en
stoppen bij een publicatiefout. Geen indexworker of verwijdering in de runtime.
Nieuwe logregels meten ook de uitgeschakelde baseline. Planner/MEP/commitmentbeleid
blijven gelijk. Geen release of NUC-optiewijziging uitgevoerd; dev.263 blijft live.

Releasevoorbereiding na Alex' akkoord: dev.264 op een aparte branch vanaf
`a1f00bfe9111b6b0e05b2a349352f723751a1e91`. Optie blijft false; eerst 30 minuten
baseline op de NUC. De opnameproef start pas na expliciet inschakelen/herstarten.
Geen plannerwijziging of automatische verwijdering. Publicatiestatus volgt in het
ontwikkellog van de runtimeproef; de eerdere lokale statusregels zijn historisch.

## Dev.265 — trial diagnostic export

See `docs/development_log/2026-09-20-history-trial-export.md` for the bounded
read-only export and completed dev.264 trial. Keep capture false during update
and download. The three actual NUC objects still require offline verification.

## 20 september — tijdnotatie voor replay, lokaal

Lees `docs/development_log/2026-09-20-history-time-offset.md`. De echte proefrecords
zijn geverifieerd; de oorspronkelijke beslissing is inclusief ID’s gereproduceerd.
Recordopslag bewaart nu bronoffsets, terwijl fingerprints UTC blijven gebruiken.
65 gerichte tests en de echte opslag/replayproef slagen; Ruff en mypy groen.
Branch `fix/history-preserve-time-offset`, nog geen publicatie of livewijziging.

Releasevoorbereiding na Alex’ akkoord: dev.266 via PR en CI. Opname blijft
standaard false; installatie en livecontrole volgen afzonderlijk.

## 20 september — standby-adapterherstel, lokaal

Lees `docs/development_log/2026-09-20-adapter-standby.md`.
De bestaande standby-koppeling werd door de HA-adapter geweigerd. Eén toegevoegde
primitive herstelt de vertaling; planner en runtime zijn ongewijzigd. 63 gerichte
tests, Ruff, mypy en tien offline diagnosegrenzen slagen. Branch
`fix/adapter-standby`. Alex heeft release dev.267 aangevraagd; publicatie via
PR en CI, installatie en liveverificatie volgen afzonderlijk.

## 21 september — bewijs van afgewezen huisverbruik, lokaal

Lees `docs/development_log/2026-09-21-household-rejection-evidence.md`.
Branch `fix/household-rejection-evidence` vanaf dev.267. Afwijsredenen ontstaan in
Planning Input en gaan met bronwaarden/brontijden naar een aparte begrensde
registratie en diagnose-export. Geen wijzigingen aan geldige waarden, MEP of
kwartierbalans; 240 vergelijkingen met dev.267 geven dezelfde observaties.
76 gerichte tests, Ruff en mypy geslaagd. Nog niet gepubliceerd of live getest.

Releasevoorbereiding na Alex’ akkoord: dev.268 via PR en CI. De aparte
afwijsregistratie werkt zonder inschakelen van de snapshotproef. Installatie en
nieuwe diagnose moeten de livewerking nog aantonen.

## 2026-09-23 — Release dev.269: netbalans bij ontbrekende PV

Lees `docs/architecture/ADR-037.17-missing-pv-net-balance-review.md` en
`docs/development_log/2026-09-23-missing-pv-net-balance.md`. Alex heeft release
aangevraagd. De onafhankelijke vijfminuten-netbalans kan bij ontbrekende PV een
bestaande hoofdrouteherziening openen. Dagdoel, reserve, actieve belastingbescherming
en canonieke selectie blijven gelden; ontbrekende PV wordt niet ingevuld.
Dev.268 is expliciet de eerste terugvalbasis. Publicatie via PR en CI;
installatie en liveverificatie volgen afzonderlijk.

## 2026-09-24 — lokaal crashherstel overbrugging samengesteld plan

Lees `docs/development_log/2026-09-24-shared-plan-bridge-owner.md`.
De overbruggingscontrole volgt bij markt-/laadplannen de bewaarde laadherkomst;
geen directe plan-ID-gelijkheid veronderstellen. Ontbrekende herkomst geeft een
gecontroleerde fout. Laadbeleid, marktroute en opslag blijven gelijk.
Alex heeft release dev.270 aangevraagd; publicatie via PR en CI. Installatie
en liveverificatie volgen afzonderlijk. Dev.268 blijft de afgesproken terugvalbasis.

## 2026-09-26 — besloten financiële herziening marktroute

Lees `docs/architecture/ADR-019.5-financial-market-revision.md`.
Alex heeft het wijzigingsvoorstel bevestigd: behoud, inkorten en verwijderen
zichtbaar vergelijken over de resterende uren van vandaag en morgen, met eerlijke
eindvoorraad en behoud van laadverplichtingen. Het absolute exportbehoud wordt
vervangen door canonieke financiële selectie; opslag controleert de verwerking.
Het oorspronkelijke incident en het voorafgaande overleg staan in
`docs/development_log/2026-09-26-bridge-export-intent.md`.

De technische uitvoeringsvolgorde en acceptatiegevallen staan in
`docs/development_log/2026-09-26-market-revision-implementation-plan.md`.
Alex gaf om 19:55 akkoord op uitvoering. De implementatie is nu lokaal aanwezig;
lees `docs/development_log/2026-09-26-market-revision-implementation.md` voor
gedrag, verse verificatie, replays en beperkingen. Alex heeft om 20:50 akkoord
gegeven op afzonderlijke release dev.271 via PR en CI. Installatie en livebewijs
volgen daarna; het schakelpunt van 15:25–15:31 wordt vervolgens afzonderlijk
onderzocht. Dev.268 blijft de operationele terugvalbasis.

### Vervolg — fix 2 na akkoord om 21:34

Dev.271 is gepubliceerd via PR #668, merge
`b5920fc046858fa07aaf2edaa91fb4c6160f1bad`. Alex meldt weer een actief plan;
volledig nieuw live-diagnosebewijs is nog niet ontvangen.

Het schakelonderzoek staat in
`docs/development_log/2026-09-26-switching-investigation.md`.
De goedgekeurde beperkte reparatie is lokaal geïmplementeerd; lees
`docs/development_log/2026-09-26-charge-continuity-implementation.md` voor
kandidaatcontinuïteit, uitvoeringsreden, replays en verificatiestatus. Alex heeft
om 21:50 akkoord gegeven op afzonderlijke publicatie als dev.272 via PR en
automatische controles. Installatie en liveverificatie volgen afzonderlijk.
Het financiële tabblad is daarna een
afzonderlijk herstelpunt, vastgelegd in
`docs/development_log/2026-09-26-financial-tab-triage.md`.

### Vervolg — fix 3 na akkoord om 22:15

Dev.272 is gepubliceerd via PR #669, merge
`565150bdfe8caa0d9ebde512fcaad518d2843e64`. De diagnose van 22:09 bevestigt
deze versie met een behouden actief plan om 22:07. Dit bewijst nog geen nieuwe
belastingsproef van de herstelde laadcontinuïteit.

Alex heeft de financiële herstelgrens bevestigd. Lees
`docs/architecture/ADR-037.18-financial-result-availability.md` en
`docs/development_log/2026-09-26-financial-availability.md`. Bedragen krijgen
afzonderlijke meetdekking; historie en bestaande totalen blijven zichtbaar.
De bestaande numerieke historie en voorraadkosten voor planning blijven gelijk.
Lokaal geïmplementeerd en geverifieerd. Alex heeft om 22:39 akkoord gegeven op
afzonderlijke publicatie als dev.273 via PR en automatische controles.
Installatie en livecontrole van het financiële tabblad volgen daarna.

### Vervolg — financiële afleiding na akkoord om 23:23

Dev.273 is gepubliceerd via PR #670, merge
`1feaa9b049222fdf25bb9efdfbb2974c006ad369`. Alex bevestigt installatie; de
diagnose van 23:16 toont deze versie met een behouden actief plan om 23:05.
De resterende ontbrekende financiële waarden volgen uit nachtelijke PV en korte
brononderbrekingen. Lees
`docs/architecture/ADR-037.19-financial-measurement-inference.md` en
`docs/development_log/2026-09-26-financial-measurement-inference.md`.

De goedgekeurde afleiding is lokaal geïmplementeerd op
`fix/financial-measurement-inference`: nachtbewijs, begrensde korte gaten,
afgeleid huisverbruik en herkenbare financiële kwaliteit. Oorspronkelijke
dagvelden, voorraad, strikte terugblik en planning blijven gelijk. Het oude
archief bevat geen zonhistorie: volledige historische nachtresultaten zijn
daarmee nog niet geverifieerd. Geen nieuwe release, commit, push of livewijziging;
eerst de lokale uitkomst bespreken.


Releasevoorbereiding: Alex heeft op 27 september 2026 om 00:23
Europe/Amsterdam akkoord gegeven op publicatie als dev.274 via PR en CI.
Dit vervangt de eerdere lokale publicatiestatus; installatie en livecontrole
volgen na geslaagde publicatie afzonderlijk.


Release dev.275: Alex heeft op 27 september 2026 om 16:13 Europe/Amsterdam
akkoord gegeven op publicatie van de geïsoleerde planovergangenreparatie via PR
en CI. Zie `docs/development_log/2026-09-27-retained-plan-boundaries.md`.
Financiële meetverwerking, planuitleg en NOM-vervanging blijven vervolgstappen.
Installatie en livecontrole volgen na publicatie.
