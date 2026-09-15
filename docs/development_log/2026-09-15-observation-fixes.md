# 2026-09-15 — HEMS observatieherstel na dev.260

Alex heeft de drie besproken punten laten repareren. De fixes zijn lokaal geverifieerd.
Alex heeft daarna release dev.261 aangevraagd; publicatie via PR en CI.
Installatie in Home Assistant en livevalidatie volgen na publicatie.

## Probleem en wijzigingsgrenzen

- Schakelhistorie: de klokuitvoering schreef gebeurtenissen duurzaam weg, maar
  ververste de webprojectie niet. De projectie krijgt nu direct de opgeslagen
  lijst, ook zonder Planner Run. `null` confidence blijft onbekend (`—`).
- NOM: Candidate Generation maakte een verwijderd eigen netlaadsegment vrij
  als slim ontladen. De revisiebasis behoudt daar nu NOM. Evaluation beoordeelt
  nog steeds het volledige pad; de bestaande incumbent wordt niet aangepast.
- SOC: de grafiek behield de oude toekomstige planprognose bij planbehoud.
  Een actuele verwachting van exact het geldende plan komt nu uit de bestaande
  simulatie-eigenaar. Historische voorspellingen blijven staan, de nieuwe
  verwachting begint bij de actuele SOC. De grafiek rekent geen energie uit.

De controlling contracts zijn ADR-017/024/027/030/032/033/034/035,
ADR-037.12 en het aanvullende SOC-weergavebesluit. Dit wijzigt geen
planningsvrijgave, economische doelvolgorde, hardwarecommando of meetwaarde.
De bestaande MEP-PV-berekenbasis en omzettingsverliezen blijven gelden.
Dagdoel, reserve, handmatige autoriteit en de dev.254-terugvalafspraak blijven.

De grafiek gebruikt paars voor meetdata en geel voor verwachting; een nieuw
plan krijgt een markering zonder een kunstmatige verbinding naar de oude
voorspelling. Een onbekende nieuwe verwachting wist uitsluitend het toekomstige
displaystuk. Verkeerde planidentiteit en oudere verwachting worden geweigerd.

## Regressiebewijs

De nieuwe schakelhistorie- en JavaScript-tests faalden vooraf respectievelijk
op de ontbrekende publicatiemethode en `null` dat als `0%` werd weergegeven.
Na herstel slagen beide, met behoud van oorspronkelijke run-/planidentiteit.
NOM-regressies bewijzen de kandidaatbasis en het gekozen pad tot de Plan Builder;
SOC-tests bewijzen verse invoer, onveranderde planopslag, behoud van de oude
helling, zichtbare discontinuïteit en het weigeren van een verouderde toekomst.

De volledige testsuite gaf 1604 geslaagde tests en twee verouderde
kleurverwachtingen in de SVG-renderertest. Die verwachtingen zijn bijgewerkt
naar geel, met behoud van de controle op onderbroken lijnen en een aanvullende
controle op de planwisselmarkering. De daaropvolgende gerichte eindcontrole
van grafiek, runtime, schakelhistorie, SOC en NOM slaagt: 92 tests.
Ruff en mypy slagen voor de broncode (mypy: 212 bestanden).
De SOC-producer leverde voor alle 34 passende snapshots van 15 september uit
het aangeleverde archief een verwachting voor het geldende plan. Dit toetst de
projectie en planherkomst; het is geen volledige economische dagreplay.

Liveverificatie moet
na installatie van dev.261 plaatsvinden. Oude ontbrekende
voorspellingen worden niet achteraf verzonnen. Bestaande opgeslagen
schakelmomenten worden bij laden van de webweergave opnieuw uitgelezen.

## Terugval

De schakelhistorie/publicatie en confidence-weergave kunnen zelfstandig terug.
De NOM-wijziging kan bij de kandidaatbasis terug. De SOC-producer,
runtime-aanroep en bijbehorende weergave/cache vormen samen één terugvalgrens;
de ongewijzigde canonieke plannen en ruwe SOC-metingen blijven geldig.
