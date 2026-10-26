# Onopgeloste herplanning en actuele uitvoering scheiden

Status: lokale implementatie op dev.321 (main e2206992c8ef86bce2c26aec31d7972b4d71795f).
Op akkoord van Alex; geen versieophoging, publicatie of liveopdracht.

## Probleem en afbakening

De diagnose 2026-10-26T185439.424 bevat om 14:09:58 Amsterdamtijd een volledige
no-winner-evaluatie. Alle 1022 alternatieven waren ongeldig. Het behouden plan
miste een aanvullend SOC-doel om 14:15 met circa 1,29 Wh, maar sommige alternatieven
hadden daarnaast veel grotere energietekorten tot het volgende laadblok. Dit is
geen grond om alle doelen met een tolerantie geldig te verklaren.

Een mislukte volledige herplanning veroorzaakte ook een uitvoeringsblokkade.
De huidige actie van het opgeslagen plan kan echter afzonderlijk uitvoerbaar zijn.
Dit werk voert dat onderscheid uit voor de aangetroffen no-winner-route en brengt
het bestaande behoud bij toekomstige dagdoelen en handmatige herberekening onder
dezelfde beoordeling. De bestaande strengere volledige-routecontrole van die twee
paden blijft behouden. Andere herstelpaden zijn niet herschreven.

## Verantwoordelijkheden

- Candidate en Evaluation blijven volledige alternatieven beoordelen. Alle afwijzingen
  en het ontbreken van een winnaar blijven in het canonieke evaluatierecord staan.
- `planning_recovery.assess_current_execution` maakt een tijdelijk bewijs voor de
  bestaande actie. De fysieke berekening blijft bij de bestaande reference adapter.
  Alleen bekende energiegerelateerde afwijzingen kunnen de beperkte controle gebruiken.
  Technische en onbekende afwijzingen verlenen geen toestemming.
- De pipeline verbindt deze uitkomsten; ze kiest geen vervangende winnaar en schrijft
  voor tijdelijk behoud geen plan, voltooiing of wijziging van een laadopdracht.
- Execution controleert plan- en segmentidentiteit en geldigheidsduur, naast de
  bestaande actuele SOC-, capability-, BMS-, eigendoms-, EV- en handelscontroles.
- Runtime Monitor ontvangt bij verlopen bewijs een bestaand `replan_required`-signaal.
  De volgende poll moet een verse planninginput vastleggen. Er is geen extra scheduler.
- Health onderscheidt onopgeloste planning van uitvoeringsfouten en NOM-terugval.
  Meldingen bevatten de concrete afwijzingen, leesbare uitleg en de geldigheidsgrens.

Dit volgt het onderscheid uit ADR-037.21. Aanvullende doelen blijven open volgens
ADR-037.10; er wordt geen retirement of voltooiing gefabriceerd (ADR-037.25).
Bestaande Evaluation-selectie en fysieke uitvoeringsguards blijven eigenaar van
hun beslissing. Dit is geen verklaring dat alle ADR 001-037 volledig zijn geaudit.

## Grenzen van het bewijs

Het bewijs geldt tot de eerstvolgende grens van de huidige actie, met een maximum
van 15 minuten. Het verleent geen toestemming voor een volgende actie. Het wordt
niet als nieuw plan opgeslagen en maakt toekomstige tekorten niet geldig. Een
nieuwe canonieke winnaar vervangt het bewijs door de normale plantoestemming.
Verlopen bewijs verhindert verdere opdrachten op basis van dat bewijs; het is
geen zelfstandig batterij-stopcommando. De normale uitvoering en nieuwe planning
blijven verantwoordelijk voor de daaropvolgende aansturing.

Het bewijs is runtime-state. In de latere vervolgstap wacht een nieuwe runtime op
verse plantoestemming; zie `2026-10-26-recovery-consolidation.md`. Er wordt geen
nieuwe persistente herstelmodus toegevoegd. Deze wijziging
belooft niet dat iedere toekomstige onhaalbare laadverplichting hiermee oplosbaar is.

## Verificatie

De nieuwe no-winner-regressie faalde eerst met `fallback_active` en slaagt met
`plan_retained`; de canonieke winnaar blijft leeg en de store blijft bytegelijk.
Negatieve controles omvatten actuele reserve, ontbrekende verbruiksinvoer,
capability, verstreken grens, verkeerd segment en onbekende technische afwijzingen.
Vernieuwing van bewijs laat de opgeslagen opdrachten intact.

Offline replay met de volledige historische planninginput en de store van voor de
handmatige reset reproduceert:

- snapshot `snapshot-f458187efcb99c88`;
- behouden plan `plan-0863d4acecd17e8e`;
- behouden huidige NOM-actie (`balance_bidirectional`);
- bewijs geldig tot 14:15 Amsterdamtijd;
- alle oorspronkelijke kandidaat-afwijzingen en geen canonieke winnaar;
- geen enkele wijziging in de opgeslagen plannen of laadopdrachten.

De replay doet geen Home Assistant-opdrachten. De handmatige reset om 14:11:45
in de oorspronkelijke diagnose blijft een handmatige reset, geen bewezen autonoom
herstel. De eerdere storing om 13:45 heeft onvoldoende volledige invoer om dezelfde
oorzaak zonder voorbehoud toe te schrijven.

Ruff en mypy voor de negen betrokken productiemodules zijn groen. Voor mypy is de
gewone parser gebruikt wegens de lokale native-parser incompatibiliteit.
Gerichte brede regressies: 131 geslaagd (planning, uitvoering, routekeuze, reset,
bridge, kleine voorspelde tekorten, meldingen, livepolls en architectuurgrenzen).
Finale continuiteits-/meldingssuite: 31 geslaagd, inclusief een extra test voor
het aanvragen van verse planning bij bewijsverloop. Legacy-terugvalmeldingen en
health samen: 21 geslaagd. Met overlap verwijderd zijn 140 unieke tests geslaagd.
De volledige repository-/release-CI is niet uitgevoerd; er is geen release gemaakt.

## Resterende vereenvoudiging

De routekeuze is in de lokale vervolgstap naar de onveranderlijke Planning Input
verplaatst; zie `2026-10-26-route-choice-planning-input.md`. De overige afzonderlijke
hersteluitzonderingen zijn hiermee niet allemaal verwijderd. Nieuwe functies blijven
buiten deze wijziging.
