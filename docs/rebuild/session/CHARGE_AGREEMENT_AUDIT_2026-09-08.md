# Toets laadopdrachten aan expliciete gebruikersafspraken

Datum: 2026-09-08. Basis lokaal `2264479`, gepubliceerd `123929f32921a6768914ef63f8433b6e3ad233de`, tree `113eace98dbcf509d76a358cfc338f556f690eb5`; branch `implement/first-daily-charge-cycle`, basis dev.243.

## Oordeel

**Niet volledig conform.** De hoofdlaadcyclus is in belangrijke onderdelen aanwezig. Een aanvullende laadopdracht heeft echter geen eigen vastgelegd laaddoel en bewezen voltooiing. Bovendien kan de haalbaarheidseis voor een andere ongewijzigde dagopdracht de huidige optimalisatie blokkeren. Dit zijn geen redenen om de besproken gebruikersroute te vervangen door gezamenlijke wijziging van dagopdrachten.

De laatste expliciete gebruikersafspraken zijn leidend: één blijvende dagelijkse hoofdopdracht naar 100% in de gepubliceerde leveringsdag; optimalisatie met de gunstigste nog uitvoerbare mogelijkheden; aanvullende laadopdrachten om de volgende hoofdlaadsessie te halen, met eigen doel (eventueel 100%) en eigen voltooiing; aanvullende voltooiing telt niet voor het dagdoel. Handel is afzonderlijke energieafname, geen verplichte herstelvoorwaarde voor het hoofdlaadsegment. Technische grenzen blijven gelden.

## Bevindingen en bewijs

| Afspraak | Documentatie | Implementatie en oordeel |
| --- | --- | --- |
| Dagelijkse 100%-hoofdopdracht binnen leveringsdag, zelfde identiteit | ADR-037.2/.4/.7 | Aanwezig. Discovery beperkt eigen segmenten tot de leveringsdag; Store bewaart identiteit en voltooiing. Lokale levenscyclus- en venstertests slagen. |
| PV, hybride en netladen onder dezelfde hoofdopdracht | ADR-037.4/.5 | Aanwezig. Test `test_lost_pv_adds_grid_to_same_goal_and_persists_revision` toetst PV-verlies, netaanvulling, identiteit en restart. |
| Gunstigste nog beschikbare laadmogelijkheid | ADR-037.4 sluit verstreken uren uit | Gedeeltelijk aangetoond: adapter bouwt horizon vanaf actuele snapshot; discovery biedt resterende uitvoerbare starts; Evaluation vergelijkt effectieve laadprijs. Geen verse afzonderlijke doorlopende proef uitgevoerd waarin het eerder goedkoopste venster net verstrijkt. Minimum over gegenereerde kandidaten is geen bewijs van een globaal optimum over elke denkbare route. |
| Aanvullende lading kan minder dan 100% beogen | ADR-037.9: energiebehoefte tot volgende sessie | Laadduur wordt uit tekort berekend, maar een eigen bindend doel voor de aanvullende opdracht ontbreekt. |
| Aanvullende opdracht werkelijk voltooien en zelf afvinken | Niet expliciet uitgewerkt in ADR-037.9 | **Ontbreekt, hoog, hoge zekerheid.** `DailyBridgeState` bevat alleen verwijzing naar volgende hoofdopdracht/plan, volgend begintijdstip en geaccepteerde intervaltekorten. Geen zelfstandig opdracht-ID, laaddoel, voltooiingsstatus of voltooiingsbewijs. |
| Aanvulling voltooit nooit het dagelijkse doel | ADR-037.3/.4/.9 | Aanwezig: aanvullende segmenten hebben geen `main_assignment_id`; Store weigert daarmee dagelijkse voltooiing. Test `test_bridge_full_measurement_cannot_complete_next_main_goal` slaagt. Die test bewijst niet de ontbrekende eigen voltooiing. |
| Dagopdrachten mogen elkaar niet blokkeren omdat de andere ongewijzigd onhaalbaar is | Gebruiker heeft gezamenlijke wijziging als vervolgrichting gecorrigeerd | **Niet conform, hoog, hoge zekerheid over mechanisme.** Pipeline kiest `triggers[0]`; adapter eist vervolgens dat alle andere open hoofdopdrachten in hun ongewijzigde segmenten 100% halen. Zie hieronder. |
| Marktactie afzonderlijk, energie-effect eenmaal meenemen | ADR-019.1/.2: batterij-export, geen fictief huisverbruik; optionele hersteltoets | De nieuwe dagelijkse keten implementeert deze user-rule nog niet. Zij neemt bij dagelijkse context een vroege afslag naar `_build_daily_main_run`; oude marktcode verderop is geen bewijs van integratie. Geen markt-herstelblokkade als oorzaak van de aangetroffen tweedaagse blokkade aangetoond. |

### Aanvullende opdracht: uitvoeringssegment is geen doelregistratie

