# HA-ketenverificatie — 2026-09-08

Doel: de nieuwe dagelijkse laad-/overbruggingsketen toetsen op het verschil tussen lokale tests en werkelijke HA-invoer.
Getoetste code: lokale commit `f63d78e`, gepubliceerd als `c1cb768d646e3fd6571d1d1341f1e1ed00702aac`, tree `aae826f42b26e266098866876cb4c3cb6ff5caac`, branch `implement/first-daily-charge-cycle`.

## Oordeel

**Geen live-vrijgave.** Twee reproduceerbare tekortkomingen in de overgang van HA-waarnemingen naar plannerbewijs. De bestaande 23 gerichte tests slagen, maar de aanvullende reproducties tonen ontbrekende dekking. Er is geen werkelijke HA-installatie aangestuurd en geen volledige HA-replay als geslaagd aangemerkt.

## 1. Hoog: 100% bij aanvang kan onafgevinkt blijven

Eis: ADR-037.5 staat voltooiing toe wanneer de batterij bij de start van het hoofdsegment aantoonbaar 100% is. Een onveranderde HA-toestand hoeft geen nieuwe meettijd te krijgen.

Betrokken code: `CanonicalExecutionRuntime._observe_daily_completion` legt bij eerste modusbevestiging `confirmed_since` op de huidige opnametijd. `ActivePlanCommitmentStore.observe_daily_main_completion` vereist vervolgens `confirmed_since <= measured_at`. Een 100%-meting op segmentstart wordt daardoor afgewezen als de eerste bevestiging een seconde later komt. Een herhaalde huidige toestand met dezelfde meettijd blijft afgewezen.

Gerichte reproductie met de bestaande canonical pipeline, Store en klokruntime, zonder echte dispatcher:

| Situatie | Modusresultaat | SOC | Meettijd | Dagdoel voltooid |
| --- | --- | --- | --- | --- |
| Eerste bevestiging één seconde na hoofdstart | already_active | 100% | hoofdstart | nee |
| Tweede bevestiging zestig seconden na hoofdstart | already_active | 100% | dezelfde hoofdstart | nee |

De fixture levert expliciete testcapabilities; dit is een lokale reproductie van het meettijdgedrag, geen bewijs van historische uitvoering van het nieuwe plan in HA.

Het diagnosearchief onderbouwt dat het invoerpatroon reëel is: 18 uitgebreide dev.243-polls rapporteren SOC 100%, verdeeld over slechts twee verschillende `observed_at`-waarden. De tijd tussen poll en SOC-waarneming loopt in die subset op tot 7729,274639 seconden. Dit is op zichzelf geen bewijs dat de sensor defect of de waarde ongeldig was; een gelijkblijvende toestand houdt in HA vaak haar tijdstempel. Het archief bewijst evenmin dat deze nieuwe code toen actief was.

Richting voor herstel: scheid de oorspronkelijke SOC-meettijd van bewijs dat een geldige HA-toestand op de hoofdsegmentgrens nog van toepassing is. Koppel dat bewijs aan de juiste opdracht en uitvoerings-/moduscontext. Geen meettijd verversen alsof opnieuw gemeten is, geen forecast-voltooiing, geen afvinken door overbrugging en geen omzeilen van handmatige of veiligheidsblokkades. Voeg een ketencontrole toe met werkelijk onveranderde SOC-tijd, plus restart en latere modusbevestiging.

## 2. Middel: tijdelijke PV-historiefout blijft voor hetzelfde tijdvak gecachet

Eis: ADR-037.8 laat ontbrekend historisch bewijs later aanvullen. De oorspronkelijke forecastreferentie blijft daarbij vast en nieuwe daadwerkelijke meetinhoud moet beoordeelbaar worden.

Betrokken code: `LivePVActualCache` en `apply_latest_closed_actual_pv` in `src/picot/v2/live_pv_actual.py`. De cache gebruikt alleen entiteit en tijdvakgrenzen als sleutel. Ook een onbeschikbaar resultaat wordt bewaard; dezelfde sleutel veroorzaakt geen nieuwe historieopvraag. Een gecorrigeerde bron of herstelde beschikbaarheid wordt daardoor voor dat tijdvak niet opnieuw gelezen.

Gerichte reproductie met de bestaande live-PV-koppeling:

| Stap | Bron beschikbaar | Historieaanroepen totaal | ACTUAL-intervallen | Cache-hit |
| --- | --- | --- | --- | --- |
| Eerste aanvraag | nee | 1 | 0 | nee |
| Dezelfde periode na bronherstel | ja | 1 | 0 | ja |
| Dezelfde periode met nieuwe cache | ja | 2 | 1 | nee |

