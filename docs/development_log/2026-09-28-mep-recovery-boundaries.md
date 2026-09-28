# 28 september 2026 — begrensd herstel van de MEP-beslisketen

Alex heeft om 22:23 Europe/Amsterdam ingestemd met het voorgestelde lokale
hersteltraject. Basis: dev.278, commit `ea5a4588257e974d68d544fe0a6a0e324106b809`,
inhoudelijk gelijk aan gepubliceerde tree `f392e97c28285a2ef09933454f667dd9a500091e`.
Werkbranch: `fix/mep-recovery-boundaries`. Geen release, push, commit of livewijziging
is met deze opdracht aangevraagd.

## Wijzigingscontract vóór implementatie

| Eerste foutgrens | Verantwoordelijke laag en wijziging | Vereist bewijs |
| --- | --- | --- |
| Eén onvoldoende onderbouwde marktvariant blokkeert alle financiële uitkomsten | Candidate-uitkomsten: herstelbewijs per kandidaat; vergelijk alleen aantoonbaar gelijkwaardige voorraad/horizon, met behoud van zichtbare afwijsredenen | Eén onvergelijkbaar alternatief toevoegen verandert geldige onderling vergelijkbare alternatieven niet |
| Voorselectie van laden verdringt complete geldige handelsroutes | Markt-kandidaatopbouw: volledige combinaties eerst beoordelen; bestaande Evaluation kiest | De 13 toegelaten herstelcombinaties uit de tegenproef blijven bereikbaar voor de eindvergelijking |
| Oude exportadministratie overschrijft een nieuwe planactie | Bestaande uitvoeringsbewaking: alleen de betreffende exportactie stoppen; afrekening gescheiden van nieuwe actie | Echt gekozen/gebouwd/opgeslagen support- en laadsegment blijft uitvoerbaar, ook bij ontbrekende afsluitmeting en herstart |
| Lokale overbrugging maakt omliggende vrije intervallen NOM | Bestaande overbruggingsgenerator: lokale aanvulling op bestaande route; PV-opvang alleen waar fysiek relevant; stand-by met eigen huishoudelijke noodzaak | Omliggende modi behouden, toegestane goedkope directe netvoeding blijft mogelijk; export alleen rechtvaardigt geen extra stand-by |
| Uitsluitend toekomstig onhaalbaar doel veroorzaakt huidige NOM-terugval | Dagelijkse pipeline: toekomstige onopgeloste verplichting en huidige uitvoerbaarheid afzonderlijk beoordelen | Toekomstig doel blijft onopgelost; geldig huidig segment blijft werken; echte huidige blokkades blijven blokkeren |

Normatief: ADR-001–037, vooral 016/017/024/025/026/027/030/031/032/033/034/035,
ADR-019.5/.6 en ADR-037.1–.16. De expliciete verduidelijking van stand-by en
toekomstige onhaalbaarheid is vastgelegd in ADR-037.21. Oude V2ADR-verwijzingen
verlenen geen aanvullende bevoegdheid.

## Grenzen en behoud

- Eén bestaande pipeline; simulatie en afrekening blijven hun huidige eigenaar.
- Dagidentiteit, afzonderlijke 100%-doelen, werkelijk voltooiingsbewijs, reserve,
  technische limieten, gebruikersregels en lopende laadcontinuïteit behouden.
- Geen nieuwe handelsstrategie, willekeurige winst-/SOC-/tijdsdrempel,
  netlaadprijsmodel, metingen, vendorvertaling, UI-planning of opslagformaatmigratie.
- Ongelijke eindvoorraden krijgen geen fictieve financiële gelijkheid.
- Geen toekomstig onhaalbaar plan als goedgekeurd presenteren; behoud van actuele
  uitvoering vereist bewijs en de bestaande uitvoeringsvalidatie.
- Een begunstigd exportalternatief mag niet worden afgedwongen via huis-stand-by.
- Een gekozen segment mag niet achteraf in Store of dashboard worden hertekend.

## Werkverdeling en samenvoeging

