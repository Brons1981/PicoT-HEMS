# Financiële kwartierbalans en nachtstatus — lokale reparatie

Alex gaf op 27 september 2026 om 20:43 Europe/Amsterdam akkoord op de gerichte
financiële reparatie. Basis: gepubliceerde dev.276,
`3d54d03615b84f1533e6dddba9ece6789eadfafb`; eigen branch
`fix/financial-quarter-night`. Contract: ADR-037.20, als precisering van
ADR-037.18/.19. Status: lokaal geïmplementeerd en geverifieerd; geen commit,
push, versieophoging, publicatie of livewijziging.

## Diagnose en eerste verkeerde grenzen

Alex bevestigt dev.276 live. ZIP `2026-09-27T203018.993`, SHA-256
`4ec7034df989671171ebdadbf60b5fdf0f61ea4dbd4d079fa5cabdecb14d62c1`.
De poll van 20:27:38 lokaal behoudt het bestaande plan, `live_plan_ready`,
`Alleen slim ontladen`, SOC 91%, zonder laadtekort of uitvoeringsblokkade.
De overbrugging tot 28 september 09:15 is voldoende. Dit is opstartbewijs;
de nieuwe markt-/hersteltoelating is hiermee nog niet live beproefd.

Vandaag bevat de financiële huisreeks één gat: 12:47:18,975–12:52:59,821 lokaal.
Afleiding over dat losse gat geeft −45,371122 Wh. Onafhankelijke integratie van
dezelfde bronmetingen over 12:45–13:00 geeft +37,520804 Wh. Alle 82 beschikbare
klokkwartierbalansen zijn geldig. De financiële gatenreparatie gebruikte de
afwijkende deelgrens in plaats van de bestaande volledige kwartierafleiding.
Hierdoor bleven vijf bedragen leeg; netinkoop, export, saldo en slijtage werkten.

Daarnaast verwachtte de financiële nachtfunctie historische `sun.sun`-attributen
`azimuth`, `elevation` en `next_setting`. Home Assistant markeert die als
`_unrecorded_attributes` in zijn Sun-entiteit:
https://github.com/home-assistant/core/blob/dev/homeassistant/components/sun/entity.py
De diagnose bevat voor beide dagen `no_valid_solar_observations`. De actuele
zonsondergangbron werkt wel. Het oorspronkelijke HA-historieantwoord ontbreekt
in de ZIP; de incompatibele bronaanname is wel rechtstreeks in de code bevestigd.
Deze financiële code was ongewijzigd tussen dev.275 en dev.276.

## Wijziging en grenzen

- Financiële gatenafleiding hergebruikt `aligned_measurements`. Elk getroffen,
  gesloten kwartier krijgt eenmaal zijn volledige afgeleide huisenergie. Andere
  kwartieren blijven gelijk. Negatieve kwartieren, ontbrekende fysieke bronnen
  en een nog niet gesloten kwartier blijven onbekend.
- De financiële observer leest nu opgenomen toestandswijzigingen van `sun.sun`
  met een beginanker. `below_horizon` bewijst het nachtvenster binnen de gelezen
  periode. Onbekende, onbeschikbare of ongeldige records onderbreken het bewijs;
  toekomstige records leveren geen beginanker. De lezer bewaart bronidentiteit,
  tijden en methode en begrenst de reeks op 4.096 punten.
- De bestaande worker leest maximaal vandaag/gisteren. Afgeronde historie kan
  uit de cache komen; geen nieuwe worker of extra aanvragen ten opzichte van de
  financiële observer uit dev.274. De attributenlezer voor PV-prognoseleren blijft
  ongewijzigd en is een afzonderlijk aandachtspunt.
- Methode `financial-measurement-inference:v2` bewaart de gebruikte kwartieren
  en nachtstatussen in optionele financiële context. De UI vermeldt afgeleide
  bedragen en volledige kwartierbalansen.

De oorspronkelijke ledger, voorraadkosten, meetarchieven, strikte netlaadterugblik,
MEP, Evaluation, Store en uitvoering zijn ongewijzigd. In `live_runtime.py`
verandert uitsluitend de import en keuze van de financiële historieadapter.
ADR-037.20 legt de vervanging van de oude nachtcriteria expliciet vast; er wordt
geen onbekende productie als gemeten nul gepresenteerd.

## Verse verificatie

