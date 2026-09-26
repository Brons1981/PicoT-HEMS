# Financieel tabblad — aanvullend herstelpunt

Datum: 26 september 2026, na publicatie van dev.271. Alex meldt weer een actief
plan en vraagt het financiële tabblad als afzonderlijk reparatiepunt naast het
onderzoek naar schakelen om 15:25–15:31. Eerst oorzaak en herstelomvang bespreken,
zoals eerder afgesproken. Dit log bevat alleen onderzoek; geen functionele
wijziging, release of wijziging aan Home Assistant.

## Bewijs

De screenshot van circa 21:15 Europe/Amsterdam toont:

- `measurement_coverage_incomplete` bij het financiële resultaat;
- voor 26 september 53 berekende en 32 onbruikbare kwartieren;
- voor 25 september 40 berekende en 56 onbruikbare kwartieren;
- vijf meetreeksen met onderbrekingen bij de lopende dag.

De reeds beschikbare diagnose-ZIP is van circa 16:52, vóór dev.271. Die bewijst
het eerdere probleem, niet de volledige toestand na de update.

In `picot_v2_financial_results.json` zijn 24, 25 en 26 september afgewezen wegens
ontbrekende meetdekking. De PV-reeks heeft op die dagen geen numeriek beginanker
op lokale middernacht. Op 26 september begint de numerieke PV-reeks om
07:34:40,327736 lokale tijd, met 0 W. `FinancialResultLedger._integrate` retourneert
zonder beginanker `None`; `_evaluate` breekt vervolgens de volledige berekening af.
De diagnose onderscheidt dit van een nog niet afgesloten kalenderdag.

De afzonderlijke ruwe meetarchieven bevestigen de kwartierafwijzingen:

| Dag | Berekend | Onbruikbaar | Oorzaak onbruikbare kwartieren |
| --- | ---: | ---: | --- |
| 25 september | 40 | 56 | 54 alleen PV, 1 alleen batterijvermogen, 1 beide |
| 26 september tot circa 16:49 | 36 | 32 | 31 alleen PV, 1 alleen batterijvermogen |

De batterijonderbreking op 26 september is rond 08:48 lokale tijd: circa 0,394 s
voor de vermogensreeksen en 0,404 s voor SOC. De strikte netlaadterugblik heeft
ook een gat in huisverbruiksobservaties van middernacht tot circa 07:35.
Herstel van uitsluitend het PV-beginanker is daarom nog geen bewijs voor een
volledige netlaadterugblik. De oorzaak van de onbeschikbare PV-bron zelf is niet
met deze gegevens vastgesteld; een nachtelijke uitschakeling is geen bewezen
meetwaarde van nul.

## Afzonderlijke weergavefout

`renderFinancialResults` in `src/picot/v2/web_ui.py` keert direct terug zodra
`financial.today.status` niet `available` is. De historische dagtabel en het
cumulatieve overzicht staan na die `return` en verdwijnen daardoor eveneens.
De opslag bevat nog 28 oudere records met status `available`; die zijn niet
gewist. Deze status is hier geen nieuwe inhoudelijke validatie van hun bedragen.

## Voorstel voor de herstelgrens

1. De UI laat eerdere opgeslagen dagresultaten en hun status zien wanneer vandaag
   onvolledig is. De actuele foutmelding benoemt de ontbrekende bron en periode.
2. De financiële meetverwerking onderzoekt afzonderlijk welke bedragen met de
   aanwezige bronnen onderbouwd kunnen worden. Netkosten vereisen andere bronnen
   dan batterijvoordeel of de strikte netlaadterugblik. Wijziging van deze
   beschikbaarheidsregels vraagt een expliciet verandercontract vóór implementatie.
3. Ontbrekende bronmetingen blijven herkenbaar. Geen automatische nulvulling,
   volledig verklaarde dag of besparingsclaim uitsluitend om het scherm te vullen.

Eigenaarschap: financiële nacalculatie/meetverwerking en projectie. ADR-037.13 en
de vastgelegde strikte meetgrenzen blijven leidend; de canonieke pipeline en
ADR-019.5 blijven intact. Planning, Evaluation, Plan Store en aansturing vallen
buiten dit herstelpunt. Terugval betreft uitsluitend de later goedgekeurde
observer-/UI-wijzigingen; bestaande meetarchieven blijven behouden.

Regressiebewijs voor de UI moet een onvolledige huidige dag samen met aanwezige
historie tonen. Voor meetverwerking zijn de nachtelijke PV-onderbreking, het
huisverbruiksgat en de korte batterijonderbreking afzonderlijke gevallen. Een
nieuwe diagnose na dev.271 is nodig voor de gecombineerde livecontrole van het
actieve plan en de actuele financiële brondekking.

Het schakelpunt van 15:25–15:31 blijft het afzonderlijke tweede onderzoek uit
`2026-09-26-bridge-export-intent.md`; er is hier geen schakelbeleid gewijzigd.

## Vervolg met nieuw bewijs en akkoord

De diagnose van 22:09 bevestigt dezelfde financiële blokkade op dev.272:
28 beschikbare oudere dagen en drie onvolledige dagen. De strikte terugblik
heeft nu 57 berekende en 32 onbruikbare tijdvakken voor vandaag. Netmetingen
hebben geen onderbreking; PV mist nog steeds het middernachtanker.
Alex heeft om 22:15 het afzonderlijk beschikbaar maken van netbedragen,
behouden historie en expliciete meetgaten bevestigd. Uitvoering en verificatie:
`2026-09-26-financial-availability.md`; contract: ADR-037.18.
