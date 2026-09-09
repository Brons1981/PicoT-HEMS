# Changelog

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
