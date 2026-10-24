# HC: extra laden vergelijken en leren op weer

Deze wijziging bouwt voort op de geïntegreerde dev.314-boom met de CV-keten. Geen commit, push, release of live apparaatbediening uitgevoerd.

## Extra laden in de vergelijking

HEMS beoordeelt maximaal vijf generieke HC-profielen. Een vervangingsprofiel dat niet op de bestaande laadroute past, kan nu een aanvullende berekening krijgen via de gewone planner: dagdoeltekort of tekort tot de volgende laadsessie, bestaande kandidaatopbouw en Evaluation. Deze berekening schrijft geen plannen en stuurt geen apparaten aan. Ze gebruikt dezelfde conversieverliezen, PV-basis, prijsafrekening en fysieke beperkingen.

De vergelijking houdt dezelfde prognoseperiode, minstens dezelfde eindvoorraad en de bestaande exportafspraken aan. Ook de daadwerkelijke levering van het geplande exportvolume wordt getoetst. Gas-/andere niet-elektrische kosten tellen mee in de totale vergelijking. Het antwoord geeft de aanvullende netlaadenergie aan. Een niet-ondersteunde kandidaat mag een ander bruikbaar alternatief niet blokkeren.

## Reservering vóór toestemming

Een gekozen profiel dat een andere laadroute nodig heeft, krijgt requires_route_commitment. HC kan die keuze bevestigen en de vraag reserveren; HEMS bewaart deze keuze uitsluitend als reservering. Er wordt geen starttoestemming gepubliceerd. Ook na herstart accepteert dit record geen uitvoeringsmelding.

De bestaande reserveringsverwerking brengt de gekozen vraag in de echte huishoudprognose. De gewone planner kan daarop een route vastleggen met de bestaande eigendoms- en commitmentregels. Pas een nieuwe beoordeling van het profiel op de daadwerkelijk vastgelegde route kan starttoestemming geven. Een gecachte voorlopige beoordeling kan dat nooit doen. De oorspronkelijk beloofde eindvoorraad wordt met haar tijdstip in de reservering bewaard. Een generiek opslagcheckpoint in Planning Input en kandidaatvalidatie voorkomt dat de echte planner een route met een lagere beloofde reserve kiest. MEP ontvangt alleen opslagbereik, tijdstip en Wh, geen apparaatkennis. Het checkpoint telt mee in de planningssignatuur; verlopen checkpoints worden niet opnieuw opgelegd. Intrekking en het verlopen van reserveringen blijven volgens de bestaande regels werken; een vastgelegde batterijroute wordt niet buiten die regels verwijderd.

## Weerleren beneden

HC gebruikt de bestaande weerentiteit voor verse wind en bewolking en sun.sun voor dag/nacht. Deze context blijft bij gemeten afkoeling, opwarming en handhaven opgeslagen. Alleen vergelijkbare omstandigheden leveren onderbouwing voor een advies. Zonder voldoende passende metingen blijven voorlooptijd en verlaging voorzichtig. De interface toont de gebruikte context.

Zie ook 2026-10-24-hc-weather-learning.md voor invoervalidatie, grenzen en concrete tests.

## Grenzen

- Extra laden wordt alleen onderzocht bij tekorten waarvoor de gewone planner al een toegestane herstelroute heeft. Dit is geen algemene zoekopdracht naar alle mogelijke goedkope bijlaadmomenten.
- Alleen een lagere eind-SOC zonder zo'n tekort start geen nieuwe laadroute. Zo'n profiel blijft afgewezen. Meerdere opeenvolgende hypothetische dagreparaties worden niet beloofd; actieve externe-lastpolicy sluit deze aanvullende berekening uit.
- Een oorspronkelijk ongeldige batterijroute blijft eerst herstel vereisen. Deze uitbreiding verbergt zo'n fout niet als verwarmingsalternatief.
- Weerleren gebruikt waarnemingen, geen voorspelling van wind/bewolking per uur. De bestaande dagelijkse verwachting is daarvoor onvoldoende nauwkeurig.
- CV-hulpverbruik blijft expliciet geschat. Geen echte woningproef, browserproef of volledige repositorybrede typecheck uitgevoerd.

## Verificatie

De nieuwe ketentest gebruikt echte profielopslag, reservering, prognosevervanging en de gewone planner: voorlopige keuze → reserveren → andere route vastleggen → opnieuw beoordelen → starttoestemming. Andere tests controleren kostenvergelijking met een niet-elektrisch alternatief, herstartbeveiliging en geïsoleerde afwijzing van een niet-ondersteunde kandidaat.

De eerste gecombineerde reeks telde 502 geslaagde tests en 13 subtests. Een aanvullende ketentest met behoud van de oorspronkelijke reserve toonde vervolgens dat de normale planner een andere route met lagere eindvoorraad kon kiezen. Dit is hersteld met het generieke opslagcheckpoint en onafhankelijke controle vóór start. De definitieve gecombineerde testuitslag na deze correctie wordt hieronder vastgelegd.


### Definitieve uitslag, 24 oktober 2026

- Gecombineerde regressiereeks na de reservecorrectie: **520 tests en 13 subtests geslaagd**, 247,82 seconden, exitcode 0. Inclusief extra kandidaat-/plannertests voor de generieke reservevoorwaarde.
- Gerichte ketentest: reserveren, SQLite-herstart, planning met reservecheckpoint, daadwerkelijk vastleggen, herbeoordelen en starttoestemming; een hogere niet-gehaalde reserve wordt afgewezen.
- Proef met vijf voorwaardelijke alternatieven op dezelfde synthetische etmaalbasis: alle vijf berekend, één gekozen; 1,25 seconde. Dit is geen prestatiegarantie voor de NUC of elke prognose.
- Ruff op nieuwe en gewijzigde moderne modules/tests geslaagd; F-controles op de betrokken bestaande grote modules geslaagd. JavaScript-syntaxcontrole geslaagd. Alle manifestbestanden aanwezig en Python-syntaxis gecontroleerd.
- De functie _restore_daily_charge_context blijft AST-identiek aan de dev.314-nachtreparatie.
- De ketentest gebruikt één simulatietijdstip met een vernieuwd voorstel en werkelijk gewijzigd vastgelegd plan; een complete live cyclus met voortschrijdende tijd/nieuwe HA-snapshots is niet uitgevoerd. Geen release of live aansturing.


### Vervolg

Alleen-eindreserve-tekorten en optionele uurverwachtingen zijn vervolgens aangesloten. Zie 2026-10-24-hc-reserve-completion.md voor de actuele implementatie en de gecombineerde uitslag van 607 tests plus 13 subtests.
