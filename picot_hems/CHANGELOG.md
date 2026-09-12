# Changelog

## 2.0.0-dev.255

- Gebruikt vaste klokkwartieren voor historische huisvraag, zodat alleen een verschoven polltijd de toekomstige verbruiksverwachting niet verandert.
- Rekent gedeeltelijke begin- en eindkwartieren evenredig mee. Dagdoel, reserve, prijsselectie en actuele invoer blijven van kracht.
- Begrensde observatieproef: dev.254 blijft de vaste pre-stable terugvalbasis. Bij slechter gedrag direct terug; maximaal één kleine optimalisatie als het gedrag niet slechter is. Daarna bij onvoldoende resultaat terug en opnieuw ontwerpen.

## 2.0.0-dev.254

- Toont de geplande SOC als doorgetrokken lijn met behoud van de moduskleuren.
- Geeft de werkelijke SOC een vaste paarse kleur, inclusief legenda. Ontbrekende metingen blijven zichtbaar als onderbreking.
- Alleen weergave gewijzigd; SOC-gegevens, planning en aansturing blijven ongewijzigd.

Na installatie: controleer dev.254 en de SOC-lijnen in de prijsgrafiek.

## 2.0.0-dev.253

- Neemt de oorspronkelijke marktroute mee in de ongearceerde planreferentie. De eerste handel geldt niet meer ten onrechte als een latere optimalisatie.
- Herstelt de oorspronkelijke handelssegmenten via hun bewaarde bronverwijzingen, ook na planrevisies en herstart. Latere laadwijzigingen worden niet in de oorspronkelijke referentie overgenomen.
- Alleen latere afwijkingen van het volledige oorspronkelijke plan krijgen arcering. MEP en aansturing blijven ongewijzigd.

Na installatie: controleer dev.253 en of oorspronkelijke handel ongearceerd is.

## 2.0.0-dev.252

- Corrigeert arcering: alleen afwijkende delen ten opzichte van het eerste vastgelegde dagplan worden gearceerd. Ongewijzigde delen blijven zonder arcering, ook bij een nieuwe planrevisie.
- Herstelt de oorspronkelijke referentie uit de bestaande planhistorie na herstart. Ontbrekende referentie wordt expliciet gemeld.
- Toont het kostenverschil bij minder netladen boven de terugbliktabel onder Financieel, met datum en status of de reden waarom nog geen bedrag beschikbaar is.
- MEP, financiële rekenregels en aansturing blijven ongewijzigd.

Na installatie: controleer dev.252, de arcering bij aangepaste plandelen en Financieel > Terugblik netladen.

## 2.0.0-dev.251

- Voegt een passieve dagelijkse terugblik op netladen toe: modelmatig vermijdbare kWh, kostenverschil en afwijking van de vastgelegde PV-verwachting. De berekening behoudt batterij-export, het hoofdlaaddoel en de eindvoorraad; onvolledige meetdagen tellen niet mee in de trend.
- Toont de werkelijke SOC als groene traplijn naast de gestreepte oorspronkelijke prognose in de prijsgrafiek. Ontbrekende metingen blijven zichtbaar als onderbreking.
- Arceert de prijsbalken precies binnen gekozen NOM-, netlaad- en handelssegmenten, inclusief gedeeltelijke kwartieren.
- Bewaart de terugblik over herstarts en voegt de gegevens toe aan de diagnose-download. MEP, evaluatie en aansturing blijven ongewijzigd.

Na installatie: controleer dev.251, de twee SOC-lijnen en arcering. Onder Financieel verschijnt de terugblik; de lopende dag is voorlopig. Dit is een modelschatting met voorkennis en geen automatisch gewijzigd laadbeleid. Browser- en livecontrole volgen na installatie.

## 2.0.0-dev.250

- Beoordeelt vermindering van netladen ook bij een hogere actuele SOC wanneer de gemeten PV niet boven CENTRAL ligt.
- Vermindert uitsluitend via de bestaande planning, met behoud van het laaddoel en controle van de overige hoofdopdrachten.
- Een gewijzigde SOC kan dezelfde PV-metingen opnieuw relevant maken; identieke herhaalde metingen starten geen nieuwe prijszoektocht.

Na installatie: controleer versie dev.250 en of netladen bij voldoende verwachte energie wordt verminderd.

## 2.0.0-dev.249

- Bewaart de oorspronkelijke SOC-prognose bij het plan, zodat de lijn na een herstart terugkomt bij hetzelfde behouden plan.
- Kan voor bestaande installaties de oorspronkelijke prognose eenmalig uit de diagnosehistorie herstellen, uitsluitend bij overeenkomende plan- en energiepadidentiteit.
- Het oorspronkelijke berekenmoment blijft zichtbaar. Een prognose van een ander plan of een verlopen prognose wordt niet overgenomen.

Na installatie: controleer de SOC-lijn en het oorspronkelijke berekenmoment. De planningslogica blijft ongewijzigd.

## 2.0.0-dev.248

- Herstelt de onterechte melding `daily_reference_household_horizon_incomplete` bij handelssegmenten met tijdgrenzen op fracties van seconden.
- De prognosedekking wordt met exacte tijdsduren gecontroleerd. Afrondingsverschillen veroorzaken hierdoor geen onnodige terugval naar NOM; echte gaten blijven afgewezen.

Na installatie: controleer dev.248 en of NOM- en marktvensters over opeenvolgende berekeningen behouden blijven zonder deze foutmelding.

## 2.0.0-dev.247

- Herkent een historisch gemeten SOC van 100% tijdens het toen geldige hoofdlaadvenster, ook als PicoT op dat moment niet draaide. Het bewijs en de oorspronkelijke laadopdracht blijven bewaard.
- Beoordeelt overbodige herstel-laadsegmenten opnieuw via de canonieke planner. Een achterhaald hoofdlaadsegment wordt niet uitgevoerd terwijl die herbeoordeling nog loopt.
- Gebruikt dezelfde tariefgrenzen bij de berekening van handelscapaciteit en exportsimulatie. Dit voorkomt onterechte afwijzing door een verschil tussen gevraagd en berekend exportvolume.
- Spreadvoorwaarden blijven van toepassing; een groot prijsverschil alleen garandeert geen uitvoerbare marktroute.

Na installatie: controleer dev.247, de historische SOC-herkenning en de nieuwe marktberekening. Werking in Home Assistant moet live worden bevestigd.

## 2.0.0-dev.246

- Verhelpt de StopIteration-crash in de marktplanner bij verschoven tijdgrenzen van de huisverbruiksvoorspelling.
- De exportsimulatie wordt gesplitst op de tariefgrenzen, zodat ieder exportdeel een passend tarief krijgt.
- Een ontbrekende prijsmatch wijst de handelskandidaat af met een expliciete reden. Er wordt geen prijs verzonnen of gedeeltelijke kandidaat gepubliceerd.
- Dagelijkse laadopdrachten, handelsvolume en spreadregels blijven behouden.

Na installatie: controleer dev.246 en of de planner zonder crash blijft draaien. Livewerking moet in Home Assistant worden bevestigd.

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