Dit bewijst vasthouden van de fout zolang de cache-sleutel gelijk blijft. Een nieuw gesloten forecastinterval kan die sleutel veranderen en alsnog een aanvraag veroorzaken; er wordt dus geen onbeperkte blokkade over alle volgende tijdvakken geclaimd. Ook geldige later gecorrigeerde historie kan voor dezelfde sleutel ongezien blijven. De reproductie toont de huidige code-eigenschap, niet dat dit de oorzaak van een specifieke dev.243-avond was.

Richting voor herstel: onderscheid ontbrekend/tijdelijk mislukt bewijs van stabiele geldige historie en maak bronherstel/correcties via de bestaande meetketen opnieuw leesbaar. Behoud begrensde historieopvragen en inhoudelijke deduplicatie in de planner. Geen nieuw PV-plannerpad, onbeperkt pollen of willekeurige nieuwe tijdsdrempel invoeren om dit te maskeren.

## Beschikbaar historisch bewijs en grenzen

Bron: `picot-diagnostics - 2026-09-07T212500.492.zip`, door gebruiker aangeleverd.

- Planningsincidentgeschiedenis: 193 regels, waarvan 115 basisregels en 78 uitgebreide pollrecords.
- Uitgebreide dev.243-polls: 41, van 2026-09-07 07:18:11,813714 UTC tot 16:51:37,214424 UTC.
- Modusovergangen: 134 regels, eindigend op 2026-09-07 15:37:19,287013 UTC.
- Huishoudelijke vermogenshistorie: 28451 regels, eindigend op 2026-09-07 19:23:39,521840 UTC.
- Er zijn prijs-/Solcast-entiteitsgegevens, bronwaarnemingen en oude planningsuitkomsten. De uitgebreide pollrecords bevatten geen volledig origineel `PlanningInputSnapshot` of expliciete `capability_snapshot_set`.
- De oude Store bevat alleen `commitments` en `schema_version`; de nieuwe dagelijkse opdracht-/PV-basis-/brugregistratie bestond daar nog niet.
- De bestaande `dev243_snapshot_and_conversion`-fixture is expliciet een numerieke subset met testcapabilities. Daarmee kan planningslogica worden onderzocht, maar niet worden bewezen dat alle oorspronkelijke HA-capabilities, toestandsovergangen, herstarts en uitvoeringsbevestigingen correct worden hersteld.

Daarom geen volledig gereconstrueerde of live-uitgevoerde nieuwe hoofdroute presenteren op basis van dit archief. Het is wel geschikt om echte invoerpatronen en gerichte ketenproblemen aan te tonen.

## Uitgevoerde controles

- Inspectie van archiefschema, tellingen, versie-/tijdgrenzen en SOC-tijdstempels, zonder bestanden in het archief te wijzigen.
- Twee afzonderlijke lokale reproducties via bestaande productie-ingangen en bestaande fixturehelpers. Alleen tijdelijke Store; geen productie- of testbron gewijzigd.
- `python -m pytest tests/test_v2_live_pv_actual_coupling.py tests/test_v2_pv_actual_intervals.py tests/test_daily_main_active_pipeline.py -q`: **23 passed in 19,15 s**.
- De huidige voltooiingstest wijzigt de SOC-meettijd expliciet na de eerste modusbevestiging; hij bewijst daardoor niet het ongewijzigde-HA-tijdgeval hierboven. De bestaande cachetest bewijst hergebruik van geldige historie, niet herstel van een eerder mislukt resultaat.

## Vervolg

Eerst deze twee concrete invoer-/bewijsovergangen herstellen binnen de geaccepteerde ADR's en met passende regressies. Daarna opnieuw de HA-keten beoordelen. De geaccepteerde plannerregels blijven behouden; er is geen reden gevonden om ze met nieuwe gedragsdrempels te vervangen. Een echte live-verificatie vereist daarnaast actuele gegevens en uitvoeringsbewijs van de nieuwe ontwikkelversie in HA.

## Vervolg — herstel na expliciet gebruikersakkoord

Beide hierboven beschreven reproducties zijn in de aansluitende herstelstap lokaal opgelost. De oorspronkelijke bevindingen blijven als historische verificatie van de genoemde basiscommit staan.

