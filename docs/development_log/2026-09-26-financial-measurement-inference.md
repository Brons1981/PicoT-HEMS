# Financiële nacalculatie met begrensde afleiding

Alex heeft op 26 september 2026 om 23:23 Europe/Amsterdam de uitvoering
goedgekeurd. Basis: dev.273, `1feaa9b049222fdf25bb9efdfbb2974c006ad369`.
Branch: `fix/financial-measurement-inference`. Verandercontract: ADR-037.19.
Dit werk is lokaal; geen commit, push, versieaanpassing of livewijziging.
Publicatie volgt pas na afzonderlijk overleg over deze uitkomst.

## Aanleiding en werkelijk bronbewijs

Diagnose `2026-09-26T231613.107` bevestigt dev.273. De laatste opgeslagen
plannerpoll van 23:05:18 heeft een behouden actief plan, `live_plan_ready`,
`Alleen slim ontladen` en geen uitvoeringsblokkade. Dit financiële herstel
verandert dat plan niet.

SHA-256 van de oorspronkelijke ZIP:
`fc3a519e1d6aba886c7aaacb15fe9beb37339839e5a4656b69a3c7768ff76176`.

Op 26 september ontbreken PV en daarvan afhankelijk huisverbruik vanaf
middernacht tot ongeveer 07:34. Daarnaast is er één PV-onderbreking van
70,56 seconden en rond 08:48 een onderbreking van ongeveer 0,394 seconden in
beide batterijrichtingen. Die laatste onderbreking blokkeert zelfs de
dagberekening van slijtage. Netimport en netexport hebben volledige dekking.
Op 25 september zijn er, naast de nacht, zes korte PV-onderbrekingen en twee
onderbrekingen in beide batterijrichtingen. Herhaalde onbeschikbaarmeldingen
binnen één doorlopend gat zijn geen afzonderlijke fysieke uitvallen.

Het archief bevat geen historische `sun.sun`-waarnemingen. Een toekomstige
zonsondergang en nulwaarden aan de rand bewijzen niet het volledige eerdere
nachtvenster. De numerieke PV-reeks op de avond van 26 september bevat wél
echte nulwaarden vanaf 19:59:54; die worden gewoon als metingen behouden.

## Uitvoering

- Ontbrekende nacht-PV krijgt alleen met passend zonhistoriebewijs een afgeleide
  nul. Bestaande positieve metingen blijven staan. Nachtelijke nul is een
  modelaanname, niet een onafhankelijk gemeten waarde.
- Gesloten PV-/batterijgaten van maximaal 120 seconden worden begrensd geschat.
  Per gat maximaal 100 Wh mogelijke bronafwijking, per dag samen maximaal
  500 Wh. Bij overschrijding van het dagbudget worden alle korte aanvullingen
  voor die dag afgewezen. Netmetingen en tarieven worden niet aangevuld.
- PV gebruikt de expliciete financiële bovengrens van 4200 W uit de configuratie;
  batterijgrenzen, conversie en slijtage volgen de vastgelegde daginstellingen.
  Een waargenomen overschrijding van een vermogensgrens blokkeert de korte
  afleiding voor die bron. Lange, open of onbegrensde gaten blijven onbekend.
- Ontbrekend huisverbruik wordt uit de geïntegreerde bronstromen over gelijke
  kwartiergrenzen afgeleid. Negatieve balansen blijven onbekend.
- Bedragen krijgen `estimated`, de UI toont `≈` en de gebruikte perioden.
  Cumulatieve totalen vermelden hoeveel dagen afgeleide bedragen bevatten.
  Ontbrekende zonhistorie krijgt een expliciete uitleg.

De bestaande passieve worker behandelt vandaag en gisteren. Er komt geen nieuwe
thread of extra I/O in de plannerpoll. Zonbewijs wordt begrensd gelezen en voor
twee dagen bewaard; volledige afgeronde zonhistorie wordt hergebruikt.
Een mislukte financiële observer kan de strikte terugblik niet onderbreken.

De oorspronkelijke financiële dagvelden en voorraad blijven intact. Afleiding
staat in optionele velden, buiten de voorraadgetter voor planning. Bij een latere
ruwe update blijft de aanvullende uitkomst behouden. De weergave gebruikt één
gezamenlijke meetperiode en verwerpt een aanvullende berekening die meer dan
15 minuten achterloopt. Herstart herstelt dezelfde weergave.

## Replay op 25 en 26 september

De oorspronkelijke opgeslagen bronreeksen, tarieven en daginstellingen zijn
opnieuw verwerkt in afzonderlijke tijdelijke administraties. De raw-replay van
26 september eindigt om **23:11:07**, eerder dan de losse financiële momentopname
van 23:15. Die bedragen mogen dus niet als dezelfde meetperiode worden vergeleken.

Uitsluitend met bewijs uit de ZIP:

| Uitkomst | 25 september | 26 september tot 23:11 |
| --- | ---: | ---: |
| Netinkoop | €0,0191 | €1,7837 |
| Teruglevering | €3,5511 | €0,2405 |
| Netto energieresultaat | +€3,5321 | −€1,5432 |
| Slijtage, begrensd afgeleid | ≈ €0,1096 | ≈ €0,1296 |
| Aangevulde korte brononderbrekingen | 10 | 3 |
| Maximale bronafwijking door die aanvullingen | 299,310132 Wh | 82,850617 Wh |
| Volledig batterij-/PicoT-voordeel | Nog onbekend | Nog onbekend |