De coördinator bezit uitkomstenproductie, overbruggingsadapter, contractteksten en
gezamenlijke verificatie. Eén afzonderlijke uitvoerder bezit markt-kandidaatbouw
en eigen regressies; één bezit uitvoeringsbewaking/dagelijkse foutafhandeling en
eigen regressies. Publieke samenwerkingscontracten blijven behouden, tenzij een
concrete noodzakelijke uitbreiding eerst gezamenlijk wordt vastgesteld.

Iedere regressie wordt eerst op de oorspronkelijke bron tegen het echte defect
uitgevoerd. Daarna gerichte checks per eigenaar en verse geïntegreerde controles.
De echte diagnose van 28 september wordt gebruikt voor planvergelijking,
opeenvolgende observaties en resource-/diagnoseomvang. Synthetische grensproeven
blijven als zodanig herkenbaar. Geen offline resultaat heet LIVE_VERIFIED.

## Terugvalgrens

De lokale wijzigingen blijven los van de ongewijzigde dev.278-werkboom. Iedere
afgebakende wijziging is afzonderlijk inspecteerbaar; een release kan pas volgen
na gezamenlijke verificatie. De bestaande operationele terugvalafspraak wordt
hier niet veranderd. Dev.268 bevat aantoonbaar ook oudere constructies en wordt
niet als bewezen oplossing voor deze bevindingen gepresenteerd.

## Verificatie

### Uitvoering van het contract

- `mep_candidate_outcomes.py` bewijst herstel per alternatief op de bestaande
  laadcyclus. Intenties en fysieke intervalinvoer van die cyclus moeten gelijk
  zijn. Na het bereiken van 100% wordt de werkelijke, gelijke eindvoorraad
  vergeleken; die mag door aansluitend huisverbruik lager dan 100% zijn.
  Een ongeldige incumbent levert geen besparingsreferentie. De bestaande
  capability-, vermogen- en SOC-controles worden hiervoor gedeeld met de
  uiteindelijke uitkomstencontrole. Een afgewezen alternatief blijft zichtbaar.
- `market_rule_planning.py` laat iedere canoniek geldige laad-/exportcombinatie
  door de bestaande volledige markttoelating lopen. De geneste keuze op alleen
  laadprijs is verwijderd. De bestaande eind-Evaluation blijft de kiezer;
  er is geen willekeurige limiet op de nieuwe combinaties toegevoegd.
- `market_execution_guard.py` beperkt zijn NOM-ingreep tot aangevraagde export.
  Stopregistratie en ontbrekende afsluitmetingen blijven bestaan, maar zetten
  een geldige nieuwe support- of laadactie niet meer om naar NOM.
- `independent_daily_reference_adapter.py` bouwt lokale brugaanvullingen vanuit
  de bestaande modi. NOM-aanvullingen vragen voorspeld PV-overschot. Standby
  vraagt een zelfstandig huishoudtekort, vastgesteld met dezelfde simulator
  zonder de exportopdracht; deze tegenproef wordt geen uitvoerbaar plan of
  financieel alternatief. `market_revision_candidates.py` vult verwijderde
  export zonder PV-overschot met huishoudondersteuning.
- `mep_canonical_pipeline.py` kan uitsluitend bij een ongebonden toekomstige
  onhaalbare opdracht de bewezen huidige uitvoering behouden. De adapter
  controleert de bestaande verplichtingen en uitvoeringsgrenzen; huishoudelijk
  bewijs loopt tot de grens van de ongebonden volgende dag. Vanaf die daggrens
  geldt deze uitzondering niet meer. De diagnose blijft
  `future_daily_goal_unresolved:<opdracht>:<reden>`; er wordt geen winnaar,
  binding of voltooiing verzonnen. Een lege fysieke vensterontdekking behoudt
  bovendien haar oorspronkelijke reden.

### Rode regressies en onafhankelijke review

