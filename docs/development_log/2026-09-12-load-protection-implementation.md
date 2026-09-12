# 2026-09-12 — Belastingbescherming geïmplementeerd

Status: lokaal op dev.257; geen commit, push, release of aansturing uitgevoerd.
Autorisatie: Alex: “oke dan passen we de nieuwe fix toe”.
Besluit: ADR-037.15. Dev.254 blijft pre-stable met de vaste stopregel.

## Gedrag

- Planning Input berekent een tijdgewogen vijfminutenafwijking van de historische
  huisvraag. Vanaf 500 W extra telt de positieve afwijking vijftien minuten mee.
  Historische kwartieren en weging blijven gelijk; geen apparaatprofielkoppeling.
- Vrijgave na vijf minuten betrouwbaar actueel verschil <=250 W. Samples zijn
  maximaal 180 seconden geldig; laatste betrouwbare gemiddelde maximaal vijf
  minuten. Daarna onbekend zonder voortgezette energie-extrapolatie.
- Bestaande route en alle nieuwe kandidaten gebruiken dezelfde aangepaste invoer.
  Het einde van de vijftien minuten blijft een echte simulatiegrens.
- Lopende hoofd-netlaadblokken worden bij actieve/onbekende belasting niet
  onderbroken of uitgesteld door nieuwe kandidaten. Behoud geldt tot het eigen
  blokeinde; werkelijk 100% of vrijgegeven belasting heft de bescherming op.
- Als alleen die continuïteitsvoorwaarde alle kandidaten uitsluit, blijft het
  bestaande toegelaten blok actief. Het tekort blijft in de diagnose zichtbaar;
  geen onbedoelde NOM-terugval. Uitvoeringsvalidatie blijft bestaan.
- Tekorten <=0,5 procentpunt mogen uitsluitend wachten met een simulatiebewijs
  dat herstel vanaf vijftien minuten later nog 100% binnen het bestaande
  hoofdvenster bereikt en de reserve respecteert. Anders direct strikt toetsen.
  Werkelijk SOC en voltooiing worden nooit fictief verhoogd.
- Diagnostiek bewaart de belastingstatus. Wijzigingen in belasting tellen mee
  in de inhoudelijke beoordelingsidentiteit; polltijd alleen niet.

## Verificatie

Met tijdelijke testafhankelijkheden onder /tmp, zonder repositorydependencywijziging:

- Brede repositoryrun: `python -m pytest -q`: 1.514 geslaagd (246,82 s).
- Na definitieve integratiecorrecties: 16 gerichte tests geslaagd in de vier
  bestanden test_daily_main_load_protection, test_household_load_guard,
  test_household_load_guard_adapter en test_daily_main_route_optimisation.
  Inclusief de twee later toegevoegde integratieregressies.
- Ruff op v2 en de drie nieuwe testbestanden: schoon.
- Mypy op v2: 74 bestanden schoon met eigen tijdelijke cache. Eén tussentijdse
  run gaf een interne mypyfout; de geïsoleerde definitieve run slaagde.
- `git diff --check`: schoon.
- Replay met de productieadapter op alle 35 oorspronkelijke middagtoestanden:
  alle zeven verminderingen tijdens EV-belasting geblokkeerd, inclusief 15:13.
  Om 15:58 is de bescherming weer vrijgegeven en vermindering weer mogelijk.
  Resultaat: 12 herstelbeslissingen, 22 behouden, 1 vermindering.
  Ruwe uitkomsten: replay_20260912/implemented_guard_result.json.

De replay blijft een vergelijking tegen de werkelijk opgeslagen oorspronkelijke
SOC en plannen per poll; geen doorgerekende alternatieve fysieke middag. De
uiteindelijke dagelijkse 100%-voltooiing en het praktijkgedrag na installatie
blijven live te observeren. De code garandeert geen energie die fysiek onhaalbaar
is: zo'n tekort blijft een tekort, zonder fictieve voltooiing.

## Onafhankelijke review

Twee risico's vóór afronding gecorrigeerd en gericht getest:
1. Geen NOM-terugval wanneer de continuïteitsfilter alle kandidaten uitsluit.
2. Geen uitsmeren van extra belasting over de volgende klokkwartiergrens.

Geen wijziging in weekend/werkdagprofielen, EV-sturing, marktbeleid, dagdoel,
reservegrens of vaste terugvalbasis. Deze fix is nog niet uitgebracht.