Bronnen: `src/picot/v2/daily_bridge.py` (`DailyBridgeState`, `DailyBridgeTrigger`), `src/picot/v2/plan_commitment_store.py` (`bind_daily_main_plan`, `load_daily_bridge_state`, `observe_daily_main_completion`), `src/picot/v2/canonical_execution_runtime.py` (`_observe_daily_completion`) en `src/picot/planner/mep_candidate_outcomes.py` (supplemental PathSegment-projectie).

De Store bewaart overbruggingsinformatie onder de volgende hoofdopdracht. Het uitvoeringssegment heeft wel een segment-ID en `bridge:`-doelomschrijving, maar dat is geen zelfstandig overbruggingscommitment. `target_wh` in de trigger bevat de batterijcapaciteit voor de simulatie; het bewijst geen gekozen aanvullend SOC-doel. De segmenten krijgen de algemene minimum-/maximum-SOC-grenzen. De runtime roept uitsluitend dagelijkse voltooiing aan, die aanvullende segmenten expliciet uitsluit. Zo wordt het dagdoel terecht beschermd, maar kan het aanvullende doel niet afzonderlijk bewezen en duurzaam afgevinkt worden.

ADR-037.9 beschrijft vasthouden, eigen segmentidentiteit en atomaire opslag van de gekozen overbrugging, maar werkt de eigen doel-/voltooiingslevenscyclus niet uit. De door de gebruiker bedoelde afspraak is dus onvolledig vertaald naar documentatie én implementatie. Bestaande geaccepteerde ADR-bestanden blijven bevroren; een volgende gekoppelde precisering kan dit vastleggen zonder de oorspronkelijke afspraak opnieuw te laten bedenken.

### Dagoverschrijdende blokkade

Bronnen: `mep_canonical_pipeline.py::_build_daily_main_run` en `independent_daily_reference_adapter.py::main_charge_windows`.

Vers geïnspecteerde code kiest één tekorttrigger en filtreert diens kandidaten op 100% in de andere ongewijzigde hoofdsegmenten. De vorige toets reproduceerde twee tekorttriggers en voor beide afzonderlijke revisies nul vensters met `retained_main_goal_requires_explicit_optimisation`. Deze reproductie is historisch bewijs uit de onmiddellijk voorgaande toets, niet opnieuw uitgevoerd in deze toets. De code op dit punt is ongewijzigd. De eerdere proef bewijst niet dat een gezamenlijke oplossing in die specifieke fixture fysiek haalbaar was.

**Correctie van de eerder vastgelegde vervolgrichting:** gezamenlijke wijziging van beide dagopdrachten is niet het overeengekomen herstel. Die aanbeveling in `HA_CHAIN_VERIFICATION_2026-09-08.md` en het voorgaande log wordt door de expliciete gebruikerscorrectie en deze toets ingetrokken. De volledige route en haar SOC-effect blijven simulatie-input, maar zelfstandige opdrachtoptimalisatie mag niet worden geblokkeerd door de eis dat een andere bedreigde route zonder haar eigen optimalisatie al voldoet. Niet simpelweg alle fysieke haalbaarheidstoetsen verwijderen; dat zou een ander defect introduceren.

## Verse controles

- `python -m pytest tests/test_daily_bridge_pipeline.py tests/test_daily_main_route_optimisation.py tests/test_daily_ha_completion_recovery.py tests/test_daily_charge_assignment.py -q`: **54 passed in 54,07 s**, exit 0.
- `python -m pytest tests/test_daily_main_charge_windows.py tests/test_daily_main_charge_selection.py -q`: **27 passed in 20,10 s**, exit 0.

Deze tests bewijzen geselecteerde bestaande gedragingen. Geen ervan bewijst een eigen voltooiingslevenscyclus voor aanvullende laadopdrachten. Groen heft de geconstateerde contractgaten niet op. Geen nieuwe tests of productiecode gewijzigd, geen volledige HA-replay, CI_VERIFIED of LIVE_VERIFIED.

## Gerichte vervolgscope

1. Bestaande afspraken volledig vastleggen: zelfstandige aanvullende laadopdracht met behouden identiteit, expliciet eigen doel, toegestane routeoptimalisatie en werkelijk voltooiingsbewijs; los van dagdoel.
2. Deze levenscyclus door de bestaande kandidaat-, plan-, Store- en uitvoeringsketen realiseren. Algemene uitvoeringssegmenten of geaccepteerde netondersteuning niet zonder bewijs als voltooide laadopdracht markeren.
3. De te strenge koppeling tussen dagopdrachten gericht corrigeren, met een fysiek haalbare tweedaagse regressie en behoud van volledige SOC-projectie. Geen gezamenlijke herdefinitie van dagopdrachten.
4. Afzonderlijke user-rule-marktroute blijft vervolgwerk; geen hersteltoets terug invoeren via de laadcyclus.

Deze beurt is uitsluitend een toets. Geen implementatie, versie-bump, merge, deployment of batterijcommando.