De nachtdelen blijven in deze replay onbekend omdat het bijbehorende zonbewijs
ontbreekt. De Wh-grens geldt voor korte brononderbrekingen; ze is geen foutmarge
op alle dagbedragen of op de nacht-, meet- en overige modelaannames.

Een **afzonderlijk, expliciet conditioneel scenario** levert aangenomen
nachtvensters als testinvoer. Daarin kunnen beide dagen volledig worden berekend,
met alle negen bedragen en status `estimated`. Dit bewijst de technische keten
van nachtafleiding naar financiële weergave, maar bevestigt niet het werkelijke
batterij- of PicoT-voordeel van die dagen. De aangenomen vensters zijn niet als
historische Home Assistant-waarnemingen opgeslagen of gepresenteerd.

Alle oorspronkelijke dagvelden, de planningvoorraad en de ingelezen bestanden
blijven gelijk; herstart levert exact dezelfde weergave. De echte JavaScript-
renderer toont in beide scenario's 31 dagregels. Met alleen archiefbewijs tellen
28 oudere dagen mee; in het conditionele scenario 30, waarvan twee als afgeleid.

## Rekentijd en controle van de isolatie

De eerste volledige nacalculatie kostte ongeveer 20 seconden per dag door
herhaalde integratie van dezelfde meetreeks per tarief. Alleen de nieuwe
weergaveberekening integreert nu één keer op de bestaande tariefgrenzen en geeft
intervalenergie door aan dezelfde formules. Bronreeksen blijven beschikbaar
voor dekking, onafhankelijke netbedragen en herkomst.

Dezelfde replay daalt lokaal naar 1,965 en 1,960 seconden voor de conditioneel
volledige dagen. Alle afgeronde bedragen, dekking, herkomst en foutgrenzen zijn
gelijk aan vóór deze aanpassing. Zonder zonbewijs kost de replay 1,610 en
1,372 seconden. Dit zijn lokale metingen, geen benchmark van de HA-machine.

Acht bestaande voorraad-, integratie- en NOM-methoden zijn via AST met dev.273
vergeleken en volledig gelijk. De oorspronkelijke `_evaluate`-body is voor een
echte `PlanningInputSnapshot` eveneens gelijk. Alleen de afzonderlijke
`FinancialPhysicalContext` gebruikt geen eerdere planningvoorraad. De strikte
terugblik en ruwe archivering blijven identiek, ook bij een observerfout.

## Verificatiestatus

De regressie voor herhaalde meldingen faalde vóór herstel. Gerichte tests dekken
nachtgrenzen, ontbrekend zonbewijs, positieve PV, korte/open/grote gaten,
dagbudget, fysieke grenzen, negatieve energiebalansen, Nederlandse 23-/25-uursdagen,
ontbrekende prijzen/SOC, historische SOC versus actuele HA-leestijden, dubbele
bronrollen, herstart, gelijktijdige publicatie en verouderde uitkomsten.
De vergelijking van dense meetreeksen met integratie per tarief geeft dezelfde
bedragen bij positieve, nul- en negatieve prijzen.

De bestaande canonieke integratietest vergelijkt PlanningInputSnapshot,
CandidateSet, uitkomsten, EvaluationRecord, ExecutionPlanSet, uitvoering,
primitive en vendorresultaat plus Plan Store. Die keten krijgt geen afgeleide
financiële metingen of voorraad.

Afgeronde controles:

- Alle 265 testbestanden, verdeeld over vier afzonderlijke pytestprocessen:
  **1.811 geslaagd, 1 optionele archieftest overgeslagen**. Geen mislukte tests.
- Daarna zijn de onafgeronde nachtrand op maximaal 15 minuten en dubbele
  bronrollen verder begrensd. De volledige betreffende inferentie- en UI-tests
  zijn opnieuw uitgevoerd: **37 geslaagd**, inclusief vijf nieuwe grensgevallen.
- Ruff voor `src/picot`, alle v2-tests en de financiële ledgertests: groen.
- Mypy met de selectie van de Core CI-workflow: **266 bronbestanden zonder fout**,
  opnieuw uitgevoerd na de laatste bronwijziging.
- `git diff --check`: groen. Manifest en runtime blijven dev.273.
- Een extra Ruff-opdracht over het ruimere `src tests` rapporteert 91 bestaande
  meldingen buiten de CI-selectie. Alle 46 betrokken bestanden zijn bytegelijk
  aan dev.273; die staan buiten deze wijziging en zijn niet aangepast.

De UI is met de echte JavaScript-renderer en de beide replayweergaven uitgevoerd.
Er was geen browserbinary voor een nieuwe visuele screenshotcontrole. Er is
geen remote CI-run of nieuwe liveproef uitgevoerd: publicatie is niet aangevraagd.

Laatste verzameling: 1.817 tests, waarvan de genoemde optionele test niet wordt
uitgevoerd. SHA-256 van de elf gewijzigde bron-, test- en configuratiebestanden
(gesorteerd pad, NUL, inhoud, NUL):
`56ab7ffbba9949b9b64d26697914d1856c5ad7fd615957916542af44951de152`.


Releasevoorbereiding: Alex heeft op 27 september 2026 om 00:23
Europe/Amsterdam akkoord gegeven op publicatie als dev.274 via PR en CI.
Dit vervangt de eerdere lokale publicatiestatus; installatie en livecontrole
volgen na geslaagde publicatie afzonderlijk.
