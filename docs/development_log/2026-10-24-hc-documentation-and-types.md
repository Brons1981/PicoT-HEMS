# Handleiding en resterende releasecontroles

24 oktober 2026. Vervolg op hc-release-checks. Alleen README en deze overdracht
gewijzigd; geen productiecode, versie, commit, push of live installatie.

## Handleiding

De hoofdtekst van picot_hc/README.md beschrijft nu de lokale ontwikkelwerking:
centrale instellingen beneden, handmatige thermostaat bij uitgeschakeld schema,
handhaven, de rol van boven bij CV-keuze, voorzichtig leren, afbouwen, maximaal
vijf voorstellen, voorwaardelijke reservering en starttoestemming, geschatte
CV-hulpstroom, vertraagde tapwatersignalen en optionele uurverwachting.
Oude installatie- en migratienotities zijn behouden als expliciet historische
bijlage. Er is geen nieuw releasenummer toegekend. Lokale documentlinks bestaan.

## Verse controles

Testhulpmiddelen zijn uitsluitend onder hc-verification-temp/type-tools geplaatst.
De eerste pip-poging mislukte door ontoegankelijke tijdelijke opslag. Met TEMP/TMP
in de werkmap lukte installatie; geen systeeminstallatie of extra appdependency.

- Python-pakketbouw: `python -B -m hatchling build -t wheel -d
  ../hc-verification-temp/package-build` slaagt, exit 0. De HEMS-wheel bevat ook
  reserve_recharge.py en portfolio_recharge.py. Dit is NIET de HC-containerbuild.
- Typecontrole: mypy 2.4.0, vanuit de integratieboom `python -B -m mypy src/picot
  --platform linux --cache-dir ../hc-verification-temp/mypy-linux` levert
  **82 fouten in 13 bestanden, 263 bronbestanden gecontroleerd**, exit 1.
- Dezelfde mypy-versie, instellingen en Linux-doel op de ongewijzigde dev.314-basis:
  **geen fouten in 252 bronbestanden**, exit 0. De nieuwe typefouten horen dus bij
  de integratie en mogen niet als bestaande basisproblemen worden afgedaan.
- Een eerste controle met Windows als doel meldde daarnaast Unix-specifieke API's.
  Die platformmeldingen zijn niet de genoemde 82; de Linux-doelcontrole past bij CI.
- Browserproef opnieuw geprobeerd met tijdelijke opslag in de werkmap, bestaande
  dashboard.cjs, lokale fake HA, aanwezige Edge en echte lokale Python. Edge sluit
  bij starten met Windows-toegangsfouten, voor dashboardasserties. Nog geen
  geslaagde browserproef; geen productfout uit deze startfout afleiden.
- Docker ontbreekt. Geen containerbouw, Supervisor-proef of live woningproef.

## Open typewerk, geen vrijgave

De meldingen bestaan uit ontbrekende annotaties, ongetypeerde verzamelingen en
mogelijk ontbrekende context/resultaten. Verdeling:

| Bestand | Meldingen |
|---|---:|
| modeled_load_history.py | 7 |
| planning_input.py | 3 |
| household_load_history.py | 4 |
| energy_outlook.py | 2 |
| mep_candidate_outcomes.py | 1 |
| reserve_recharge.py | 16 |
| portfolio_recharge.py | 4 |
| mep_canonical_pipeline.py | 1 |
| energy_portfolio.py | 5 |
| energy_selection.py | 3 |
| accepted_loads.py | 23 |
| energy_portfolio_runtime.py | 10 |
| live_runtime.py | 3 |

Vervolg: de bestaande contracten expliciet typeren, vervolgens de ontbrekende
waarden bij hun producer/consumer-grens beoordelen. Geen globale uitschakeling
van strict checks en geen willekeurige type-ignore-regels om de controle groen
te maken. Daarna typecontrole en betrokken regressies opnieuw uitvoeren, gevolgd
door de echte CI/container/browsercontroles. Deze stap is geen releasegoedkeuring.

De 428 HC-tests en 30 subtests uit de vorige stap zijn niet opnieuw gedraaid:
deze beurt wijzigt uitsluitend documentatie. Dat eerdere bewijs blijft apart
van de nu mislukte typecontrole staan.

Vervolg na opdracht tot herstel: zie 2026-10-24-hc-type-repair.md. De 82
typefouten en de bronlintmeldingen zijn opgelost; de lokale browserproef slaagt.
