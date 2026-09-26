# Fix 3 — financiële bedragen onafhankelijk beschikbaar

Alex heeft op 26 september 2026 om 22:15 Europe/Amsterdam de afbakening bevestigd.
Basis: dev.272, `565150bdfe8caa0d9ebde512fcaad518d2843e64`. Branch:
`fix/financial-result-availability`. Verandercontract: ADR-037.18.
Alex heeft om 22:39 Europe/Amsterdam afzonderlijke publicatie als dev.273 via
PR en automatische controles goedgekeurd. Installatie en livecontrole volgen daarna.

## Bewezen fout

De nieuwe diagnose `2026-09-26T220916.462` bevestigt dev.272 om 22:07:51 lokaal,
met een behouden actief plan en zonder uitvoeringsblokkade in die ronde.
De financiële dagberekening wordt afgewezen omdat de eerste numerieke PV-waarde
pas om 07:34:40 binnenkomt. Netimport en netexport hebben wel volledige dekking.
De echte JavaScript-renderer produceert met de opgeslagen administratie alleen
de foutmelding, nul tabellen en nul dagregels, terwijl 28 oudere dagresultaten
met status `available` bewaard zijn. Dit is geen nieuwe validatie van die bedragen.

## Uitvoering en grens

`financial_result_metrics` bepaalt afzonderlijk welke getoonde bedragen hun eigen
meet- en prijsdekking hebben. Netinkoop, teruglevering en het gezamenlijke
energieresultaat hoeven niet op PV te wachten. Slijtage volgt de bestaande formule
met batterijontlading. De bestaande voordeelberekeningen worden alleen getoond
bij voldoende dekking; geen onbekende bedragen als nul in kaarten of totalen.

De bestaande voorraadkosten die planning kan lezen blijven behouden: de oude
afrekening en voorraadfuncties zijn ongewijzigd. Nieuwe status, bronafhankelijkheden
en gaten staan in een optioneel veld `financial_metrics`. Alleen presentatie en
cumulatieve weergave gebruiken dat veld. Oudere dagrecords blijven leesbaar.
Een fout in de aanvullende meetbeoordeling krijgt expliciet foutbewijs en kan
de bestaande voorraadupdate niet verhinderen.

Dezelfde historiecache bewaart onbeschikbaarheidsmarkeringen. Bestaande grafieken
en voorraadberekening krijgen vóór de middernachtselectie dezelfde numerieke
reeks als voorheen. De financiële meetbeoordeling krijgt ook de markeringen;
geen extra HA-aanvragen, cache of worker. De cachevergelijking test beide routes
op dezelfde Recorder-antwoorden, meerdere tijdvakken en een onbeschikbaar beginanker.

De UI houdt historie, gedeeltelijke dagen en bestaande totalen zichtbaar.
Kaarten tonen bedragen of een streep met reden. Bron en onderbrekingsperiode
zijn uitklapbaar; de tabel bevat een statuskolom en kan horizontaal scrollen.
De dekking van het cumulatieve bedrag is expliciet. Geen extra lokale berekening
van energiekosten of voordeel in JavaScript.

## Originele diagnose opnieuw verwerkt

De originele laatste PlanningInputSnapshot, volledige bronprijzen en de gemeten
reeksen zijn gebruikt in twee tijdelijke administraties. De dev.272-afrekening
en de gewijzigde versie ontvangen dezelfde numerieke reeks; alleen de nieuwe
weergavebeoordeling krijgt daarnaast de onbeschikbaarheidsmarkeringen.
Instellingen uit de diagnose: slijtage €0,02/kWh en beide conversiefactoren
0,9110433579. Er zijn geen opgeslagen bronbestanden veranderd.

Tot 26 september 22:07:51 lokaal:

| Bedrag | Uitkomst |
| --- | ---: |
| Netinkoop | €1,7825 kosten |
| Teruglevering | €0,2380 opbrengst |
| Netto energieresultaat | −€1,5445 |
| Batterij- en PicoT-voordeel | Onbekend wegens meetonderbrekingen |

Alle 31 dagrecords blijven bestaan, waaronder 28 oudere beschikbare resultaten.
De bestaande afrekening, voorraad, snapshot en oudere dagen zijn gelijk aan de
baseline; herstart herstelt exact dezelfde nieuwe weergave. De replay kostte
lokaal 0,127 s voor de baseline en 0,365 s met beschikbaarheidsbeoordeling.
Dit is één lokale meting, geen prestatiegarantie voor de NUC.

