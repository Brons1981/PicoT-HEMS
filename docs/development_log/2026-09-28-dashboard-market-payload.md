# Dashboard bij grote marktroutevergelijking

Alex gaf op 28 september 2026 om 20:17 Europe/Amsterdam akkoord op deze fix.
Basis: dev.277, `0ae60a8d488dd7a1f9f4a7f28b189d7137efe630`.
Branch: `fix/dashboard-market-payload`. Publicatie en installatie zijn afzonderlijk.

## Wijzigingscontract

- Eerste verkeerde grens: Projection/UI publiceert herhaalde lange bewijsreeksen
  per alternatief. WebViewStore vervangt bij meer dan 8.000.000 tekens de gehele
  weergave door `view_too_large`, inclusief een beschikbaar canoniek plan.
- Autoriteit: canoniek pipelinecontract, ADR-019.5 (alternatieven en verschillen
  tonen), ADR-028 (begrensd en gecontroleerd afschalen) en V2ADR-055 (ontbrekend
  optioneel detail mag een beschikbaar MEP-plan niet verbergen).
- Eigenaar: presentatie en serialisatie. Deel bestaande verliesvrije codering van
  bewijsreeksen met de diagnoseregistratie; het diagnoseformaat blijft gelijk.
- Buiten scope: MEP, kandidaatgeneratie, Evaluation, Plan Store, aansturing,
  meetverwerking en financiële afleiding. Geen aanpassing van de 8M-grens.
- Invariant: canonieke kandidaten, bedragen, redenen, winnaar, planidentiteiten,
  segmenten en live/observer-status blijven gelijk; bronrecords blijven intact.
- Regressiebewijs: grote vergelijkingen inclusief verliesvrije bewijsresolutie;
  behoud van huidig plan en uitvoeringsstatus bij te veel schermdetail; zichtbare
  beperking, vervolgupdates en herstel; dezelfde diagnose vóór/na projecteren.
- Terugvalgrens: deze presentatiepatch terugnemen zonder plan-/gegevensmigratie.
  De eerder afgesproken operationele eerste terugvalbasis blijft dev.268.

## Oorspronkelijk bewijs

ZIP `picot-diagnostics-2026-09-28T200423.940.zip`, SHA-256
`23641eaf0beb0fa800abe03e21322db90a660b6954aa7a9803cc07269f62d41e`.
19:01:53: 1.393 alternatieven; plandeel 10.903.803 tekens.
19:04:36: 1.338 alternatieven; plandeel 10.474.935 tekens, waarvan de
bewijsverwijzingen in de vergelijking 8.690.447 tekens. Alleen dit plandeel
aan de ongewijzigde WebViewStore aanbieden reproduceert een foutobject van
93 tekens zonder planning. Dit is een projectiereplay, geen nieuwe planberekening.

De tijdelijke SOC-uitval om 18:35 en het herstel om 18:36:39 zijn een afzonderlijke
gebeurtenis. De financiële meetgaten worden met deze fix niet ingevuld.

## Implementatie

- `EvidenceSequenceEncoder` bevat de bestaande codering uit incidentregistratie:
  één ruwe basisreeks, gedeelde prefix/suffix en het afwijkende middendeel.
  De UI-vergelijking gebruikt `evidence_ids_ref` en een gedeelde dictionary met
  expliciet formaat `prefix-middle-suffix:v1`. Geen bron-ID of volgorde gaat verloren.
  Financiële rijen, aantallen, keuzes en afwijsredenen blijven volledig aanwezig.
- De technische evaluatiekaart in het webantwoord verwijst naar de volledige
  vergelijking onder `planning_status`, met dezelfde identiteit en het aantal
  alternatieven. De volledige vergelijking staat daardoor eenmaal in het antwoord.
  De zelfstandige HA-projectie behoudt de vergelijking en haar bestaande transportgrens.
- WebViewStore reserveert bij te veel data eerst ruimte voor plan, segmenten,
  beslissing, uitvoeringsstatus en technische herkomst/status. Kleinere optionele
  secties worden daarna toegelaten binnen dezelfde 8M-grens. Te groot detail
  verdwijnt met expliciete vermelding; de UI toont een Nederlandse melding.
  Vervolgupdates behouden die melding zolang eerder weggelaten detail ontbreekt.
  Een nieuw volledig schermantwoord herstelt de normale weergave.
