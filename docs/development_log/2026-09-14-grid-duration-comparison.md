# 2026-09-14 — Expliciete netlaadduurvergelijking, auditpunt 8

Alex heeft de open beslissing uit de auditcorrecties expliciet beantwoord:
bij gelijke kosten en haalbaarheid heeft minder netlaadduur de voorkeur in het
kader van zelfverbruik. De verduidelijking betreft uitsluitend **netlaadduur**.
ADR-037.16 legt deze beperkte aanvulling vast.

## Wijzigingscontract

Eerste ontbrekende grens: dagkandidaten bevatten nog geen vers doorgerekende,
expliciete incumbent; Evaluation mist de toegestane gelijkspelregel voor de
netlaadduur. Candidate Generation levert volledige paden, hun geldigheid en duur;
Evaluation vergelijkt die gegevens; Plan Builder en Store verwerken uitsluitend
het gekozen resultaat. Bij behoud blijven oorspronkelijke planidentiteit en
revisie intact. Geen historische kosten als actuele vergelijkingsbasis.

Controlling: ADR-024/026/027/032/033, ADR-037.12/.15 en nieuwe expliciete .16.
Monitor, Opportunity, fysieke uitvoeringsmodus, hardwareconfiguratie en de
klokkwartierproef blijven buiten deze wijziging. Dagdoel, reserve, andere
verplichtingen en bescherming van lopend netladen blijven vereist. De duurregel
is geen vrijgave voor een nieuwe run. Ontbrekende gegevens geven geen voordeel.

Regressies moeten bewijzen: kortere netlaadduur wint bij gelijkwaardigheid;
gelijke duur behoudt incumbent; duurder/ongeldig wint niet op duur; PV/NOM-duur
telt niet mee; de echte dagelijkse route behoudt geldige beperkingen en oorspronkelijke
planidentiteit bij retention. Rollback van dit punt betreft de nieuwe duurregel
plus dagelijkse incumbentconstructie/integratie als één samenhangende wijziging;
de eerder geverifieerde auditcorrecties blijven staan.

Implementatie en verificatieresultaten staan hieronder. Geen commit, release of
livewijziging is met deze opdracht aangevraagd.

## Betekenis van gelijkwaardigheid

De goedkeuring betreft gelijke kosten en haalbaarheid, niet een exact gelijke
extra resterende energievoorraad. De SOC90%-replay om 11:05 laat het verschil zien:
het oude plan houdt 1.760 Wh minimale voorraad, een kortere geldige route 1.660 Wh.
Beide respecteren de vereiste reserve. De lagere strategieprioriteit voor extra
reserve mag de expliciet goedgekeurde netlaadduurvoorkeur niet blokkeren.
Daarom volgt de duurvergelijking direct na een beschikbare financiële gelijkheid,
vóór lagere strategieprioriteiten. Hogere strategieprioriteiten en alle harde
voorwaarden blijven vooraf leidend. De bestaande reductieregressie blijft staan.

## Implementatie

- De outcomeproducer levert resterende netlaadseconden en een verse beoordeling
  van het bestaande plan, inclusief expliciete ongeldigheidsredenen. Ontbrekende
  dekking of noodzakelijke herinterpretatie maakt het oorspronkelijke pad ongeldig.
- Evaluation v3 registreert `grid_charge_duration` en behoudt eerdere
  vergelijkingsstappen. Gelijke duur volgt de overige doelen en commitmentregel.
- De dagelijkse pipeline voert beide soorten kandidaten door dezelfde Evaluation.
  Een winnende incumbent behoudt planidentiteit en revisie; een vervanger volgt
  Plan Builder en Store. Het dashboard benoemt de beslissende netlaadduurregel.
- De marktlaadroute selecteert expliciet een bron met een laadvenster. De nieuwe
  incumbentbron kan zonder zo'n venster bestaan; deze marktportfolio maakt zelf
  geen incumbent aan.

## Verificatie

- Gerichte dagelijkse keten: **87 geslaagd**, met SOC-90%-scenario's om 11:00
  en 11:05, behoud van planidentiteit, ongeldige incumbent, NOM-continuïteit,
  belastingbescherming, andere daghorizon en legacy-evaluatie.
- Evaluation/builder/architectuur: **37 geslaagd**.
- Volledige suite: **1.595 geslaagd, 2 gefaald** in 286,51 seconden. Beide fouten
  waren testopzet: SOC-uitvoeringstests veronderstelden dat het eerste plansegment
  netladen was. De nieuwe selectie begint daar met NOM. De helper selecteert nu
  expliciet het netlaadsegment; beveiligingsasserties blijven gelijk.
- Daarna alle uitvoering-auditregressies plus marktselectie, dagplanner en
  routevrijgave opnieuw: **66 geslaagd** in 90,21 seconden. Dit omvat beide
  eerdere fouten en de aangepaste marktbronselectie. Geen tweede volledige run.
- Ruff: `src/picot` en de vijf betrokken regressiebestanden geslaagd.
  Een bredere verkenning van `src tests` meldde 91 lintproblemen; die scope is
  niet opgeschoond. Geen claim dat alle legacybestanden lintvrij zijn.
- Mypy: **211 bronbestanden geslaagd**. `git diff --check` geslaagd.

Geen commit, push, release of livewijziging uitgevoerd. De eerdere auditreparaties
blijven in dezelfde lokale werkboom aanwezig; dit log sluit het open punt 8.
