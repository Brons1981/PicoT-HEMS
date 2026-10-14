# 2026-10-14 — rustig financieel weekoverzicht (lokaal, geen release)

## Wijzigingscontract

Op verzoek van Alex: het goedgekeurde weekoverzicht implementeren, een grafiek
voor de herkomst van huisverbruik toevoegen en de Zendure-terugverdienvoortgang
met een afzonderlijke tijdschatting tonen. De eerste presentatiegrens was een
lange dagentabel met een gezamenlijke status, naast veel permanent zichtbare
uitleg. Eigenaar is uitsluitend `web_ui.py`.

ADR-037.18/.19/.20 blijven leidend: kwaliteit per bedrag, onbekend is geen nul,
afleiding is herkenbaar, oude bedragen worden niet opnieuw beoordeeld.
Backendformules, meetverwerking, opgeslagen bedragen, voorraad, planning,
apparaatregeling, tarieven, zonnebonus en releasebestanden blijven ongewijzigd.

## Presentatie

- Huidige Amsterdamse maandag-zondagweek; eerdere weken via selectie en knoppen.
- Drie weekkaarten en dagbedragen. Afleiding/ontbrekend bewijs krijgt een !;
  historische bedragen zonder afzonderlijke meetcontrole krijgen een klokicoon.
- Weekbedragen sommeren uitsluitend bestaande beschikbare waarden per bedrag.
  Ontbrekende dagen worden meegeteld in de dekking, toekomstige dagen niet.
  Deeltotalen benoemen hun dekking; huidige meetperiode wordt vermeld.
- Onderbouwing standaard dicht. Bedragicoon opent de dag met toetsenbordfocus.
  Bestaande brononderbrekingen, afleidingen, onzekerheid en bedragen blijven daar.
- Dagbalken in kWh: PV geel, net rood, batterij groen. Alle balken dezelfde schaal.
  Alleen de bestaande volledige, aansluitende bronverdeling wordt getoond;
  geen nieuwe toerekening of reconstructie. Batterij is de directe leveringsbron,
  geen claim over de eerdere laadbron.
- Zendure toont bestaande cumulatieve terugverdienvoortgang. Alex heeft ook een
  tijdschatting bevestigd: resterende aankoopwaarde / gemiddeld netto
  batterijvoordeel van de laatste 28 afgesloten kalenderdagen. Geen schatting
  bij ontbrekende dagbedragen of een niet-positief gemiddelde. Afgeleide en
  historische invoer worden in de toelichting genoemd. Geen seizoensprognose,
  garantie of zonnebonus. Dit verandert geen dagbedrag of cumulatieve waarde.

## Verificatie en grenzen

- Gerichte financiële/UI-suite: 130 tests geslaagd; omvat bestaande ledger,
  afleiding, nacht-/kwartierbewijs en HTTP/UI-regressies.
- Nieuwe uitvoerbare JavaScript-tests: afzonderlijke kwaliteit, nul/negatief,
  ontbrekende kalenderdagen, historische labels, geen mutatie, Amsterdam/DST/
  jaarovergang, bronverdeling en ontbrekend bewijs, 28-daagse schatting,
  weekkeuze en openen van onderbouwing.
- Ruff geslaagd op gewijzigde Pythonbestanden; Mypy geslaagd voor web_ui met
  Linux-doelplatform (productie). Windows-default Mypy meldt bestaande
  O_NOFOLLOW/O_NONBLOCK-platformdefinities in passive_history/export.py.
- Lokale Edge-browser: 49 dagrecords uit diagnose 14 oktober 19:47 via bestaande
  ledgerprojectie. Geen JavaScriptfouten; weekkeuze, icoonbediening en mobiel
  390px gecontroleerd. Bronbestand alleen gelezen; preview buiten repository.
- De diagnose mist batterijbedragen binnen het 28-daagse venster: daarom wel
  voortgang, maar geen numerieke terugverdientijd. Geen live/installatiebewijs.

Rollback: uitsluitend deze presentatiewijziging terugdraaien; geen migratie of
historische reparatie nodig. Geen commit, push, PR, versieophoging of release.

## Vervolg — herstel na tweede controle (14 oktober)

Alex heeft herstel en regressietests voor twee bevindingen goedgekeurd, zonder
release en met behoud van alle bestaande bedragen en rekenmodules.

- De afzonderlijke tijdschatting vereist nu voor elk van de 28 dagen een
  vastgelegde periode van lokale middernacht tot de volgende lokale middernacht
  in Europe/Amsterdam. Een geselecteerde financial_metrics-periode wordt nooit
  aangevuld met de periode van een ander/raw resultaat. Ontbrekende, ongeldige
  of kortere perioden blokkeren alleen de schatting; historische bedragen en
  kwaliteitslabels blijven behouden. Ook 23- en 25-uursdagen zijn geldig.
- Alle financiële uitklapvelden hebben stabiele sleutels. Hun actuele open/dicht-
  toestand wordt synchroon vastgelegd voordat het overzicht opnieuw wordt
  opgebouwd, ook wanneer een browser-toggle-event nog niet verwerkt is.
  Dit omvat meetgaten, afleidingen en de onderbouwing van de tijdschatting.
- De regressies voor halve dagen en verloren uitklapstanden faalden vóór de fix;
  de extra kalendergrenzentest faalde omdat die controle nog niet bestond.
  Na herstel: 133 gerichte tests geslaagd, Ruff en Mypy (Linux-doel) geslaagd.
- Verse Edge-controle: open en gesloten uitleg blijft behouden na verversen;
  28 volledige dagen van EUR 2 bij EUR 200 resterend geven 100 dagen, één halve
  dag blokkeert de schatting. Geen JavaScriptfouten of mutatie van invoergegevens.
- Opnieuw 441 bedragen (49 dagrecords x 9 velden) vergeleken met oorspronkelijke
  presentatie: identiek. Python buiten DASHBOARD_HTML en financiële rekenmodules
  ongewijzigd; diagnose-ZIP en ingelezen dagrecords blijven ongewijzigd.

Geen commit, push, PR, installatie, versieophoging of release uitgevoerd.

## PR-voorbereiding — lichte weergave

Alex heeft een PR en automatische controles aangevraagd; nog geen release.
Het financiële overzicht gebruikt nu een licht vlak met witte kaarten,
donkere tekst en rustige randen. De wijziging is beperkt tot het financiële
paneel. PV blijft geel, net rood en batterij groen; de legendatekst is donker
voor leesbaarheid. Berekeningen en opgeslagen bedragen zijn niet gewijzigd.

Verse lokale verificatie: 133 tests, Ruff, Mypy (Linux-doel), Edge op desktop
plus mobiel, bronkleuren en uitklapbediening geslaagd. De PR bevat ook de twee
gecontroleerde reparaties en hun regressietests. Automatische GitHub-controles
volgen op de PR; geen merge, installatie of release is aangevraagd.
