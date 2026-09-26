# Implementatieplan — financiële herziening marktroute

Datum: 26 september 2026. Status: akkoord voor uitvoering door Alex om 19:55
Europe/Amsterdam; lokaal uitgevoerd. Zie het
[implementatiebewijs](2026-09-26-market-revision-implementation.md) voor de actuele
verificatiestatus. Onderstaande volgorde beschrijft het vooraf afgesproken plan.
Besluit: [ADR-019.5](../architecture/ADR-019.5-financial-market-revision.md).
Basis: dev.270, lokale branch `fix/bridge-nom-export-target`.

## Wijzigingscontract

- **Eerste foutgrens:** overbruggingskandidaten maken van export NOM maar behouden
  een exportdoel van 504,525 Wh. De intentievalidatie wijst dat terecht af.
- **Vervolggrens:** absoluut exportbehoud verhindert nu revisie in de Store.
  Dit was bewust beleid; ADR-019.5 vervangt dat door financiële selectie.
- **Eigenaars:** MEP genereert en simuleert; Evaluation kiest; de Plan Builder
  vertaalt exact; de Store bewaart; de projectie toont het bewijs.
- **Autoriteit:** ADR-019.5, ADR-024, ADR-027, ADR-032, ADR-033, ADR-037.9 en
  de bestaande regels voor dagelijkse laaddoelen en laadcontinuïteit.
- **Invarianten:** afzonderlijke 100%-doelen en voltooiingsbewijzen, minimum-SOC,
  technische grenzen, actieve laadbescherming, één handelsopdracht per dag,
  gemeten uitvoeringshistorie en één canonieke planningsketen.
- **Bewijs:** incidentregressie, financieel gecontroleerde winnaars/verliezers,
  opslag/herstart en herberekening van beschikbare vrijdag-/zaterdagsnapshots.
- **Terugvalgrens:** iedere wijzigingsstap afzonderlijk herleidbaar en terug te
  draaien; dev.268 blijft de afgesproken operationele terugvalbasis. Vóór
  publicatie moet herstel van de bewaarde planstatus zijn beproefd.

Eerste markttoelating, gebruikersvelden, gewone hoofdlaadselectie, prognoses,
tarieven en schakelbeleid worden niet opnieuw ontworpen. De schakelregistratie
van 15:25 blijft een afzonderlijk onderzoekspunt.

## Uitvoeringsvolgorde en betrokken onderdelen

Elke stap levert bewijs bij de eigen grens; een gedeeltelijke keten geldt niet
als werkende marktrevisie en wordt niet als zodanig uitgebracht.

| Stap | Onderdelen | Concrete wijziging en resultaat |
| --- | --- | --- |
| 1. Consistente intenties | `src/picot/v2/independent_daily_reference_adapter.py`, `tests/test_daily_bridge_pipeline.py` | Export naar NOM wist het expliciete exportdoel; afgeleide standby-/laadvarianten zijn eveneens consistent. De oorspronkelijke route blijft intact. De domeinvalidatie blijft streng. |
| 2. Volledige alternatieven | Bestaande MEP-kandidaatconstructie, `bridge_windows()` en de domeinrecords voor simulatiebewijs | Behoud, inkorten en verwijderen van de betrokken marktroute, elk met haalbare aanvullende laad-/overbruggingsvarianten. Inclusief behoud **met** bijladen. Afwijzingen blijven zichtbaar. |
| 3. Vergelijking en keuze | `src/picot/planner/mep_candidate_outcomes.py`, `src/picot/v2/mep_canonical_pipeline.py`, bestaande Evaluation Engine | Expliciete marktrevisiecontext, één financiële maatstaf en een herkenbare incumbent uit hetzelfde nieuwe snapshot. Gewone laadselectie houdt haar bestaande maatstaf. |
| 4. Gekozen revisie vastleggen | `src/picot/domain/market_plan_binding.py`, `src/picot/domain/market_daily_assignment.py`, `src/picot/v2/plan_commitment_store.py` | Expliciet revisiebewijs maakt inkorten/verwijderen atomair mogelijk. Zonder dat bewijs blijft ongemerkt verlies van export een fout. |
| 5. Uitleg en ketenbewijs | Bestaande canonieke records, `src/picot/v2/projection.py`, bijbehorende diagnose/UI en tests | Alle berekende alternatieven met bedragen, eindvoorraad en selectie-/afwijsreden zichtbaar; geen berekening van een tweede winnaar in de UI. |

