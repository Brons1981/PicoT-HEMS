# Routekeuze — hervatting 21 oktober 2026

## Werkstand

Alex heeft het werk in 'Downloads map lezen' gestopt en hervatting hier bevestigd.
Werkmap: `ev-deadline-advice` in het lokale PicoT-project. Dit is een uitgepakte
werkbron, geen Git-checkout. Bewaar bestaande wijzigingen; niet opnieuw beginnen.
Laatste gedocumenteerde releasebasis is dev.312 / main
`d07abb56e4ae32a63f693483167a2e1a36706e28` (zie `.release312-status.md`).
Geen nieuwe commit, push, release of HA-wijziging uitgevoerd.

Contract: ADR-037.27-assignment-route-choice.md. EUR 0,10 blijft buiten scope.
Financiële score, automatische keuze zonder antwoord en apparaatadapter blijven
ongewijzigd. Eén opdracht, actuele herbeoordeling, keuze bewaren, noodzakelijk
herstel toestaan/met uitleg, expliciet teruggeven via dashboard.

## Aangetroffen en afgemaakt

De oude chat had opslag, kandidaatrestricties, notificatietransport en dashboard
gedeeltelijk geschreven. De runtime-aansluiting ontbrak. Toegevoegd/afgemaakt:

- Callback onder PlanningResetBarrier, duurzame aanvraag en herplanningssignaal.
- HA-helpertransport met dezelfde callback; status en herstelmeldingen publiceren.
- Actuele routecontrole vergelijkt resterende segmenten: vijf seconden normale
  voortgang mag dezelfde route niet onvindbaar maken.
- Afwijzing consumeert de aanvraag één keer, zonder dubbele afrondingsfout.
- Economische herbeoordeling respecteert de keuze; betere geblokkeerde routes
  krijgen een melding. Fysiek herstel blijft toegelaten en verklaard.
- Een eerder veilig herstelde incumbent blijft toegelaten bij latere beoordeling;
  keuze mag geen fallback veroorzaken doordat herstel ander netladen nodig had.
- Dashboard toont tijden/uitleg en gebruikt de bestaande request-ID-helper die
  ook op een gewone HTTP-dashboardverbinding werkt.
- Configuratie heeft één `route_choice_response_entity` in options en schema.

De planbinder blijft de enige acceptatieplek; telefoon/dashboard schakelen geen
batterijmodus. Publicatie van meldingen verandert geen planselectie of voorkeur.

## Verse verificatie

Python uit `%USERPROFILE%/.cache/codex-runtimes/codex-primary-runtime/dependencies/python`.
Testtools uit `night-audit-1021/test-deps`; typecontroletools uit `type-deps`.
TEMP/TMP op de schrijfbare `night-audit-1021` gezet. Geen netwerk nodig voor tests.

- Nieuwe runtime-test reproduceerde eerst de ontbrekende callback (ImportError).
- Gecombineerde route-, dagplan-, herberekening-, daggrens-, belasting-, bridge-
  en marktvergelijkingtests: **101 passed, 9 deselected**, 111,22 seconden.
- Aanvullende volledige route-pipelinefile: **4 passed**, incl. economische
  hercontrole. Acceptatie, onhaalbaar alternatief, opheffen en werkelijk herstel
  lopen door canonieke Candidate/Evaluation/Plan Builder/Plan Store.
- Notificatiefile: **18 passed**, inclusief publicatie/deduplicatie van bevestiging
  en herstel. Deze runs overlappen; samen 103 verschillende geslaagde tests.
- Mypy: **geen fouten in alle 9 gewijzigde bronmodules**.
- Ruff: **alle controles geslaagd** voor betrokken bronmodules en routekeuzetests.
- Node-dashboardrendering geslaagd binnen de gecombineerde run.

De 9 uitgesloten gevallen zijn HTTP-sockettests: 8 nieuwe route-endpointgevallen
en 1 bestaande herberekeningtest. Een eerdere poging gaf Windows-sandbox
WinError 10013 op localhost. Deze zijn NIET als geslaagd beschouwd. Eerst waren
ook standaard Python/TEMP/tijdzonepaden ongeschikt; met de runtime en schrijfbare
TEMP zijn de offline tests daadwerkelijk uitgevoerd.

## Resterende releasegates

Geen live iPhone/HA-bericht, installatie of batterijcommando getest/verstuurd.
HTTP-tests en normale repository-CI moeten vóór release slagen. De brede complete
repositoriesuite is hier niet uitgevoerd. Na installatie is een echte aangeboden
keuze nodig om de telefoon/helper/HEMS-bevestiging te controleren.
Installatiehandleiding: `docs/route-choice-notifications.md` en blueprint
`blueprints/automation/picot_route_choice.yaml`.