- De SOC-ingang bewaart de werkelijke succesvolle HA-leestijd apart van `last_updated` en `last_changed`. De runtime kan daarmee, bij bevestigde toegestane uitvoering, aantonen dat 100% al op de oorspronkelijke hoofdsegmentstart gold. De oorspronkelijke meettijd blijft ongewijzigd; voltooiing wordt geregistreerd op de actuele leestijd, niet achteraf op een verzonnen meetmoment. Bewijs en tijden worden in Store en diagnose vastgelegd. Ontbrekende bewijsvelden in oudere snapshots geven geen nieuwe bevoegdheid.
- Mislukte en onvolledige PV-historie worden niet als herbruikbaar eindresultaat gecachet. De volgende gewone poll mag dezelfde begrensde periode opnieuw lezen. Volledig geldig resultaat wordt weer gecachet. Er is geen extra pollinglus of nieuwe wachttijd. Het herleesbeleid voor reeds volledig geldige maar later gecorrigeerde historie blijft gekoppeld aan de bestaande cache-/tijdvakvernieuwing; deze gerichte fix introduceert geen onmiddellijke detectie van iedere broncorrectie.
- Verse lokale controles: 134 regressietests geslaagd; vervolgens 31 gerichte tests voor nieuwe voltooiingsbewijzen, diagnoseopslag en live-PV-koppeling geslaagd. Vier aanvullende bestaande invoer-/assemblagetests geslaagd. De sets overlappen. Type- en lintcontroles geslaagd.

Dit is **IMPLEMENTED en lokaal geverifieerd**, geen LIVE_VERIFIED. De beperkte beschikbaarheid van originele HA-capabilitysnapshots en bewijs van de werkelijk draaiende nieuwe versie blijft bestaan. Ook gevallen waarin 100% pas tijdens een onbevestigde/offline periode ná hoofdstart ontstond zijn niet door dit specifieke vol-bij-start-bewijs automatisch toegelaten.

## Herbeoordeling — twee gelijktijdige hoofdtekorten

Getoetste basis: lokale commit `fdf854d`, gepubliceerde commit `7f0bde0adc2c245541120db4be9ba59f942f9fba`, tree `7fcfd1c20e8fd7e97b51f286534113824b62ac9f`.

**Oordeel: gedeeltelijk geverifieerd; volledige live-vrijgave nog niet onderbouwd.** De twee eerdere herstelpunten slagen opnieuw. De reeds bekende beperking bij meerdere onhaalbare hoofdopdrachten is nu rechtstreeks gereproduceerd.

- Verse uitvoering: `python -m pytest tests/test_daily_ha_completion_recovery.py tests/test_v2_live_pv_actual_coupling.py tests/test_daily_main_route_optimisation.py tests/test_daily_main_horizon_retention.py -q`: **39 passed in 38,88 s**, exit 0.
- Afzonderlijke tijdelijke reproductie gebruikt de bestaande tweedaagse fixture, echte lokale Store, beide gebonden hoofdopdrachten en het tweede plan als actief plan. Een volgende snapshot heeft SOC 10% en nul voorspelde PV. `main_route_shortfalls` levert twee fysieke tekorttriggers. `main_charge_windows` levert voor zowel 2026-09-07 als 2026-09-08 nul vensters, met reden `retained_main_goal_requires_explicit_optimisation`. Exit 0; geen productie-/testbestanden of live systeem gewijzigd.
- Mechanisme: `_build_daily_main_run` in `mep_canonical_pipeline.py` kiest alleen `triggers[0]`; `IndependentDailyReferenceAdapter.main_charge_windows` vereist dat alle andere open hoofdopdrachten in hun behouden segmenten haalbaar zijn. De huidige keten kan niet in één kandidaat en atomaire binding beide getroffen routes aanpassen. Nul vensters leidt in de runtime tot geblokkeerde planning en de bestaande bewaakte NOM-terugval, met behoud van de opgeslagen plannen. De tijdelijke reproductie oefent de adapter uit; de runtimegevolgtrekking volgt uit broninspectie.
- Ernst: hoog voor een algemene vrijgave van de dagelijkse planner; hoge zekerheid over de gereproduceerde afwijzing. Deze proef bewijst niet dat een gezamenlijke oplossing in precies deze fixture fysiek haalbaar is, en evenmin dat dev.243 hierdoor historisch faalde. Hij bewijst wel dat afzonderlijk herstellen hier geen voortgang oplevert en dat gezamenlijke haalbaarheid niet wordt onderzocht.

