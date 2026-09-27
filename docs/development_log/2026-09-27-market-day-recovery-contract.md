# Herstelcontract — marktroute binnen de dagelijkse MEP-cyclus

Datum: 27 september 2026, Europe/Amsterdam.
Basis: gepubliceerde dev.275, `1b6bb2224e2c967965a761ce8d20a5cf12f89aab`.
Status: technische uitwerking van de door Alex om 19:02 bevestigde richting.
Alex koos om 19:16 expliciet voor wachten op bekende herstelprijzen.
Lokale implementatie in `fix/market-day-recovery`; verificatie hieronder.
Geen commit, publicatie of livewijziging. Het oorspronkelijke voorstel hieronder
blijft als besluitgeschiedenis leesbaar; de keuze staat vast in ADR-019.6.

## Bevestigde bedoeling

De bestaande dagelijkse laadcyclus blijft de basis. Per lokale leveringsdag
blijven een eigen hoofdopdracht, werkelijk voltooiingsbewijs en financiële
uitkomsten bestaan. Het volgende dagplan begint met de verwachte beschikbare
SOC en de eigen prijzen, PV en huisvraag. Reeds gerealiseerde kosten worden
niet opnieuw geoptimaliseerd. De volledige fysieke tijdlijn blijft doorlopen.

Na het laden bewaakt PicoT de overbrugging tot de volgende bekende hoofdlaadsessie.
Extra herstelenergie en haar kosten worden meegerekend bij de handeling die
deze veroorzaakt. Het begin van laden beëindigt die kostenrekening niet
automatisch. Als routes onder dezelfde vastgelegde vervolgacties weer dezelfde
energievoorraad bereiken, is hun eerdere voorraadverschil opgeheven. Een later
verschil door een andere marktroute hoort niet alsnog bij dat eerdere herstel.

Automatische marktplanning is het doel. De marktroute krijgt dezelfde structuur
als laden: opdracht per dag, vastgelegde route, relevante aanleiding voor
herbeoordeling en traceerbare revisie. Laden behoudt het verplichte 100%-doel;
handel moet financieel zinvol zijn. Veiligheid en werkelijke onuitvoerbaarheid
blijven afzonderlijke redenen om in te grijpen.

Een verbetering moet tegen dezelfde uitgangssituatie worden berekend. Behoud,
inkorten en verwijderen moeten zichtbaar vergelijkbaar zijn. Een winstgevende
ingekorte route mag niet vooraf door een ongerelateerd eindvoorraadvereiste
verdwijnen. Gelijkwaardige uitkomsten behouden het bestaande commitment.

## Oorspronkelijke afspraak en eerste verkeerde grens

De audit van 8 september legt zelfstandig herstel van dagopdrachten al vast:
`docs/rebuild/session/CHARGE_AGREEMENT_AUDIT_2026-09-08.md`.
De gewone laadroute bevat nog de bijbehorende bescherming. ADR-037.2/.4/.9
blijven de basis voor daggrenzen, blijvende opdracht en overbrugging.

Dev.271 voegde vóór de bestaande laad-/brugconstructie een afslag naar
`market_revision_windows` toe zodra enige resterende marktroute aanwezig is.
Een trigger bevat een laadeigenaar, maar die afslag bepaalt niet of de gekozen
marktroute tot de betreffende herstelvraag behoort. De financiële horizon loopt
vervolgens tot middernacht na morgen. Bij een ongeldig incumbent wordt de hoogste
eindvoorraad van haalbare kandidaten een verplichte vergelijkingsnorm.

Dit verwart drie grenzen:

1. Welke opdracht mag door deze aanleiding veranderen?
2. Hoe ver moet de volledige fysieke route worden gecontroleerd?
3. Tot waar moeten de financiële gevolgen van deze specifieke keuze worden
   vergeleken?

Alleen een verbod bij de Store toevoegen verplaatst de fout naar publicatie.
Alleen morgen uitsluiten is eveneens te grof: een wijziging in de verwachte SOC
kan een eigen herstelvraag voor morgen rechtvaardigen. De eerste correctie hoort
bij de toelating en afbakening van de bestaande kandidaatconstructie.

## Technische afbakening

