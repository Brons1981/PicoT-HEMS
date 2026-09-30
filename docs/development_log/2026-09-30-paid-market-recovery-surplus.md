# 30 september — betaald voorraadoverschot bij marktherstel

Alex vraagt uitsluitend reparatie van de herstelvergelijking. De besproken
central-prognoseregel is uitdrukkelijk uitgesteld. Basis: dev.281, 049b138.
Werkbranch: fix/market-recovery-surplus. Geen release of livewijziging.

## Eerste foute grens en contract

Candidate Generation vergelijkt een herstelde handelsvariant tegen een
ongewijzigde referentie die na haar vroegere laadafronding huisverbruik voedt.
Beide paden hebben het dagdoel gehaald; exacte gelijkheid op het latere einde
van de herstellading wijst een betaald overschot af als ontbrekend herstel.

Grondslag: ADR-019.6/.7, ADR-037.21 en de lokale beperkte verduidelijking
ADR-019.8. De referentie en tariefberekening blijven intact. Alleen nieuwe
marktroutes mogen een volledig betaald overschot hebben; tekort en ontbrekend
100%-bewijs blijven verboden. Waardeer het overschot niet. Alle importkosten,
exportopbrengsten en slijtage tot herstel blijven meegenomen. Routeherzieningen
houden exact gelijke voorraad als standaard. Candidate levert; Evaluation
kiest; Builder en Store blijven ongewijzigd. Directe terugval voor deze lokale
patch is dev.281; operationele afgesproken eerste terugval blijft dev.268.

## Implementatie

`common_market_recovery` heeft een expliciete opt-in voor eindvoorraad niet
lager dan de referentie, met behoud van het fysieke volle dagdoel in beide
paden. `market_rule_portfolio` gebruikt deze opt-in bij eerste toelating.
Geen hoofdlaadselectie, forecastmodel, live-uitvoering of tarifering gewijzigd.

## Verse verificatie

- Regressie met echte simulator en huisverbruik: faalt op dev.281 doordat geen
  toegelaten overschotvariant bestaat; slaagt met deze patch.
- Brede markt-/hoofdlaad-/uitvoeringssuite: 263 geslaagd in 278,04 seconden.
- Definitieve toelatings-/hersteltests: 17 geslaagd in 4,55 seconden.
- Ruff op de vier gewijzigde bron-/testbestanden: geslaagd.
- Mypy zonder incrementele cache op beide bronbestanden: geslaagd.
- Tests bewijzen behoud van strikte standaard, geen voorraadtekort, geen
  ontbrekend vol doel en afwijzing van duur/onrendabel extra herstel.

## Echte beslissnapshot van 13:22 Nederlandse tijd

Snapshot `snapshot-35ccb16d1bce2a96`, zonder wijziging van bronbestanden of
apparaatacties. Behoud werkelijk resterend exportbudget: 1633,989 Wh.
Bij expliciete slijtage 0 EUR/kWh (Alex' afgesproken uitgangspunt) blijven acht
varianten over. Canonical Evaluation kiest export 19:27:31–20:15, met herstel
morgen 00:00–02:30. Berekend extra kasresultaat: 0,0130135 EUR, zonder waarde
voor het voorraadoverschot. Minimumvoorraad: 3017,212 Wh; volle voorraad bij
herstel. Dit is prognosebewijs van de historische beslissing, geen werkelijke
opbrengst of plan voor installatie op een later tijdstip.

Volledige CanonicalPipeline-replay kiest `user_market_rule_selected`, bouwt
`plan-d244840fbab9282a`, slaat dezelfde handelsidentiteit en het resterende
budget op, en laadt het plan na herstart correct terug. De bronhash blijft
ongewijzigd. Een afzonderlijke proef met standaard slijtage 0,05 EUR/kWh wijst
handel financieel af; die standaard is geen bewijs van Alex' liveconfiguratie.

Geen versie verhoogd, commit/push/PR gemaakt, gepubliceerd of live aangestuurd.
Publicatie en livecontrole volgen alleen op afzonderlijke opdracht.

## Releaseautorisatie

Alex heeft op 30 september 2026 release dev.282 aangevraagd via PR en CI.
Deze release bevat uitsluitend de herstelfix. De central-regel blijft uitgesteld.
Installatie en livecontrole volgen afzonderlijk.
