# Eerste HC/HEMS-uitwisseling: doorlopende energierichtlijn

Lokale vervolgstap op de HC-leermotor. Geen release, commit, push of publicatie
naar Home Assistant uitgevoerd.

## Afbakening

Dit is de eerste richting van de afgesproken uitwisseling: HEMS publiceert
ook zonder verwarmingsvraag zijn verwachting bij de bestaande batterijroute.
HC leest deze en toont de kleinste verwachte batterijmarge tot het einde van
de beschikbare horizon. De verwarming reageert er nog niet op.

De waarde is de verwachte opgeslagen energie boven het technische minimum.
Het is geen toegewezen hoeveelheid energie: komende dagdoelen, herstel,
vermogensgrenzen, marktroutes en alternatieve plannen vereisen een volledige
herbeoordeling zodra HC extra verbruik voorstelt. De velden
`advisory_only=true`, `approval_required=true`, `budgets_additive=false` en
`available_additional_energy_wh=null` leggen dat expliciet vast.

Maximaal vijf HC-kandidaatplannen tegelijk aanbieden, marginale kosten en
haalbaarheid beoordelen, concrete herplanningsvoorwaarden teruggeven en
het gekozen plan reserveren/uitvoeren zijn vervolgstappen. Deze eerste stap
claimt geen planbeoordeling of vrij besteedbaar energiebudget.

## Producent HEMS

- Nieuwe modules `src/picot/v2/energy_outlook.py` en
  `energy_outlook_runtime.py` gebruiken de bestaande read-only projectie
  van de behouden route. Geen kandidaatoptimalisatie of commitmentwrites.
- Kleine aansluiting in `live_runtime.py`: een afzonderlijke achtergrondtaak,
  maximaal één tegelijk, maximaal eenmaal per minuut. Geen HC-vraag nodig.
  Berekenings-/transportfouten blijven geïsoleerd van fysieke uitvoering.
- HA-sensor: `sensor.picot_energy_outlook`, contract `hems-energy-outlook:v1`.
- Maximaal 24 aansluitende tijdgroepen, zonder meetintervallen weg te laten.
  Per groep: verwachte minimum batterij-inhoud, marge boven minimum,
  PV-export, netimport en laagste confidence. De groepsduur hoeft geen uur te zijn.
- Alleen bij één bruikbare actieve route; een ontbrekende of te repareren
  route publiceert een geblokkeerd bericht zonder oude tijdgroepen.
- Snapshot maximaal 120 seconden oud bij berekening én publicatie;
  bericht verloopt 180 seconden na snapshotopname.

MEP heeft geen apparaatnamen, temperaturen, HVAC-logica of nieuwe aanvragen
gekregen. De producent leest bestaande HEMS-planningsgegevens. De originele
werkmap `ev-deadline-advice` bleef ongewijzigd. Alleen `live_runtime.py` werd
als basis gekopieerd naar deze HC-werkmap; lokale hash komt overeen met de
actuele GitHub-versie bij aanvang:
`7cd4623e007ef297ce3b0dcfd7369a2a627e8b64`.

## Consument HC

`picot_hc/energy_outlook.py` valideert versie, tijden met UTC-offset,
geldigheidsduur, aaneengesloten horizon, aantallen, eindige numerieke waarden,
confidence, marges en het niet-toewijzende karakter. Bij verlopen gegevens,
HA-uitval of onvolledige berichten wordt geen oude richtlijn beschikbaar
gehouden. HC blijft zelfstandig zijn bestaande comfortregeling uitvoeren.

De runtime geeft `energy_outlook` door aan het dashboard. Dit werkt ook als
de automatische verwarming uit staat. Er is geen HEMS-signaal aangesloten
op `Heating.plan`, bronkeuze, setpoints of in-/uitschakelen.

## Verificatie en releasegrenzen

Tests gebruiken de echte behouden-routeprojectie en commitmentopslag uit
de bestaande HEMS-testscenario's, plus de echte HC-consument. Ze controleren
dat de route niet verandert, HA de tijdlijn niet inkort, ongeldige/ontbrekende
berichten worden afgewezen, oude snapshots niet worden gepubliceerd en
transportfouten/gelijktijdige aanvragen geen regelkring blokkeren.

De HC-runtimetest controleert zichtbaarheid met HC uit en zonder servicecalls.
De bestaande EV-advies- en worker-tests worden daarnaast opnieuw uitgevoerd.
Voor deze gedeeltelijke checkout worden de bestaande HEMS-bronnen als
importbasis gebruikt en de gewijzigde v2-modules daar in de testomgeving overheen
geladen. De productie-importstructuur verandert daardoor niet.

Echte HA-transport- en browsercontrole en beoordeling tegen de volledige
repository blijven nodig voor release. Het is nog geen live koppeling.

Eindresultaat: 44 tests geslaagd, inclusief bestaande EV-advies/worker- en
beneden-contracttests. Na formattering/importcontrole zijn de 26 direct
betrokken tests opnieuw geslaagd. Ruff voor de nieuwe HEMS-modules en tests,
Python-AST, JavaScript-syntax en git diff --check geslaagd.