| Verantwoordelijkheid | Bestaande plek | Vereiste verandering |
| --- | --- | --- |
| Aanleiding en betrokken opdracht | `material_replanning.py`, `_build_daily_main_run` | Een aanleiding voor laden/overbrugging geeft geen algemene bevoegdheid over alle latere handelsopdrachten. Een marktreview moet verwijzen naar de eigen energie- of herstelgevolgen. |
| Volledige alternatieven | `market_revision_candidates.py`, bestaande laad-/brugconstructie | Behoud, inkorten en verwijderen binnen de toegelaten opdracht. Andere acties blijven behouden. Geen afzonderlijke herstelplanner. |
| Financieel bewijs | `market_route_admission.py`, `market_rule_planning.py`, `mep_candidate_outcomes.py`, bestaande settlement | Dezelfde grondslag voor eerste toelating en latere revisie; aantoonbaar benodigde herstelkosten, zonder gezamenlijke verplichte eind-SOC na ongerelateerde acties. |
| Keuze | Bestaande Evaluation | Kies op de onderbouwde uitkomsten. Fysiek onhaalbaar, financieel nadelig en financieel nog niet vergelijkbaar zijn verschillende toestanden. |
| Vastlegging en uitvoering | Bestaande Plan Builder, marktbindings en Store | Gekozen route exact vertalen en atomair bewaren, met identiteit en uitgevoerde hoeveelheid. Geen economische vervanging door Store of uitvoering. |
| Uitleg | Bestaande canonieke vergelijkingsrecords en projectie | Eigen dag, aanleiding, herstelgrens, gebruikte prijzen en ontbrekend bewijs tonen. Geen financiële uitkomst in de UI verzinnen. |

De financiële vergelijking moet een benoemde herstelopdracht of aantoonbare
opheffing van het energieverschil hebben. Exacte gelijkheid aan de hoogste
voorraad aan het einde van morgen is daarvoor geen vervanging. Volledige
fysieke validatie blijft nodig, ook na de financiële vergelijkingsgrens.

Bij een onhaalbaar oorspronkelijk laadplan mag dit plan geen fictieve goedkope
referentie of verplichte eindvoorraad leveren. Vergelijk uitvoerbare
herstelalternatieven onder dezelfde dagverplichtingen. Ontbrekend economisch
bewijs mag een geldige gewone laadreparatie niet blokkeren.

Import, export, PV-opportuniteitskosten, verliezen en ingestelde slijtage mogen
elk maar eenmaal meetellen. De bestaande tariefinstelling moet identiek worden
doorgegeven bij aanmaken en reviseren. De fiscale betekenis van tarieven wordt
in deze wijziging niet opnieuw ontworpen.

## Wat blijft en wat wordt vervangen

Behouden:

- dagelijkse 100%-opdrachten, onafhankelijke revisie en voltooiingsbewijs;
- actuele fysieke SOC en bestaande huis-/PV-simulator;
- laadcontinuïteit en bestaande beschermde uitvoering;
- correcte omzetting export naar NOM met nul expliciet exportdoel;
- correcte simulatiegrenzen bij iedere actieve planovergang;
- maximaal één handelsopdracht per leveringsdag, uitgevoerde export en herkomst;
- atomaire opslag en bestaande uitvoeringsketen.

Vervangen op de oorspronkelijke plek:

- de onbegrensde koppeling van een laadtrigger aan de eerstvolgende marktroute;
- de vaste financiële eindgrens aan het einde van morgen;
- de afwijzing op basis van de hoogste eindvoorraad van de kandidaten;
- de verschillende financiële grondslagen voor eerste toelating en revisie.

Geen nieuwe middernachtvoorraad, fictieve herstelprijs, verplicht extra laadblok,
willekeurige schakeldrempel of tweede planner. Het afgewezen lokale prototype
`fix/market-terminal-recovery` hoort niet bij deze wijziging. Het financiële
tabblad en algemene fout-/NOM-terugval blijven aparte onderwerpen.

## Besluit: eerste marktroute wacht op bekende herstelprijzen

Een volledig automatisch en financieel vergelijkbaar handelsbesluit heeft
herstelprijzen nodig als de alternatieven anders met verschillende bruikbare
voorraad eindigen. Die prijzen zijn bij de eerste planning vaak nog onbekend.

Concreet incident: in snapshot `snapshot-5ab19bfe6b58f4dd` zijn prijzen bekend
tot 29 september 00:00 lokaal. De marktroute van 28 september eindigt om
19:40:01 lokaal; daarna staat geen volgende hoofdlaadsessie in het bekende plan.
De dinsdagse herstelkosten zijn daarmee niet bewezen. De oude hersteltoets
alleen verplicht inschakelen zou zo'n nieuwe route blokkeren.