- De bestaande uiterste harde begrenzing blijft voor een invoer waarvan zelfs
  de essentiële kern niet binnen het budget past. De regressie met een kunstmatig
  budget van 200 tekens blijft bestaan. Bij de canonieke plannen in de regressies
  en diagnose wordt deze noodgrens niet bereikt; omvangrijk optioneel detail wist
  hun plan niet meer.

## Verse verificatie

- Voor de productieaanpassing faalden drie regressies op dev.277 door het
  verdwijnen van `planning_status`/`observer_only`. De definitieve vijf regressies
  slagen: 1.393 en 4.007 alternatieven; verliesvrije bewijsresolutie en behoud van
  alle uitkomsten; een werkelijk door MEP gebouwd plan onder schermdruk in live-
  en observerweergave; financiële vervolgupdate, herstel en de JavaScript-melding.
- `PYTHONPATH=src pytest -q tests/test_v2_*.py
  tests/test_market_revision_projection.py tests/test_market_revision_incident_history.py
  tests/test_ha_projection_sink.py tests/test_architecture_ownership.py --tb=short`:
  **832 geslaagd, 1 overgeslagen**, 99,39 seconden. Omvat bron/plan/UI-integratie,
  canonieke MEP-scenario's, uitvoeringscontinuïteit, herkomst en eigendomsgrenzen.
- Ruff over `src/picot`, alle v2-tests en marktprojectie-/incidenttests: geslaagd.
- Mypy over `src/picot`: geslaagd, **234 bronbestanden**.
- `git diff --check`: geslaagd. Geen runtime-, MEP-, evaluatie-, opslag- of
  financiële rekenwijzigingen, nieuwe afhankelijkheden of versieophoging.

## Projectiereplay van de echte diagnose

De bestaande compacte bewijsdictionary is eerst verliesvrij uitgepakt. Vervolgens
zijn de originele planstatus en marktroutevergelijking met de aangepaste productiecode
opnieuw geprojecteerd en via WebViewStore gepubliceerd. Geen nieuw plan berekend.

| Lokale polltijd | Alternatieven | Plandeel dev.277 | Plandeel na fix | Resultaat |
| --- | ---: | ---: | ---: | --- |
| 19:01:53 | 1.393 | 10.903.803 tekens | 2.005.407 tekens | Compleet gepubliceerd |
| 19:04:36 | 1.338 | 10.474.935 tekens | 1.928.044 tekens | Compleet gepubliceerd |

Beide houden `plan-a37f6db440f2743e`, `live_plan_ready`, live autoriteit, alle
financiële uitkomsten en exact herstelbare bronverwijzingen. De oude en gedeelde
incidentencoder leveren voor beide records gelijke gegevens; de aangeleverde
incidentregistratie behoudt haar SHA-256.

Dit meet het oorspronkelijke falende plandeel. De ZIP bewaart geen alternatieve
padlichamen en adapterrecord, waardoor de volledige oorspronkelijke webweergave
niet exact kan worden gereconstrueerd. De complete `build_web_view`-keten is
afzonderlijk beproefd met de grote volledige regressiefixtures. Livegedrag en
browserprestaties op de NUC zijn nog niet geverifieerd.

## Overdracht

Lokaal gereed op `fix/dashboard-market-payload`, zonder commit, push of publicatie.
Na afzonderlijk releaseakkoord via de gebruikelijke PR/CI-route uitbrengen.
Livecontrole: actief plan en werkelijke uitvoeringsstatus zichtbaar, vergelijking
inclusief verliezers aanwezig, en actuele metingen/financiële updates blijven
verversen. Een echt financieel meetgat blijft herkenbaar onvolledig.

## Release dev.278 — akkoord 28 september 20:37

Alex heeft publicatie aangevraagd. Dit vervangt de eerdere lokale publicatiestatus.
De release gaat vanaf dev.277 via een afzonderlijke PR en de bestaande CI-controles.
Runtimeversie, add-onmanifest, versiecontrole en add-onchangelog worden gezamenlijk
bijgewerkt. Geen andere instellingen of componentversies wijzigen. Installatie
op de NUC en livecontrole volgen na geslaagde publicatie afzonderlijk.

De verse releasecontrole slaagt: **25 tests** voor versie, add-onverpakking,
architectuur en dashboardregressie; Ruff over productiecode en betrokken tests;
mypy over **234 bronbestanden** en `git diff --check`. De eerste incrementele
mypy-aanroep kreeg een interne checkerfout; de volledige niet-incrementele
controle met een nieuwe cache slaagde. CI beoordeelt de definitieve commit
in een schone omgeving opnieuw, inclusief de volledige testset.
