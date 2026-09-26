# 26 september — overbrugging en exportintentie

Status: lokale beperkte fix; niet releaseklaar. Geen publicatie of livewijziging.
Basis: dev.270, db9aa7391c55add746b3d57a074a39798a0a955f.

## Contract

Alex beperkt fix 1 tot export -> NOM met consequent exportdoel. Punt 2,
schakelen rond 15:25, is uitsluitend onderzoek. Eerste foutgrens:
`IndependentDailyReferenceAdapter.bridge_windows` verandert een vrije
exportintentie naar NOM maar bewaart het positieve exportdoel. De constructor
weigert dit terecht. Autoriteit: ADR-024, ADR-032, ADR-033, ADR-037.9 en het
canonieke pipelinecontract. Eigenaar: kandidaatconstructie; selectie, dagdoelen,
Store, uitvoering en schakelbeleid vallen buiten deze wijziging.

Invariant: niet-exportintenties hebben nul exportdoel, de oorspronkelijke route
blijft ongewijzigd beschikbaar, latere hoofdopdrachten blijven beschermd.
Regressie moet eerst dezelfde fout tonen en vervolgens de echte simulator en
pipeline doorlopen. Lokale wijziging afzonderlijk terug te draaien; dev.268
blijft Alex' eerste operationele terugvalbasis. Geen nieuwe releaseversie.

## Fix 1 en resterende blokkade

Alleen de bestaande NOM-alternatiefconstructie wist nu `storage_export_target_wh`.
De daarop gebaseerde standby-/netlaadalternatieven krijgen daarmee ook geen
achtergebleven exportwaarde. De baseline wordt niet gemuteerd.

De nieuwe ketentest faalde voor de wijziging met de live fout:
`Only storage export intent may request storage export.`
Na de wijziging doorloopt de berekening die grens, maar de ketentest faalt later:
`pending market window cannot be removed or relocated`.
`ActivePlanCommitmentStore._preserve_market_bindings` vereist behoud van een
nog open handelsvenster en weigert het geselecteerde alternatief zonder dat
venster. Deze grens is bewust niet gewijzigd: een willekeurige verwijdering
toelaten zou bestaande eigendoms- en marktregistratiecontroles omzeilen.

De adapterregressie gebruikt de echte simulator en 504.5251533820346 Wh uit het
incident, bewijst consistente alternatieven en ongewijzigde opslag. De fixture
is synthetisch met een bestaand store-boundary handelsvoorstel; geen volledige
historische replay of bewijs van economische markttoelating van de fixture.
De integratietest blijft expliciet rood als releaseblokkade, zonder xfail.

## Onderzoek punt 2: 15:25

Diagnose 26 september, run-a8728bd3525bfc68:
- planninginput 15:25:22.384609 lokale tijd, SOC 95%;
- behouden plan plan-6614002634def2b2 heeft netladen tot 15:25:30.042180;
- daarna staat NOM in hetzelfde bestaande plan;
- uitvoeringswaarneming 15:25:37.322780, dus na de segmentgrens;
- dispatch-ID noemt expliciet die NOM-grens;
- `live_runtime` registreert `run.evaluation.reason` als schakelreden.

De schakelreden beschrijft hier het behouden van het plan, terwijl de daadwerkelijke
schakeling zijn volgende segment uitvoert. Het laadblok is niet voortijdig
onderbroken: ADR-037.15 beschermt het tot zijn eigen einde.
Om 15:30:35 (SOC 94%) constateert een nieuwe berekening circa 63.63 Wh tekort
voor het dagdoel; nieuwe financiële selectie kiest netladen, uitgevoerd 15:31:05.
Dat verklaart het heen-en-weer maar bewijst niet dat deze keuzes globaal optimaal
waren. Geen schakel- of labelwijziging uitgevoerd.

## Validatie

- Nieuwe adapterregressie: geslaagd.
- Nieuwe publicatieregressie: faalt op bovengenoemde Store-grens.
- Ruff op src/picot en gewijzigde tests: geslaagd.
- Mypy op 225 bronbestanden: geslaagd.
- Gerichte overige regressies: resultaat volgt na afronding.