De besproken mogelijkheden waren:

| Keuze | Eerste plan | Zodra herstel beoordeelbaar wordt |
| --- | --- | --- |
| Vooraf plannen met onvolledig herstelbewijs — advies | Leg een fysiek haalbare marktroute vast op de bekende daginformatie en expliciete prijs-/spreadvoorwaarden. Vermeld dat het totale voordeel inclusief herstel nog niet bewezen is; verzin geen herstelbedrag. | Laat het beschikbaar komen van de ontbrekende herstelbasis een eigen marktbeoordeling openen. Behoud, inkorten en verwijderen worden dan eerlijk vergeleken. |
| Wachten op herstelbewijs | Leg nog geen nieuwe marktroute vast als haar voordeel niet vergelijkbaar is. Een reeds geldig commitment verdwijnt niet alleen doordat gegevens ontbreken. | Plan de route zodra de volledige vergelijking mogelijk is. Morgen kan daardoor aanvankelijk zonder marktroute worden getoond. |

Alex heeft het alternatief **wachten op herstelbewijs** gekozen. Het gewone
laadplan wordt alvast vastgelegd. Een nieuwe marktroute volgt pas wanneer het
herstel met bekende prijzen vergelijkbaar is en financieel voordeel heeft.
Dit vervangt het bovenstaande voorlopige advies; er wordt geen voorlopige
marktroute gepubliceerd. Een bestaand geldig commitment wordt door ontbrekend
economisch bewijs alleen niet gewist.

## Vereist bewijs voor de implementatie

| Geval | Onafhankelijke verwachting |
| --- | --- |
| Vandaag heeft een tekort; morgen bereikt 100% vóór zijn marktroute | Vandaag repareren; latere export van morgen kan de reparatie niet ongeldig maken of verdwijnen door haar eigen eindvoorraad. |
| Morgen heeft door gewijzigde verwachte SOC zelf een tekort | Morgen krijgt een eigen gerichte laadrevisie; vandaag en voltooide doelen blijven behouden. |
| Handel vanavond veroorzaakt extra netladen morgenochtend | Vergelijk exportvoordeel met de werkelijk benodigde extra herstelkosten, ook als het herstel na de overbruggingsgrens doorloopt. |
| Beide alternatieven bereiken onder dezelfde vervolgacties weer dezelfde voorraad | Een latere ongerelateerde marktroute verandert de rangschikking van het eerdere herstel niet. |
| Gedeeltelijke handel is gunstig, volledige handel ongunstig | Ingekorte route blijft beschikbaar en kan winnen ten opzichte van verwijderen. |
| Alle handelsvarianten zijn ongunstig | Geen handel mag financieel winnen door een verborgen voorraadverschil. |
| Herstelprijzen ontbreken | Exact het gekozen gedrag uit de vorige sectie; geen verzonnen bedrag en geen blokkade van een geldige laadroute. |
| Gewone SOC-daling volgens plan en ongewijzigde verwachtingen | Geen nieuwe routekeuze of extra dagelijkse cyclus. |
| EV/droger of relevante PV-afwijking | Zelfde dag-/marktopdracht gericht aanpassen; geen indirecte revisie van een andere handelsopdracht. |
| Herstart en onvolledige opslag | Dezelfde gekozen route, doelen, dagbudget en werkelijk uitgevoerd volume blijven behouden; geen halve revisie. |
| Tariefinstelling en einde leveringsdag | Gelijke waarderingsbasis voor aanmaken en aanpassen; correcte lokale daggrenzen. |

Test eerst de eerste verkeerde grens rood op dev.275, daarna dezelfde proef op
de correctie. Gebruik de echte simulator, Evaluation, Plan Builder en tijdelijke
Store. Voor marktbehoud en verwijdering worden beide gunstige en ongunstige
gevallen getoetst; alleen het incident laten slagen is onvoldoende.

De originele snapshots van 25, 26 en 27 september dienen als prognosereplays;
zij bewijzen geen werkelijk gemeten besparing of volledige livewerking. Een
livecontrole volgt pas na implementatie, gerichte regressies, Ruff/mypy en CI.
Er is in dit contract geen autorisatie voor een release of livewijziging.

