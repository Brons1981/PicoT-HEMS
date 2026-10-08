# Changelog

## 0.3.0-dev.2

- Verwijdert de onterecht meegeleverde @gielz-wrapper. @gielz-automatiseringen, marges, modi en noodstop blijven origineel.
- De CT REST-definitie markeert ontbrekende/ongeldige JSON-vermogensdata expliciet als niet beschikbaar; geen fictieve 0 W.
- Na een onderbreking in de meetlus vraagt herstel opnieuw drie bruikbare controles.
- Offline getoetst met de oorspronkelijke NOM-takken en oorspronkelijke één-minuut-noodstop. Zie de handleiding voor de terugvalbeperkingen.

## 0.3.0-dev.1

- Optionele EV-correctie op basis van fysieke RAW-P1, getekend actueel Zendurevermogen en EV-meter.
- Onafhankelijke 1s-meetlus, conservatieve 20W-marge, versheidscontrole en Shelly-compatibele lees-API op poort 8101.
- Afzonderlijk beleidssnapshot voor HEMS; Energy Devices kiest geen batterijmodus.
- Correctie standaard uit. @gielz blijft origineel; alleen de bestaande P1-bron wordt aangeboden via de lees-API. Zie de testhandleiding.

## 0.2.0

- Leer volledige apparaatprogramma’s in met **Start inleren** en **Programma klaar**. Rustige fases splitsen een opname niet meer.
- Bekijk het vermogensverloop en de metingen, wijzig de programmanaam of verwijder een opname.
- Lopende opnames blijven na een herstart bewaard. Meetuitval en lange meetgaten worden zichtbaar; onvolledige energiegegevens tellen niet als volledig leerprofiel.
- Automatische sessiedetectie is voor deze inleerfase uitgeschakeld. Oude automatische sessies tellen niet mee en kunnen na bevestiging worden gewist.
- PicoT HEMS blijft op dev.248. Deze release voegt geen planning of apparaatsturing toe.

Na installatie: start een proefopname, controleer het vermogensverloop en rond de opname af. De browserweergave moet nog in Home Assistant worden bevestigd.

## 0.1.0

Eerste onafhankelijke Energy Devices-add-on met apparaatregistratie en automatische sessieprofielen.