- Eerst regressies op dev.276: vijf van zes nieuwe gevallen falen op de bedoelde
  grens (losse gatenbalans, dubbeltelling/kwartierafbakening, brondekking,
  onafgerond kwartier, standaard HA-antwoord zonder attributen). Een reeds
  negatieve volledige balans blijft terecht afgewezen.
- Brede run: `PYTHONPATH=src pytest -q tests/test_v2_*.py
  tests/test_financial_result_ledger.py tests/test_architecture_ownership.py`:
  **832 geslaagd, 1 overgeslagen in 89,71 s**. Dit omvat runtimecompositie,
  plannerintegratie, presentatie en architectuurcontroles.
- Daarna is ontbrekende recordidentiteit expliciet afgevangen en zijn de
  adapter→observer-keten en dag/nachtvensters op 23-/25-uursdagen aangescherpt.
  De verse gerichte financiële/zonhistoriecontrole op de laatste inhoud omvat
  **83 geslaagde tests**. De brede run is niet nogmaals uitgevoerd.
- Ruff over productiecode en alle v2-tests slaagt. Mypy controleert **233**
  productiebronbestanden zonder fout. `git diff --check` slaagt.
- De eerste brede opdracht noemde abusievelijk `tests/test_review_alignment.py`
  en voerde geen tests uit; de juiste v2-bestandsselectie hierboven is uitgevoerd.

## Replay met alleen bewijs uit de ZIP

De passieve observer is op beide oorspronkelijke meetarchieven uitgevoerd met
hun vastgelegde prijzen en fysieke instellingen, in een tijdelijke ledgerkopie.
Geen zonstatussen aangenomen: de ZIP bevat die nieuwe bron nog niet.

| Dag | Resultaat | Beschikbare bedragen | Lokale rekentijd |
| --- | --- | --- | --- |
| 26 september | Gedeeltelijk; nachtbron ontbreekt in archief | 4 van 9 | 1,327 s |
| 27 september tot 20:27:38 | Compleet met herkenbare afleiding | 9 van 9 | 1,128 s |

Voor vandaag wordt alleen het kwartier 12:45–13:00 afgeleid: 37,520804 Wh.
Netinkoop €0,1387, export €0,1631 en netto energieresultaat +€0,0244 blijven
beschikbaar. Afgeleide uitkomsten: totale energiebesparing netto €1,9943,
batterij netto −€0,0666 en extra PicoT-resultaat netto €0,0225.
Dit zijn resultaten tot het genoemde meettijdstip, geen afgesloten dag.
De oorspronkelijke losse ledgerupdate loopt circa 90 seconden verder; haar
bedragen zijn daarom niet één-op-één dezelfde meetperiode.

Oorspronkelijke dagvelden, planningvoorraad en de aangeleverde bestanden blijven
exact gelijk. Opnieuw openen van de tijdelijke opslag levert dezelfde weergave.
De echte JavaScript-renderer verwerkt 32 dagregels en het afgeleide dagresultaat
zonder fout. De volledige HA-historieadapter→observer-keten is daarnaast getest
met het standaard Recorder-antwoordmodel zonder attributen.

## Overdracht

Lokaal gereed voor een afzonderlijke financiële release. Eerst publicatie via
PR/CI na releaseakkoord. Dev.276 blijft nu live en ongewijzigd. Na installatie
controleren of de nieuwe dag/nachtbron daadwerkelijk wordt teruggegeven, of
gisteren opnieuw kan worden berekend en of de financiële bedragen beschikbaar
blijven. Ontbrekende oude HA-historie is met deze ZIP niet te reconstrueren.
De operationele eerste terugvalbasis blijft dev.268.


## Release dev.277 — akkoord 27 september 21:00

Alex heeft na het lokale resultaat akkoord gegeven op de afzonderlijke financiële
release. Dit vervangt de eerdere lokale publicatiestatus. Dev.277 wordt vanaf
main `3d54d03615b84f1533e6dddba9ece6789eadfafb` via PR en de bestaande
GitHub-controles gepubliceerd. Runtimeversie, add-onmanifest, versiecontrole en
changelog worden gezamenlijk bijgewerkt. Installatie en werkelijke beschikbaarheid
van de HA-dag/nachthistorie blijven afzonderlijke livecontroles.

De verse releasecontrole slaagt: 27 versie-, add-onpakket- en
architectuurcontroles, Ruff op productiecode en alle v2-tests, mypy op alle
233 productiebronbestanden en `git diff --check`. CI controleert de definitieve
release-inhoud inclusief de volledige testset opnieuw.