## Reeds uitgevoerd onderzoek

- Read-only audit van dev.275 en relevante wijzigingen sinds dev.268.
- 120 gerichte bestaande tests geslaagd: dagopdracht, laadselectie, onafhankelijke
  dagrevisies, overbrugging, markttoelating en marktherziening.
- Afzonderlijke prijsproef: wijzig 21 prijsintervallen vóór morgen met behoud van
  fysieke invoer; verwachte beginvoorraad en gekozen morgenroute blijven gelijk.
- Verse incidentreplay: herstel van 27 september opent export van 28 september;
  31 behoudalternatieven en 279 ingekorte alternatieven worden alleen door de
  gezamenlijke eindvoorraad afgewezen. 31 verwijderalternatieven blijven geldig.
- Eerdere geïsoleerde proef op datzelfde incident: zonder het openen van de
  marktroute van morgen vindt de bestaande laadroute een uitvoerbaar herstel,
  met behoud van alle acties van morgen en herstelbare opslag.

Deze voorafgaande bewijzen ondersteunen de oorzaak en richting. De nieuwe
implementatie is afzonderlijk getoetst zoals hieronder beschreven.

## Werkvolgorde en terugval

1. Afgerond: keuze voor wachten en precisering in ADR-019.6 vastgelegd.
2. Maak het incident en de grens tussen betrokken en onbetrokken opdrachten
   expliciet toetsbaar; corrigeer toelating en financieel bewijs aan de bron.
3. Verbind eerste toelating en revisie aan dezelfde gekozen grondslag en
   behoud de bestaande marktidentiteit, Store en uitvoering.
4. Verifieer de volledige samenhang, inclusief ontbrekende gegevens, opeenvolgende
   beslissingen en herstart, vóór een afzonderlijke releasebeslissing.

De implementatie begint vanaf dev.275 in een eigen werkboom. De ongewijzigde
dev.275-audit en het afgewezen prototype blijven beschikbaar. De operationele
terugvalbasis blijft de eerder door Alex aangewezen dev.268; dit document voert
geen terugval uit en beweert niet dat die alle recent opgeloste fouten bevat.

## Lokale uitvoering en verse verificatie

De foutieve onderdelen zijn vervangen in de bestaande keten:

- De toelating tot marktherziening gebruikt de eigenaar en grens van de
  laad-/overbruggingstrigger. Een herstelvraag van vandaag geeft geen toegang
  tot de export na het laden van morgen.
- De gemeenschappelijke herstelgrens komt uit een bestaande laadopdracht.
  De vaste grens aan het einde van morgen en de toets op de hoogste
  eindvoorraad zijn verwijderd. De fysieke simulatie blijft volledig.
- Eerste markttoelating en revisie gebruiken dezelfde settlement en slijtage.
  De eerste route vereist bekend vergelijkbaar herstel en positieve bijdrage.
  De oude hersteloptie schakelt alleen de aanvullende minimummarge in.
- Lagere exportprijzen worden niet langer vooraf afgeschreven op grond van
  alleen de exportprijs: hun herstelkosten kunnen verschillen.
- De bron van prijzen en herstelopdracht, plus het hersteleinde, staan bij
  de canonieke uitkomst/het energiepad. Het instellingenscherm beschrijft de
  gewijzigde betekenis van de aanvullende marge.

Bekende prijzen alleen bewijzen nog geen vergelijkbaar herstel. Als de
alternatieven bij de bestaande laadcyclus niet aantoonbaar weer dezelfde
voorraad hebben, blijft eerste toelating wachtend. Er wordt geen extra
laadcyclus aangelegd en geen fictieve voorraadwaarde gebruikt om dit alsnog
goed te keuren. Een gewone laadreparatie blijft afzonderlijk beschikbaar.

Gerichte regressies:

- De nieuwe controles op het omzeilen van herstelbewijs en verliesgevend
  herstel faalden eerst op dev.275. De daggrensproef maakte daar 153
  marktherzieningskandidaten voor de onbetrokken export van morgen.
- 34 controles op hersteltoelating, marktvergelijking, dagelijkse doelen en
  ontbrekende gegevens slagen op de gewijzigde code.
- De integratieproef doorloopt wachten → nieuwe prijspublicatie → zelfstandig
  laadplan voor morgen → toelating van handel met bewezen herstel.