Eerstvolgende implementatiestap: gezamenlijke tekortcorrectie binnen dezelfde bestaande Candidate → Evaluation → Plan Builder → Store-keten. Alle getroffen oorspronkelijke dagidentiteiten en bewezen voltooiingen behouden; alleen expliciet getriggerde routes mogen wijzigen. Kandidaten moeten alle open doelen toetsen. Planversies, oorspronkelijke uitvoeringsreferenties en actieve pointer moeten samen atomair worden vastgelegd. Geen selectie op toevallige opdracht-ID-volgorde, geen tijdelijk ongeldige tussenplannen en geen tweede planner. Vereiste checks: twee afzonderlijk haalbare maar samen bedreigde hoofdopdrachten, behoud van een derde onaangetaste opdracht waar toepasselijk, herstart/schrijffout en werkelijk onhaalbare gezamenlijke situatie.

De marktroute blijft afzonderlijk vervolgwerk. CI_VERIFIED en LIVE_VERIFIED zijn niet vastgesteld; geen versie-bump, merge of deployment.

## Herbeoordeling na ADR-037.10 en interdag-correctie — eindmeting bij overgang

Basis: lokale commit `737da21`, gepubliceerd `bf4a9d86175f3595c7fa58b335d93d21fb6c9320`, tree `8e354360d16b6eaef2a8357cbf1ac9ac6e5b237d`; ontwikkelbranch `implement/first-daily-charge-cycle`. De gebruiker vroeg de volgende stap; overeenkomstig het ontwikkellog is de uitvoeringsgrens read-only getoetst.

**Oordeel: gedeeltelijk geverifieerd, nog geen volledige live-vrijgave.** De interdag-blokkade en aanvullende opdrachtlevenscyclus slagen in de bestaande lokale controles. De reeds eerder benoemde grens rond laat ontvangen eindmetingen is nu ook bij aanvullende opdrachten concreet gereproduceerd.

| Waarneming | Actuele bevestigde primitive | Runtime | SOC bereikt aanvullend doel | Aanvullend doel afgevinkt |
| --- | --- | --- | --- | --- |
| Eén seconde vóór einde laadsegment | charge_at_power | already_active | nee | nee |
| Eén seconde ná einde; SOC-meettijd exact op einde | balance_bidirectional | already_active | ja | nee |

De tijdelijke reproductie gebruikt de bestaande `charged`-fixture, werkelijke lokale Store, dezelfde CanonicalExecutionRuntime over beide waarnemingen, passende testcapabilities/modusmapping voor elk actueel segment, en een testdispatcher. Beide definitieve runtime-uitkomsten hebben geen failure_reason. Er zijn geen echte batterijcommando's verstuurd. Een eerste variant hield alleen de mapping van de vorige primitive beschikbaar en werd daardoor technisch geblokkeerd; dat was onvoldoende bewijs van deze overgang. De bovenstaande definitieve variant heeft voor beide actuele segmenten geldige mapping en bevestiging en reproduceert het open blijven zonder die blokkade.

### Mechanisme en gevolgen

`CanonicalExecutionRuntime.advance_committed_boundary` bewaart de vorige bevestiging tijdelijk, maar selecteert het segment op de huidige uitleestijd. Bij de volgende modus wordt voltooiing alleen voor dat nieuwe segment beoordeeld. De meting met tijdstip op de vorige segmentgrens wordt niet aan de vorige aanvullende opdracht aangeboden. `ActivePlanCommitmentStore.observe_supplemental_completion` verlangt daarnaast `observed_at <= segment.ends_at`; een later ontvangen meting kan dus ook via deze ingang niet worden geregistreerd voor het afgelopen segment. De planningscode hoeft voor deze oorzaak niet te veranderen.

Ernst: hoog voor betrouwbare doelregistratie bij een algemene live-vrijgave; hoge zekerheid over het gedemonstreerde niet verwerken van eindmetingen. Dit is geen bewijs dat iedere laat ontvangen meting automatisch geldige voltooiing oplevert. De synthetische moduswaarnemingen begrenzen een overgang, maar vervangen geen werkelijke HA-modushistorie. De huidige keten heeft nog geen afhandeling om afsluitend bewijs bij de vorige uitvoering te beoordelen. Een gefingeerde verse meettijd, alleen verstreken tijd, een dispatch-ack of de nieuwe modus als bewijs voor oude uitvoering gebruiken is geen geldige oplossing.

Gevolg: een opdracht kan onbewezen blijven terwijl een uitlezing vlak na het venster het doel op de eindtijd rapporteert. Bij een aanvullende opdracht blijft dit zichtbaar als open of later onbewezen voorbij de benodigde tijd. Geen feitelijke herhaalde lading of historische HA-fout als gevolg geclaimd; die vervolgeffecten zijn niet in deze proef onderzocht.

### Verse controles en vervolg