Vervolg vereist een expliciete uitbreiding naar de overdracht van een canoniek
geselecteerde marktrevisie aan de Store; geen vrijbrief voor algemene plannerwijzigingen.

## Overleg en besluit, 26 september 19:38

Alex vroeg eerst overleg. De eerdere testverwachting dat verwijderen moest
worden opgeslagen was voorbarig: ADR-019.1/019.3 beschermen bewust de vastgelegde
marktroute. De Store-weigering is daarmee niet op zichzelf een bewezen defect
tegen het toenmalige beleid. De synthetische publicatieregressie is een
onderzoeksexperiment, geen geaccepteerd bewijs dat verwijderen moet winnen.
De oorspronkelijke fout export -> NOM met positief exportdoel staat daar los van.

Vervolgens is expliciet een nieuwe vergelijkingsrichting afgesproken en bevestigd:
`docs/architecture/ADR-019.5-financial-market-revision.md`. Alle alternatieven
moeten zichtbaar worden berekend; Evaluation kiest op gezamenlijke financiële
uitkomst over vandaag en morgen met eerlijke eindvoorraad. De Store bewaart
uitsluitend de correct geselecteerde revisie. Laadregels blijven de basis.
Deze vervolgstap verandert uitsluitend documentatie, geen productiecode of tests.

Onderzoek met de originele PlanningInputSnapshots en de echte fysieke simulator
en afrekening vergelijkt behoud met alleen het schrappen van de export van die
dag. Overige vensters blijven gelijk; benodigde laadenergie volgt uit de simulator.

| Snapshot (lokale tijd) | Verschil die dag | Verschil volgende dag | Gezamenlijk behoud minus schrappen |
| --- | ---: | ---: | ---: |
| 25 september 13:21:55 | +0,906739 EUR | -0,324567 EUR | +0,582172 EUR |
| 25 september 19:30:47 | +0,496708 EUR | -0,201308 EUR | +0,295401 EUR |
| 26 september 16:29:47 | +0,781207 EUR | -0,309830 EUR | +0,471377 EUR |

Per vergelijking eindigen beide routes met dezelfde voorraad en halen beide
het volgende 100%-doel. Dit zijn afzonderlijke prognoseherberekeningen met het
bestaande tariefmodel, geen optelbare of werkelijk gemeten besparingen. Geen
nieuwe optimalisatie van nachtlaadvensters; het zaterdagse overbruggingstekort
blijft in de behouden route bestaan en wordt door netimport gedekt/meegerekend.
De ZIP bevat voor 22–24 september uitsluitend beknopte gebeurtenissen, geen
vergelijkbare volledige invoersnapshots. Fysiek is de tweedaagse horizon er al;
de verschillende financiële selectiemaatstaven en het absolute exportbehoud
vormen het aangetroffen verschil met het nieuwe besluit.

## Technisch implementatieplan

De vervolgstap is uitgewerkt in
`docs/development_log/2026-09-26-market-revision-implementation-plan.md`:
consistente kandidaten, volledige alternatieven inclusief behoud met bijladen,
gezamenlijke financiële selectie, expliciete atomaire revisie en zichtbaar bewijs.
Het plan beschrijft ook het vervangen van de voorbarige publicatietest door
financieel gecontroleerde behoud-/wijzigingsgevallen en de beschikbare replays.
Deze uitwerking verandert uitsluitend documentatie; de eerdere productiecode en
testexperimenten zijn niet verder gewijzigd. Implementatie en releasebewijs
blijven open.

## Vervolg na implementatieakkoord

Alex heeft het technische plan vervolgens om 19:55 goedgekeurd. De lokale
implementatie, vervanging van de voorbarige publicatietest en actuele
verificatieresultaten staan in
`docs/development_log/2026-09-26-market-revision-implementation.md`.
De eerdere statussen hierboven blijven het verslag van de toenmalige onderzoeksstappen.

Het vervolgonderzoek van fix 2 staat in
`docs/development_log/2026-09-26-switching-investigation.md`. De oorspronkelijke
snapshots reproduceren nu ook de kandidaatblokkade vóór het verstrijken van de
laadgrens: eerst alleen PV-opties, daarna uitsluiting op laadcontinuïteit zonder
aanvullende netlaadopties. Dit onderzoek wijzigt geen productiecode.
