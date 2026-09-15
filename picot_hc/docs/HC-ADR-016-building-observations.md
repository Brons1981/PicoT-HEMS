# HC-ADR-016 — Meetbasis woninggedrag

Status: eerste registratiestap geaccepteerd door Alex, 2026-09-15.

## Besluit

De bestaande HC-database bewaart de afkoelperiode vóór het stookseizoen en blijft
ook tijdens verwarming registreren. Per ontvangst worden eigen binnen-/buiten-
temperaturen, vocht, dauwpunt, energie/vermogen en bronstatussen samengehouden.
Voeg het gemeten binnen-buitenverschil (K), achterdeur en per warmtebron de
gerapporteerde modus, activiteit en doeltemperatuur toe, met bronmomenten.
Cv is één bron voor beneden en boven. Modus heat bewijst geen warmtelevering.

Alleen HC-observatie/opslag/presentatie wijzigen. HC-ADR-014/015 blijven gelden.
Geen warmteverliescoëfficiënt, COP, geselecteerde afkoelperiode, voorspelling of
automatische apparaatopdracht in deze stap. Een ontbrekend bronmoment blijft
onbekend. ΔT is een rekenkundig verschil, geen bewijs van actuele of geschikte
leerdata. Latere analyse moet meetleeftijd, gaten, zon, interne warmte, open deur,
verwarming en nawerking daarvan meewegen. Gas omvat ook tapwater.

## Opslag en toegang

Gebruik bestaande snapshots en ingestelde bewaartermijn (standaard 90 dagen),
geen tweede database of verzonnen context bij oude meetpunten. Nieuwe context
heeft versie 1. Herstart behoudt metingen; terugval dev.14 kan de extra velden
negeren. Een download levert de aanwezige meetreeks als gzip-JSONL, in kleine
pagina's gelezen tot een vast eindtijdstip. Geen token, volledige HA-inventaris
of apparaatopdrachten opnemen. Dezelfde Ingress-toegangscontrole blijft gelden.

## Bewijs

Gemeten ΔT inclusief nul/negatief/ontbrekend/verkeerde eenheid, aparte modus en
activiteit, gedeelde cv en onbekende deur; echte HTTP-registratie zonder writes,
SQLite/herstart/oud formaat, begrensd gepagineerde download en browserweergave.
