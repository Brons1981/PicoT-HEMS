# 21 september — bronbewijs bij afgewezen huisverbruik

Status: geïmplementeerd vanaf dev.267 / 853da6d. Alex heeft publicatie bevestigd;
dev.268 gaat via PR en wordt na geslaagde CI samengevoegd.

## Verandercontract

Eerste ontbrekende grens: Planning Input wijst ongeldige huisverbruiksbalansen af
als None, zonder een reden mee te leveren. De runtime bewaart alleen geldige
observaties. Daardoor is later niet zichtbaar of een ontbrekend meetmoment door
bronuitval, inconsistent batterijvermogen of een negatieve balans ontstond.

Canonical Pipeline Contract, ADR-017/030 (feiten en herkomst), ADR-028
(resourcebegrenzing) en ADR-035 (HA-bronbewijs) blijven leidend. Eigenaren zijn
invoerbeoordeling en de passieve diagnostische registratie. MEP, selectie,
commitment, uitvoering, sensoren en bestaande kwartierberekening blijven buiten
scope. Geen nulvulling, tijdverschuiving of nieuwe geldigheidsgrens.

Invariant: dezelfde bronwaarden leveren exact dezelfde HouseholdLoadObservation
of None op. De extra reden staat op de bundle, buiten PlanningInputSnapshot.
Terugval: registratiecallback en diagnosepad verwijderen; oude bestanden behouden.

## Bewijs uit diagnose 21 september 20:04

Gaten 14:09:27–14:14:49 en 14:32:16–14:37:40 Nederlandse tijd. Bronreeksintegratie
over deze perioden geeft respectievelijk circa -37,63 en -56,52 Wh huisverbruik.
Onafhankelijke integratie bevestigt de negatieve klokkwartieren 11:15–11:30
(-5,11 Wh) en 14:30–14:45 (-3,88 Wh). GoodWe heeft 8/9 archiefpunten per betrokken
kwartier, Shelly 897 en batterij-laden 573/561. Puntenaantallen zijn geen bewijs
van fysieke samplefrequentie: Recorder bewaart ook state-holdgrenzen.

Dit wijst op onderlinge bron-/tijdinconsistentie, maar bewijst geen exacte
sensorvertraging of afwijsreden voor elke historische poll. Het bijbehorende
runtime-log ontbreekt; een extra runtimeonderbreking kan niet worden uitgesloten.

## Implementatie

De bestaande invoerbeoordeling retourneert nu naast de observatie een reden:
ontbrekende/dubbele bronrol, onbeschikbare of ongeldige bronmetadata, niet-numerieke
of niet-eindige waarde, inconsistent batterijvermogen of negatieve huisbalans.
De oude helper blijft dezelfde observatie/None teruggeven.

Alleen afgewezen metingen worden via een aparte runtimecallback vastgelegd in
`/data/picot_v2_household_load_rejections.jsonl`. Elke regel bevat run/snapshot-ID,
versie, poll- en assemblagetijden en de vijf betrokken bronrollen. Per bron blijven
entity-ID, ruwe waarde/eenheid, availability/error, evidence/mapping-ID, observed_at,
state_read_at, last_updated_at en last_changed_at behouden. Ontbrekende tijden
blijven null; de oorspronkelijke offset blijft behouden. Geen afgeleide geldige
huisverbruikswaarde in dit bestand, geen invoer voor prognose of planner.

Het bestand is expliciet toegevoegd aan de bestaande diagnose-export. Maximaal
64 KiB per regel en 16 MiB totaal. Bij volle opslag stopt nieuwe registratie met
een expliciete runtimefoutmelding; niets wordt verwijderd of geroteerd. Dit is
begrensde onderzoeksregistratie, niet het nog openstaande permanente bewaarbeleid.
Schrijf-/serialisatiefouten laten de bestaande runtimecyclus doorgaan.

## Verificatie

76 gerichte tests slagen: bronredenen, bronbewijs, export, uitsluiting uit geldige
historie, opslaglimiet zonder verlies van bestaand bewijs, doorgaan bij schrijffout,
bestaande huisverbruiksberekening/-historie, runtime/herplanning, fallback,
webserver-diagnosepaden en architectuur. Ruff slaagt. Mypy slaagt op 224 bronbestanden.
Een onafhankelijke vergelijking van 240 invoercombinaties met de functie uit
dev.267 geeft exact dezelfde observatie/None-uitkomsten. git diff --check schoon.

Geen nieuwe NUC-metingen beschikbaar; dit verklaart toekomstige afwijzingen en
repareert nog niet de bronafstemming of historische gaten. Releaseversie voorbereid als dev.268; installatie en livecontrole volgen apart.