De aanvankelijke globale herstelblokkade is gereproduceerd met 112 aantoonbaar
herstellende alternatieven: toevoeging van één niet-herstellend alternatief
verwijderde alle financiële uitkomsten. De nieuwe regressie bewaart uitkomsten
en winnaar, ook in omgekeerde volgorde. De marktvoorselectie gaf eerst nul in
plaats van 13 volledig toegelaten routes. Acht echte Store-/uitvoeringsproeven
dekken vervanging van gestarte en nog niet gestarte export door support of laden,
inclusief ontbrekende meting en herstart. Zes proeven dekken uitsluitend toekomstig
falen en de negatieve gevallen voor ontbrekende input, reserve, capability en
het daadwerkelijk beginnen van de toekomstige dag.

De onafhankelijke review vond vóór afronding twee aanvullende grenzen in dezelfde
herstelvergelijking. Deze zijn gerepareerd en als regressies toegevoegd:

1. Een inmiddels niet-ondersteunde exportprimitief maakte de incumbent canoniek
   ongeldig, maar gaf nog winstverschillen. De gedeelde validiteitscontrole
   voorkomt die claim; geldige verwijderingsalternatieven blijven vergelijkbaar.
2. Een PV-herstelcyclus bereikte 8.160 Wh en eindigde na huisverbruik op 8.040 Wh.
   Alle 156 geldige reparaties krijgen nu hun vergelijkbare financiële uitkomst;
   het bereiken van 100% wordt niet verward met een verplichte volle eindvoorraad.

Een onafhankelijke simulatorproef met 60 trajecten bevestigde convergentie op
gelijke eindvoorraad bij dezelfde herstelcyclus en fysieke invoer, inclusief
verliezen en eindvoorraad onder 100%. Niet-herstellende trajecten vielen
afzonderlijk af. Dit is aanvullend synthetisch bewijs, geen liveprestatiemeting.

De eerste volledige testrun gaf 1.863 geslaagde tests, één skip en drie falende
overgangstests. Deze drie gebruikten kunstmatig `target_soc / 2`, onder de reserve.
De oude NOM-vervolgactie maskeerde dit; de nu correct behouden supportactie werd
terecht geblokkeerd. De fixture gebruikt voor de normale overgang nu een SOC
tussen reserve en doel en de werkelijke vendor-modus van de volgende actie.
Een extra negatieve proef bevestigt dat support onder de reserve geblokkeerd
blijft. De vijf overgangstests slagen. De definitieve volledige testverzameling
is opnieuw, in twee disjuncte delen, tegen de gezamenlijke eindbron uitgevoerd:
alle 1.869 tests geslaagd, één bestaande skip.

### Replay met opgenomen gegevens van 28 september

De volledige pipeline draaide op een lokale Store-kopie, teruggebracht naar de
opgenomen begincontext. Latere plannen en revisies zijn uitgesloten; eerdere
stopbewijzen zijn behouden. Planinhoud, planidentiteit en dagopdrachten zijn
vooraf gelijk aan de opname gecontroleerd. De instellingen komen uit de diagnose;
er zijn geen netwerk- of apparaatopdrachten uitgevoerd.

De basiscode reproduceert de opgenomen winnaar en planbeslissing exact. Het
herstel bewaart de eerdere route en voegt geen nacht-NOM of exportgerichte
standby toe. Vervolgobservaties en herstart behouden dezelfde planidentiteit
zonder nieuwe Store-writes. De vervolgreplay gebruikt werkelijk opgenomen
invoer na een hypothetisch andere eerdere keuze en is daarom conditioneel
bewijs van continuïteit, geen gemeten liveprestatie.

De eerste volledige vergelijking duurde lokaal ongeveer 27 seconden op de basis
en 19 seconden met herstel, terwijl andere tests tegelijk draaiden. De
synthetische winterproef groeide van 31 naar 290 complete kandidaten en van
circa 22 naar 25 seconden. Dit zijn geen apparaatprestatiegaranties. De bestaande
planning-checkpoints blijven aanwezig. Zowel het volledige dashboard als het
volledige diagnoserecord bleef binnen de bestaande omvanggrenzen.