De adapter mag geen economische voorkeur toevoegen. Kandidaatconstructie blijft
onder MEP-eigenaarschap, ook waar bestaande functies nu in de adapter staan.
Gebruik de bestaande simulator, afrekening, Evaluation en Plan Builder; geen
zelfstandige marktselector of extra opslag-/dispatchroute.

## Kandidaten en financieel bewijs

Start vanuit het actuele snapshot en het volledige resterende bestaande plan.
Wijzig alleen de expliciet betrokken marktopdracht en de toegelaten aanvullende
energievoorziening. Bescherm de overige laadopdrachten en uitvoeringsgrenzen.
Inkorten gebruikt uitvoerbare segmentgrenzen en een opnieuw berekend volume;
verwijderen laat nul resterend exportdoel achter. Beperk en dedupliceer de
zoekruimte volgens bestaande resourcegrenzen, zonder een economisch onwelgevallig
alternatief vooraf te verbieden.

De huidige brugcode leidt laadvarianten af van één NOM-variant zonder export.
Dat moet worden uitgebreid zodat ook een behouden of ingekorte marktroute met
goedkoop bijladen kan meedoen. Een goedkoper gepubliceerd nachtvenster moet
mee kunnen doen als het vóór de energiebehoefte ligt en fysiek uitvoerbaar is.

Voor alle alternatieven geldt dezelfde horizon: het snapshotmoment tot het
einde van morgen in Europe/Amsterdam. De huidige grens van maximaal 36 uur of
het einde van een bestaand plan mag deze vergelijking niet ongemerkt afkappen.
Ontbrekende benodigde prijs-/prognosedekking wordt expliciet geregistreerd;
geen fictieve verlenging of besparing op basis van alleen morgen.

Het bewijs per alternatief bevat minimaal:

- snapshot-, opdracht-, kandidaat-, energiepad- en uitkomstidentiteit;
- horizon, tarief-/prognoseherkomst en status van de vergelijkbaarheid;
- importkosten en exportopbrengsten per lokale dag en gezamenlijk;
- extra netlaadenergie, eindvoorraad, minimumvoorraad en dagelijkse doeltoetsen;
- ingestelde slijtage en eventueel expliciet herstelbewijs voor eindvoorraad;
- gezamenlijk vergelijkbaar resultaat, verschil met behoud en afwijsredenen.

Vergelijk exportopbrengst minus importkosten en toepasselijke ingestelde
slijtage. PV-opvang, verdrongen eigen verbruik en conversieverliezen werken door
via dezelfde fysieke simulatie en afrekening; tel ze niet nogmaals als losse
besparingen of kosten. Historische betalingen staan vast. Het fictieve goedkope
referentievenster van de eerste markttoelating is geen werkelijk herstelpad.

Ongelijke eindvoorraad mag geen schijnwinst opleveren. Gebruik gelijkwaardige
voorraad of aantoonbaar uitvoerbaar herstel met beschikbare prijzen; registreer
hoe die kosten zijn meegenomen zonder dubbeltelling. Zonder dat bewijs is het
alternatief financieel niet vergelijkbaar, ook als zijn ruwe kassaldo hoger is.

Evaluation behoudt de geldige incumbent bij gelijkwaardige/slechtere resultaten.
Een aantoonbaar betere geldige kandidaat kan winnen. Een onhaalbare kandidaat
krijgt een afwijsreden en blokkeert geen nog geldige uitvoering. Een ongeldige
incumbent wordt niet via deze behoudregel geldig verklaard; bestaande veiligheids-
en herstelregels blijven gelden. Programmeer-/consistentiefouten blijven fouten,
geen verborgen economische afwijzingen.

## Overdracht en opslag

Geef de Store naast het exact gebouwde winnende plan expliciet revisiebewijs:
vorige plan-/opdrachtrevisie, snapshot, geselecteerde kandidaat, EvaluationRecord,
energiepad, betrokken marktopdracht en nieuwe resterende segmenten/hoeveelheden.
De Store controleert identiteit, actualiteit en onderlinge overeenstemming,
zonder het financiële oordeel over te doen.

Bewaar in één transactie het plan, actieve verwijzingen, markt-/laadbindings en
revisiehistorie. Schrijfuitval of verouderd bewijs laat de vorige toestand intact.
Herhaalde verwerking is idempotent. Geen algemene uitschakeling van
`_preserve_market_bindings`: alleen een aantoonbaar geselecteerde revisie krijgt
de nieuwe verwerking.

