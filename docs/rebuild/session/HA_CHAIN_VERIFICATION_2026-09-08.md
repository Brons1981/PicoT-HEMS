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