De gedetailleerde replay blijft lokaal. Het openbare
[bewijsbestand](evidence/2026-09-28-mep-recovery-verification.json) bevat alleen
bronhashes, testresultaten en de uitkomst van deze controles; geen opgenomen
huishoudinstellingen, tijdschema's of financiële waarnemingen.

### Definitieve controles en opleverstatus

Ruff op alle productiebron en betrokken tests: geslaagd. Mypy op alle 234
productiebestanden: geslaagd. `git diff --check`: geslaagd.

De volledige definitieve pytest-verzameling is zonder overlap gesplitst:

- 99 tests voor de financiële/herstelketen en de nieuwe regressies: geslaagd
  in 379,47 seconden.
- Alle overige tests, met uitsluitend diezelfde dertien bestanden uitgesloten:
  1.770 geslaagd, één overgeslagen, in 344,54 seconden.
- Totaal: **1.869 geslaagd, één overgeslagen; geen falende tests**.

De skip is de bestaande optionele passieve-history-test die een externe
19-septemberdiagnose via `PICOT_TEST_DIAGNOSTIC` vereist. Deze bron was niet
ingesteld; de hierboven beschreven 28-septemberreplay is afzonderlijk uitgevoerd.

Beide runs gebruikten `PYTHONPATH=src:tests`, de lokale test-venv, `pytest -q
-p no:cacheprovider` en afzonderlijke tijdelijke testmappen. De dertien bestanden
waren `test_market_recovery_candidate_isolation.py`, `test_market_revision_comparison.py`,
`test_market_recovery_scope.py`, `test_market_revision_failed_goal.py`,
`test_market_rule_selection.py`, `test_market_complete_recovery_candidates.py`,
`test_market_route_admission.py`, `test_daily_main_charge_selection.py`,
`test_daily_bridge_pipeline.py`, `test_bridge_local_recovery.py`,
`test_ha_charge_transition_chain.py`, `test_market_guard_replacement_execution.py`
en `test_daily_future_failure_continuity.py`, alle in `tests/`.

De eindbron is onafhankelijk opnieuw bekeken op de twee financiële
reviewbevindingen; beide ongewijzigde tegenproeven slagen en de bevindingen zijn
gesloten. De bronhashes bij het replaybewijs stemmen met de eindbron overeen.

Alle wijzigingen zijn lokaal en inspecteerbaar op de genoemde werkbranch.
Geen versieophoging, commit, push, release of liveplaatsing. Live gedrag en
werkelijk gerealiseerd financieel resultaat zijn hiermee niet geverifieerd.

## Releasevoorbereiding dev.279

Alex heeft op 28 september 2026 om 23:04 Europe/Amsterdam afzonderlijk opdracht
gegeven: "oke maak release". Dit volgt op de hierboven afgeronde lokale
verificatie en autoriseert versieophoging, commit, push, PR en publicatie via CI.
Installatie op Home Assistant en live-apparaatopdrachten vallen hier niet onder.

De actuele gepubliceerde basis is dev.278, main-commit
`1a1db8a8952fa562ee959cfd27314c0f5cdaa4ed`; de tree is identiek aan de lokaal
gebruikte basis. Dev.279 bundelt uitsluitend het hierboven afgesproken herstel.
Runtimeversie, add-onmanifest, versietest en add-onchangelog worden samen
bijgewerkt. De zes functionele bronhashes blijven gelijk aan het replaybewijs.
De verse versie-, verpakkings- en architectuurcontroles slagen: 27 tests in
1,06 seconden. Ruff op de gewijzigde versiebron en versietests en
`git diff --check` slagen. Alle zes functionele bronhashes zijn opnieuw gelijk
bevonden aan het replaybewijs. Daarna volgen de bestaande GitHub-controles
op de exacte releasecommit vóór samenvoeging.

De automatische goedkeuringscontrole blokkeerde de eerste push vanwege het
meegeleverde gedetailleerde diagnosebewijs naar de openbare repository. Vóór
publicatie zijn het bewijsbestand en deze samenvatting beperkt tot technische
verificatie. Het volledige replaybewijs blijft lokaal; de functionele bron en
haar geverifieerde hashes zijn ongewijzigd.
