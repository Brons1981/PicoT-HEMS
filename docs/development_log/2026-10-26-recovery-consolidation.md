# Herstelbeslissingen, herstart en incidentreeksen

Status: lokaal, op akkoord van Alex voor de vier voorgestelde verbeterpunten.
Werkbasis: dev.321 plus lokale uitvoeringscontinuiteit en routekeuze-input.
Geen versieophoging, release, Home Assistant-opdracht of notificatie verstuurd.

## 1. Vergelijkbare herstelbeslissingen samenbrengen

`planning_recovery.failed_plan_change_blocks_execution` is nu de gedeelde
beslissing bij vijf afwijzings-/foutpaden in kandidaatgeneratie, selectie en
vastlegging. Het onderscheid blijft expliciet:

| Situatie | Uitkomst bij mislukte wijziging |
| --- | --- |
| Geen behouden plan | Blokkeren; een uitzondering maakt geen plan |
| Noodzakelijke vervanging | Blokkeren tenzij apart tijdelijk fysiek bewijs beschikbaar is |
| Optionele PV-verbetering | Bestaand toegelaten plan behouden |
| Optionele continuiteitsreparatie voltooid dagdoel | Bestaand plan behouden bij afwijzing of mislukte vastlegging |
| Bewezen noodzaak om huidig laden voort te zetten | Bestaande laadactie behouden |
| Ontbrekende waarderingsdekking | Alleen behouden als geen actueel tekort is vastgesteld |

Dit haalt herhaalde beslislogica uit verspreide branches. De criteria die een
wijziging optioneel maken en het fysieke bewijs voor doorladen blijven bestaan.
Bestaande hoofd- en aanvullende doelen, prijsberekening, selectie en
beveiligingsgrenzen veranderen niet. Onopgeloste toekomstdoelen gebruiken nog
steeds de afzonderlijke begrensde fysieke beoordeling uit de eerdere lokale stap.
Er is geen algemene uitzondering gemaakt die een verplichte reparatie optioneel maakt.

## 2. Herstart veilig beoordelen

Een nieuwe CanonicalExecutionRuntime begint met dagelijkse uitvoering geblokkeerd.
Een opgeslagen plan is geen nieuwe uitvoeringsgoedkeuring. Alleen een verse
`live_plan_ready` of `observer_only_plan_ready` kan deze blokkade in apply opheffen;
apply_committed vereist expliciet live_plan_ready. Bestaande guards blijven daarna gelden.
Dit gebruikt de bestaande suspension-state, zonder nieuwe opslagmodus of instelling.

De nieuwe regressie toonde eerst dat een runtime na herstart direct `dispatched`
teruggaf. Na de correctie wacht hij op planning en verstuurt geen opdracht.
De fysieke batterijmodus wordt hiermee niet zelfstandig uitgezet: het gaat om
het verlenen van nieuwe opdrachten. De normale bewaakte terugval blijft beschikbaar.

Laag-niveau tests die bewust een reeds toegelaten plan aan de klokgrens controleren,
zetten die beginsituatie nu expliciet. Hun bestaande asserts zijn behouden.
Werkelijke restartchecks blijven zonder vooraf gegeven toestemming.

## 3. Opeenvolgende incidenten

Nieuwe integratiereeks met echte Candidate/Evaluation, Store en execution-runtime:

1. Ontbrekende verbruiksinvoer veroorzaakt terugval.
2. Geldige actuele invoer behoudt de bewezen huidige actie, terwijl het toekomstdoel openblijft.
3. Gesimuleerde HA-terugmelding bevestigt de modus; een herstart vraagt opnieuw planning.
4. De daggrens bereikt een nieuwe ongebonden laadopdracht. Oud tijdelijk bewijs verloopt.
5. Een nog onhaalbare nieuwe opdracht geeft terugval, zonder fictieve voltooiing.
6. Herstelde fysieke haalbaarheid levert een nieuw geldig plan en uitvoering.

Deze reeks ontdekte een tweede fout: bewijs van 15 minuten kon in het testscenario
vijf seconden voorbij de start van het volgende ongebonden dagdoel vallen.
De geldigheidsgrens is nu het vroegste van: huidige actie-einde, 15 minuten en
start van een nog ongebonden toekomstig dagdoel. Een nieuwe beoordeling is dan vereist.
Dit is een synthetisch aangetoonde grensfout, geen nieuwe claim over de live-diagnose.

Een aanvullende integratietest bewaakt de oorspronkelijke 100%-SOC-situatie:
opstart wacht eerst, verse planning wordt toegelaten, en de werkelijk bevestigde
100% voltooit daarna de juiste opdracht zonder een nieuwe actuatoropdracht.
Alle drie incident-/herstarttests slagen.

## 4. Een meldingsroute

Zie `2026-10-26-single-health-notification-route.md`.
De legacy PlanningFallbackNotifier is verwijderd; HealthNotifier rapporteert na
publicatie van plan en SOC. Oorzaken worden persistent gededupliceerd. Een andere
oorzaak blijft meldbaar, ook als de storing actief bleef. HC/ED behouden hun bestaande
standaardgedrag. Startup-wachten en bewijsverloop zijn geen actuatorfouten en wissen
ook geen echte eerdere actuatorfout. Dashboard/diagnose houden de precieze blocker.

Een reeds bestaande oude Home Assistant persistent notification wordt niet door
code automatisch verwijderd. Er worden geen nieuwe meldingen via die oude route gemaakt.

## Verificatie en grenzen

- Herstarttest eerst rood (`dispatched`), daarna groen (`blocked`, nul opdrachten).
- Tijdgrens eerst rood (bewijs 5 seconden na begin volgend doel), daarna groen.
- Negen tabeltests leggen de gedeelde herstelbeslissing vast.
- Gerichte continuiteits-/hersteltests bewaken de afzonderlijke fysieke regels.
- Gerichte meldings-/publicatietests en uitvoeringsguardtests zijn geslaagd.
- Ruff en mypy voor de zes betrokken productiemodules zijn groen.

Geintegreerde eindsuite: **369 tests geslaagd in 206,71 seconden**. Deze combineert
alle runtime-gebruikende suites met herstelpolicy, continuiteit, routekeuze,
health/publicatie, livepolls en architectuurgrenzen. Geen mislukte test in deze run.
Eerdere lokale HTTP-webtests
waren geblokkeerd door WinError 10013, ook op dev.321. Deze wijziging verandert de
webmodule niet. Volledige release-CI en livewerking zijn niet aangetoond.

Dit is geen verklaring dat alle uitzonderingen of alle ADR 001-037 volledig zijn
afgedekt; het betreft de afgesproken herstelpaden, lifecycle en meldingen.