## Verificatie

De twee eerste regressies faalden vóór herstel: geen onafhankelijk netresultaat
bij ontbrekende PV en de verdwenen historische tabel. Gerichte controles
dekken bronuitval, huisverbruiksgaten, ontbrekende prijzen/netrichting, echte
nulbedragen, negatieve prijzen, prijs-/vermogensgrenzen, herstart en foutisolatie.
De runtimeketentest gebruikt één exact snapshot en dezelfde opgeslagen plannen:
alle canonieke records en de Plan Store blijven gelijk met/zonder weergavebewijs.
De eerste testopzet maakte twee snapshots met verschillende meetlooptijdmetadata;
dit is gecorrigeerd naar één gedeelde invoer, zonder productieaanpassing.

Een visuele browserproef kon niet starten omdat de lokale Playwright-installatie
geen Chromium-binary bevat. De echte JavaScript-renderer wordt wel uitgevoerd
met een DOM-harnas, inclusief de oorspronkelijke diagnose. Geen browserinstallatie
of wijziging aan de gebruikersomgeving gedaan. Integrale controles volgen hieronder.

### Afgeronde lokale controles

- De actuele renderer op het opnieuw berekende diagnosebestand: **31 dagregels**,
  28 oudere beschikbare resultaten, één gedeeltelijke huidige dag en twee oudere
  onvolledige dagen. De drie gemeten netbedragen en de cumulatieve dekking zijn
  zichtbaar; geen `NaN`, ongefundeerde nulbedragen of ruwe foutcode als uitleg.
- 42 gerichte financiële, UI-, historiecache- en runtimeketentests geslaagd.
  De afzonderlijke architectuur-/uitvoeringsselectie van 70 tests was eveneens groen.
- Alle **264 testbestanden** over vier geïsoleerde processen uitgevoerd:
  435 + 484 + 476 + 385 geslaagd, één fout en één optionele skip. De fout was
  uitsluitend een bestaande testdubbel die de nieuwe optionele aanroepparameter
  `financial_measurement_history` niet accepteerde. De test accepteert die nu
  expliciet en controleert gelijke meetperioden. Het volledige betrokken bestand
  daarna opnieuw uitgevoerd: **13 geslaagd**, inclusief de eerder falende test.
  Einddekking: **1781 unieke tests geslaagd, 1 optioneel overgeslagen**. Er is
  sinds de volledige run alleen deze testkoppeling aangepast, geen productiecode.
- De skip vereist de aparte diagnosefixture van 19 september via
  `PICOT_TEST_DIAGNOSTIC`; de echte financiële replay van 26 september is uitgevoerd.
- Ruff op alle broncode, alle v2-tests en de financiële tests: schoon, ook na
  de testkoppelingcorrectie. `git diff --check`: schoon.
- Volledige Mypy CI-selectie: **264 bron-/testbestanden zonder fouten**, met een
  afzonderlijke cache. Geen dependency- of configuratiewijziging.
- De oude afrekening, voorraadopbouw/-uitlezing, NOM-nacalculatie, tariefsegmenten
  en integratie zijn structureel identiek aan dev.272. De runtimeketentest
  vergelijkt dezelfde planninginvoer, kandidaten, uitkomsten, evaluatie, plannen,
  uitvoeringsrecords en bewaarde Plan Store.

SHA-256 van alle finale Python-bron- en testbestanden vóór de verhoging naar
dev.273, gesorteerd pad, nulbyte, inhoud, nulbyte:
`695be8e16da78a5144af9c5e9a2256762524e83943da40265b2aab2ff9af466c`.

De aanvullende releasecontrole na verhoging naar dev.273 is geslaagd:
11 versietests, Ruff op de aangepaste Python-versiebestanden en `git diff --check`.

Acceptatie: het goedgekeurde financiële herstel is lokaal gereed en geverifieerd.
Release dev.273 is voorbereid; publicatie volgt via PR met geslaagde automatische
controles. De bestaande oorspronkelijke diagnosebestanden zijn ongewijzigd.
Livecontrole van het financiële tabblad volgt na installatie van de goedgekeurde
release.