`python -m pytest tests/test_supplemental_charge_commitment.py tests/test_daily_ha_completion_recovery.py tests/test_daily_independent_shortfalls.py -q`: **23 passed in 52,62 s**, exit 0. Deze tests bewijzen hun bestaande binnen-segment-/startbewijs en dagelijkse revisies; zij omvatten niet de bovenstaande overgangsreproductie. De afzonderlijke definitieve tijdelijke reproductie eindigde met exit 0 en de twee gerapporteerde already_active-uitkomsten, zonder voltooiing.

Eerstvolgende gerichte herstelstap: afsluitend SOC-/uitvoeringsbewijs van het vorige segment beoordelen wanneer een gewone HA-uitlezing een overgang constateert. Oorspronkelijke meettijd en opdracht-/plan-/segmentreferenties behouden, beide voltooiingssoorten gescheiden houden en de bestaande uitvoeringsguards handhaven. Bewijs moet expliciet aantonen wat werkelijk bij de vorige uitvoering hoort; bij onvoldoende bewijs open laten en de reden tonen. Geen nieuwe plannerregel of willekeurige tolerantieperiode toevoegen.

Alleen rapport en ontwikkellog gewijzigd. Geen productiecode, tests, bevroren ADR's, configuratie of versie gewijzigd. Geen CI_VERIFIED of LIVE_VERIFIED, merge of deployment.

## Implementatie afsluitend bewijs — lokaal geverifieerd

Na akkoord is de hierboven gereproduceerde grens gericht aangepakt in de bestaande uitvoeringsruntime en Store. Een eindmeting kan aan het vorige hoofd- of aanvullende segment worden aangeboden met de oorspronkelijke meettijd en expliciet uitvoeringsbewijs. De HA-moduswisseltijd en plannerprovenance begrenzen dit bewijs. Alleen een nieuwe modus, dispatchbevestiging of verstreken tijd volstaat niet. Zonder eerdere bevestiging na herstart blijft het doel onbewezen; er wordt geen historische uitvoering verzonnen.

De gewone livepoll leest na geregistreerde voltooiing de invoer opnieuw voordat planning plaatsvindt. Opslaguitval blokkeert de overgang en laat herverwerking toe. Beide doelsoorten blijven gescheiden.

Controles: brede set **58 passed in 62,05 s**, daarna definitieve gerichte set inclusief opslaguitval **12 passed in 26,26 s**; aantallen overlappen. Gedekt zijn vertraagde ontvangst, een nog latere poll, een te late meettijd, hoofd- en aanvullende voltooiing, passend/ontbrekend/te vroeg moduswisselbewijs, handmatige blokkade, restart zonder bewijs en verse input vóór planning.

Dit sluit de gedemonstreerde lokale fout met voldoende overgangsbewijs. Het is geen volledige HA-replay of live-vrijgave. Werkelijke beschikbaarheid en samenhang van HA-modusmetadata en plannerprovenance moeten nog in de integratie worden vastgesteld. Bevroren ADRs en plannerbeleid zijn niet gewijzigd.

## Vervolg: vertraagde modusfeedback

De vervolgcontrole reproduceerde dat één oude HA-modusterugmelding na een planner-aanvraag een blijvende handmatige blokkade activeerde. Dit bewijst de lokale fout bij deze volgorde, niet dat deze in de historische dev.243-diagnostiek daadwerkelijk optrad.

Na akkoord is uitsluitend de bestaande provenance-overgang aangepast. De werkelijke HA-wisseltijd moet aantonen dat de voorafgaande modus ongewijzigd is gebleven. Dan blijft de aanvraag wachten op feedback, ook na herstart. Een nieuwe of afwijkende wijziging en ontbrekend bewijs behouden de conservatieve blokkade. De bestaande reset blijft vereist voor een werkelijke override. Aanvraag/terugmelding worden niet als bewijs van fysiek SOC-doelbereik behandeld.

De nieuwe gerichte tests dekken opslag/herstart en raw HA-metadata via de bestaande input-attachment. De volledige gecombineerde dispatch-/SOC-volgorde en echte HA-uitvoering zijn hiermee nog niet als LIVE_VERIFIED aangemerkt. Plannerbeleid en bevroren ADRs blijven ongewijzigd.

Definitieve geïntegreerde regressie: `python -m pytest tests/test_pending_mode_feedback.py tests/test_v2_storage_mode_provenance_integration.py tests/test_v2_live_storage_mode_provenance.py tests/test_charge_segment_closure.py tests/test_v2_zendure_mode_capabilities.py tests/test_v2_live_replan_poll_cycle.py -q`: **52 passed in 28,37 s**, exit 0. `git diff --check` geslaagd.