- De gerichte eindcontrole met wisselende huisvraag, wachten/toelaten en
  uitbreiding van de bestaande laadopdracht slaagt: 3 tests, 115,99 seconden.
  Identiteiten en 100%-opdrachten blijven geldig; een noodzakelijke aanpassing
  van de herstelroute is toegestaan.
- Ruff voor alle productiecode en gewijzigde tests slaagt. Mypy slaagt voor
  alle 232 productiebronbestanden.
- De brede run doorliep 1.824 tests: 1.822 geslaagd, 1 overgeslagen en één
  verouderde testverwachting over een volledig ongewijzigde herstelroute.
  De run had deze verwachting vóór de correctie ingeladen. De gecorrigeerde
  proef controleert identieke dagopdrachten, behoud van vandaag en daadwerkelijk
  haalbare 100%-doelen; die slaagt in de gerichte eindcontrole hierboven.
  Na afloop is ook `pytest -q --lf` opnieuw uitgevoerd: 1 geslaagd in
  59,92 seconden. Daarmee zijn alle 1.823 uitgevoerde tests afgedekt; één test
  blijft overgeslagen. Er is geen volledige tweede run uitgevoerd.

De complexe synthetische proef met wisselende huisvraag vergt ongeveer een
minuut. Nieuwe markttoelating onderzoekt meer opties doordat alleen een lagere
exportprijs geen geldig uitsluitingsbewijs meer is. De bestaande checkpoints
voor doorlopende uitvoering zijn behouden en hun bestaande integratietests
slagen. De rekentijd op de liveinstallatie is nog niet gemeten.

Historische prognosereplays, met oorspronkelijke snapshots en tijdelijke Store:

| Snapshot (lokale tijd) | Uitkomst gewijzigde code | Bewijs |
| --- | --- | --- |
| 25 september 13:21:55 | Bestaand plan behouden | Geen nieuwe aanleiding; identiteit en herstart gelijk. |
| 25 september 19:30:47 | Bestaand plan behouden | Geen nieuwe aanleiding; voltooid doel blijft voltooid. |
| 26 september 16:29:47 | Herstel met behoud van de marktroute | 1.615 alternatieven; behoud is beter dan inkorten/verwijderen. Geen exportdoel op NOM en geen afgebroken berekening. |
| 27 september 15:27:35 | Herstel van vandaag, morgen intact | Geen herziening van de onbetrokken marktroute, geen resterende laadtekorten na herstart, geen gewijzigde acties van morgen. |

De zaterdagse vergelijking eindigt bij herstel op 27 september 16:15 lokaal,
met 8.160 Wh. Beste resultaten in dat vergelijkingsvenster bij de gebruikte
slijtageaanname van €0/kWh: behoud −€0,02817, inkorten −€0,08371,
verwijderen −€0,49352. Dit zijn voorspelde vensterresultaten, geen gemeten
dagresultaten. Deze replay duurde 24,37 seconden. De zondagse replay gebruikte
€0,02/kWh slijtage en duurde 1,84 seconden.

Geen versieophoging, commit, push, release of apparaatbesturing uitgevoerd.
Dit wijzigt ook geen reeds live verwijderde marktopdracht. Livegedrag en
werkelijk financieel resultaat zijn hiermee nog niet aangetoond.

## Release dev.276 — akkoord 27 september 20:00

Alex heeft na de lokale uitkomst akkoord gegeven op de vervolgstap. Publicatie
wordt voorbereid als dev.276 via PR en de bestaande automatische controles.
Dit vervangt de eerdere lokale publicatiestatus; installatie en liveverificatie
volgen afzonderlijk. De gecontroleerde basis is main
`1b6bb2224e2c967965a761ce8d20a5cf12f89aab` (dev.275).

Versie, add-onmanifest, versiecontrole en changelog worden samen bijgewerkt.
De wijziging bevat uitsluitend deze markt-/herstelcorrectie en haar documentatie
en tests. Het afgewezen prototype blijft uitgesloten. De afgesproken eerste
operationele terugvalbasis blijft dev.268.

De verse releasecontrole slaagt: 27 versie-, add-onpakket- en
architectuurcontroles, Ruff op productiecode en gewijzigde tests, mypy op alle
232 productiebronbestanden en `git diff --check`. De pull request voert de
volledige testset opnieuw uit op de definitieve release-inhoud.
