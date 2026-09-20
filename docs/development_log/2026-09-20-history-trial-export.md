# 20 september — echte snapshotproef en ontbrekende exportroute

Status: export toegevoegd voor dev.265; publicatie en merge na geslaagde CI
zijn door de gebruiker toegestaan. De drie echte
objecten zijn niet beschikbaar in de huidige uploads en dus nog niet inhoudelijk
geverifieerd of geïndexeerd. Geen nieuwe opname starten om dit te herstellen.

## Vastgesteld uit aangeleverde logs

Dev.264 baseline: 366 cycli disabled, mediane cyclus 8,689 s, RSS mediaan 209,137 MiB.
HA 502 aan het einde herstelt in het vervolglog met 12/12 bronnen en succesvolle
HA-publicatie, zonder sessiewissel. De opnameproef begint om 07:10:37 Nederlandse
tijd op 20 september. 25 actieve en 19 verlopen cycli; 3 accepted, 3 published,
0 rejected/missed/discarded/pending. Laatste opslagmeting 291.610 bytes; maximale
aanbiedduur 0,021399 ms. Cyclusmediaan actief/verlopen 9,996/10,269 s. Dit is een
kleine functionele proef, geen garantie voor langdurige belasting of inhoud.

## Verandercontract

De eerste ontbrekende grens is de diagnose-export: de expliciete allow-list bevat
wel oude diagnosebestanden maar niet de trial-directory. ADR-028, de bevroren
pipeline en de passieve eigenaargrens blijven leidend. Alleen export en runtime-
allow-list worden uitgebreid. Planner, MEP, Plan Store, uitvoering, recorder en
indexworker blijven ongewijzigd. Geen nieuwe timer of automatische verwerking.
Terugval: directory niet aan de diagnose-allow-list toevoegen; bestanden behouden.

## Uitwerking

`diagnostic_zip` behandelt uitsluitend de expliciet aangemelde directory
`picot_history_capture_trial`. Export voert geen mkdir, databasehandeling of
inhoudelijke parsing/decompressie uit. Gepubliceerde `.json.gz`-objecten gaan
bytegelijk en zonder extra compressie in de ZIP, met hun oorspronkelijke digest-
naam en bucketstructuur. Andere bestanden en onafgeronde `.pending-*` blijven uit
het archief. Root, objectdirectory, bucket en objectsymlinks worden geweigerd;
objecten worden met O_NOFOLLOW geopend en op regulier bestand getoetst.

Grenzen: 16 MiB extra gecomprimeerde objectbytes, maximaal 64 geëxporteerde objecten
en 1.024 bekeken bucketentries. Dit begrenst het nieuwe onderdeel, niet de totale
bestaande diagnose-ZIP. Een eigendomsmarker is verplicht; ontbrekende directory
wordt gerapporteerd en nooit aangemaakt. Problemen geven een gedeeltelijke of
onbeschikbare export zonder automatisch gegevens te verwijderen.

`export-manifest.json` vermeldt de meegenomen objecten, lengte en SHA-256 van de
gecomprimeerde bytes, de geclaimde inhoudsdigest, budgetten, fouten en scandekking.
`content_verified=false`: een succesvolle export bewijst geen inhoud of strikte
replay. Dit is geen atomaire snapshot van een directory met een actieve schrijver;
voor deze proef blijft de captureschakelaar uit. De bestaande opname is al verlopen.

## Bewijs

Vóór de wijziging faalt een directe reproductie: de trial-directory levert geen
manifest of objecten in `diagnostic_zip`. Na de wijziging slagen **54 tests in
2,92 s**: nieuwe exportroute, bestaande diagnose-export, capture-/opslagregressies,
architectuur en runtimepackaging. Ruff slaagt; gerichte mypy op drie bronmodules
slaagt. `git diff --check` is schoon.

De nieuwe tests controleren bytebehoud, uitsluitend expliciete export, geen
verwijdering, bestand-/aantalbudget, ontbrekende directory, onveilige links en
synthetische export→digestverificatie→bewijsindex. Die laatste verwerkt drie
proefrecords, koppelt alleen oorspronkelijke beslisinvoer en levert één bruikbare
plankoppeling. Het zijn testgegevens, niet de drie NUC-records.

## Volgende benodigde stap

Dev.265 voegt de export toe om de reeds bewaarde bestanden via de normale
PicoT-diagnoseknop op te halen. Installatie op de NUC gebeurt door de gebruiker.
Na installatie met capture false: één nieuwe diagnose-ZIP. Daarna hier de echte
bytes/digests/JSON en plan-/snapshot-/evaluation-verwijzingen controleren en op een
afzonderlijke lokale index verwerken. Geen volledige replay claimen bij ontbrekende
beslisinvoer van oudere behouden plannen.
