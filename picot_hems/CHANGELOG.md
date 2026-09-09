# Changelog

## 2.0.0-dev.245

- Het behouden laadplan blijft zichtbaar, inclusief het oorspronkelijke NOM-venster en de planidentiteit.
- Bij hetzelfde behouden plan blijft de oorspronkelijke SOC-prognose zichtbaar met het berekenmoment. Na een herstart zonder eerdere prognose blijven de laadvensters zichtbaar; er wordt geen SOC-lijn verzonnen.
- De marktroute kan alle gepubliceerde dagprijzen gebruiken voor haar fictieve laadreferentie, inclusief verstreken kwartieren. Uitvoerbare acties blijven in het resterende tijdvenster.
- Echte gaten in de prijspublicatie blijven de marktvergelijking blokkeren.

De afspraken voor dagelijks laden, optimalisatie en optionele herstelbaarheid blijven ongewijzigd. Na installatie: controleer dev.245, het behouden NOM-venster en de marktroute. Werking in Home Assistant moet live worden bevestigd.

## 2.0.0-dev.244

Ontwikkelrelease voor de gezamenlijke liveproef van de dagelijkse laadcyclus en de user-rule-marktroute.

- Dagelijkse laadopdracht met eigen identiteit en 100%-doel; PV-, hybride en netlaadsegmenten blijven bij dezelfde opdracht horen.
- Aanvullende laadopdrachten behouden hun eigen doel en voltooiing.
- Marktvolume en minimumspread instelbaar in de strategiepagina; maximaal één handelsopdracht per regel per leveringsdag.
- Optionele herstel-/nettowinsttoets, standaard uit. Een lege minimumspread schakelt nieuwe handel uit.
- Bestaande laad- en handelsvensters blijven behouden tijdens optimalisatie en herstart.
- Stopbewaking gebruikt actuele SOC, het handelsvenster, gemeten export en werkelijke modusterugmelding. Meetgaten leveren geen verzonnen volume op.
- Minder herhaalde laadberekeningen. Tijdens marktberekeningen komt de bestaande uitvoeringsbewaking tussentijds aan bod; vóór uitvoering wordt nieuwe input ingelezen.

Na installeren: controleer dev.244 in PicoT en vul de gewenste handelsfractie en minimumspread in. Herstel kan voor de eerste proef uit blijven. Bestaande instellingen en historische diagnostiek blijven bewaard.

Dit is een ontwikkelrelease: lokale controles zijn uitgevoerd; werking met de echte HA-meethistorie en modusfeedback wordt in de gezamenlijke liveproef beoordeeld.
