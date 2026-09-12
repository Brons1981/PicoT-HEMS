# 2026-09-12 — Begrensde proef vaste klokkwartieren

Alex accepteert vaste historische klokkwartieren met evenredige gedeeltelijke
kwartieren. Bewezen aanleiding: bij dezelfde historie veranderde de verwachte
huisvraag voor 00:35–16:30 van 5192,205 naar 5253,323 Wh door alleen verschuiving
van rekentijd 00:31:01 naar 00:33:24. De exacte doelcontrole leidde tot revisie
bij 15 Wh tekort; netlaadvolume bleef gelijk, alleen NOM werd langer.

Pre-stable: dev.254, commit 21314d87be70442d9643d75ee74e7beb3be97e89.
Stopregel en observatiecriteria: ADR-037.14. Geen release of livevalidatie gedaan.
Dashboarduitleg van Solcast-updates en laadbronnen blijft een apart open punt.

Implementatie: alleen historische tijdvakken en methodeversie aangepast.
Gerichte regressiegevallen toetsen wisselende historische vraag, polltijd,
kwartiergrenzen, aaneensluitende intervallen en gedeeltelijke horizon.

## Verificatie

Remote main gecontroleerd: dezelfde dev.254-commit als lokale basis.
Reproductie met identieke diagnosehistorie en drie oorspronkelijke polltijden:
na wijziging steeds 5207,924785 Wh voor dezelfde periode (voorheen tot 61 Wh verschil).
Rechtstreeks uitgevoerde assertions: vijf gedeeltelijke kwartiergevallen, exacte
horizondekking, aaneensluiting, energiebehoud en onvoldoende historie geslaagd.
`git diff --check` geslaagd. Pytest niet beschikbaar in beide Python-runtimes;
tijdelijke installatiepoging kon geen pakket ophalen. De toegevoegde pytest-tests
en bestaande integratietests moeten daarom nog in CI draaien voor een release.