Een `MarketPlanBinding` vereist nu positieve export en segmenten. Volledig
verwijderen krijgt daarom een expliciete beëindiging binnen de bestaande
`skipped`/`stopped`-lifecycle, passend bij het uitvoeringsbewijs; geen fictieve
nulbinding of voltooiing. Bewaar de oorspronkelijke binding als historie.
Houd gemeten export, verstreken geplande export, geannuleerd volume en resterend
planvolume afzonderlijk. `elapsed_planned_export_wh` is geen meting.
Inkorten behoudt dezelfde dagidentiteit. Stoppen, verwijderen, herstart of een
regelrevisie vult het dagbudget niet opnieuw aan. Oude opslag moet leesbaar
blijven en mag geen uitgevoerde of gesloten opdracht heropenen.

## Acceptatie en replay

| Geval | Vereist resultaat |
| --- | --- |
| Incident met 504,525 Wh | Reproduceert de oorspronkelijke intentiefout vóór de correctie; daarna complete consistente kandidaten via de echte simulator. |
| Handel vandaag betaalt extra laden morgen terug | Behoud wint op gezamenlijke EUR, ook als schrappen morgen afzonderlijk goedkoper maakt. |
| Gedeeltelijk of volledig schrappen is werkelijk beter | Inkorten respectievelijk verwijderen wint, inclusief eventuele aanvullende laadkosten en eerlijke eindvoorraad. |
| Goedkoop later laden maakt behoud beter | Behoud met bijladen wordt gegenereerd en kan winnen; geen verplichte verwijdering om een laadvariant te maken. |
| Gelijkwaardig/slechter alternatief | Zelfde incumbent blijft; geen nieuwe willekeurige schakeldrempel. |
| Ongelijke eindvoorraad, ontbrekende prijzen, doel-/reservetekort | Herleidbare afwijzing of onvoldoende vergelijkingsbewijs; geen fictieve winst of vals 100%-bewijs. Een geldige incumbent blijft uitvoerbaar. |
| Actief laden, voltooide dagdoelen, morgen afzonderlijk doel | Continuïteit en voltooiingshistorie blijven intact; geen verschoven of opnieuw geopend doel. |
| Gedeeltelijke export, nul resterend volume, herstart/schrijffout | Atomaire toestand, echte metingen behouden, correct resterend volume, geen tweede dagbudget; ook rond lokale daggrenzen en zomer-/wintertijd. |

Werk de bestaande regressie `test_bridge_export_removal_reaches_plan_publication`
om naar financieel gecontroleerde gevallen voor behoud én wijziging. De huidige
synthetische verwachting dat verwijderen moet winnen was voorbarig en is geen
acceptatiecriterium. Behoud de afzonderlijke intentieregressie.

Gebruik de bestaande suites voor daily bridge, main charge selection/optimisation,
financial settlement, market binding/rule/admission/assignment/execution en
projectie. Toets de canonieke herkomst tot en met Store, plus
`test_architecture_ownership.py` en `test_v2_mep_single_planner_architecture.py`.
Voer vóór release Ruff, mypy en de bestaande CI-/end-to-endcontroles uit; noteer
verse resultaten, geen overgenomen groene status van eerdere wijzigingen.

Bevries voor replay de relevante invoer uit de diagnose, met herkomst en zonder
onnodige privégegevens. Beschikbaar vergelijkingsbewijs:

| Snapshot, lokale tijd | Voorlopig voordeel behoud boven alleen export schrappen |
| --- | ---: |
| 25 september 13:21:55 | € 0,582172 |
| 25 september 19:30:47 | € 0,295401 |
| 26 september 16:29:47 | € 0,471377 |

Dit zijn afzonderlijke prognoseberekeningen met dezelfde eindvoorraad en het
bestaande tariefmodel, geen optelbare of werkelijk gemeten besparingen. Overige
vensters bleven gelijk; een optimale nachtlaadvariant is nog niet gezocht.
Gebruik de bedragen als controle op diezelfde twee paden, niet als voorgeschreven
winnaarbedrag voor de uitgebreidere kandidatenverzameling. De nieuwe replay moet
juist ook inkorten en extra laden vergelijken en het zaterdagse brugtekort
zichtbaar afhandelen. Voor 22–24 september ontbreken vergelijkbare volledige
invoersnapshots in de beschikbare ZIP.

## Huidige stand

Na akkoord is dit plan lokaal uitgevoerd. De eerdere voorbarige verwachting dat
exportverwijdering moest winnen is vervangen door financieel gecontroleerde
gevallen voor behoud, inkorten en verwijderen. Het afzonderlijke intentiebewijs
blijft staan. Actuele test-/replayresultaten en beperkingen staan in het
[implementatielog](2026-09-26-market-revision-implementation.md).
Er is geen commit, push, release of livevalidatie uitgevoerd.
