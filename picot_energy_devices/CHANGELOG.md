# Changelog

## 0.3.0-dev.1

- Optionele EV-correctie op basis van fysieke RAW-P1, getekend actueel Zendurevermogen en EV-meter.
- Onafhankelijke 1s-meetlus, conservatieve 20W-marge, versheidscontrole en Shelly-compatibele lees-API op poort 8101.
- Afzonderlijk beleidssnapshot voor HEMS; Energy Devices kiest geen batterijmodus.
- Correctie standaard uit. Activering vereist de meegeleverde versheidsbewaking in de bestaande @gielz-automatisering; zie de testhandleiding.

## 0.2.0

- Leer volledige apparaatprogramma’s in met **Start inleren** en **Programma klaar**. Rustige fases splitsen een opname niet meer.
- Bekijk het vermogensverloop en de metingen, wijzig de programmanaam of verwijder een opname.
- Lopende opnames blijven na een herstart bewaard. Meetuitval en lange meetgaten worden zichtbaar; onvolledige energiegegevens tellen niet als volledig leerprofiel.
- Automatische sessiedetectie is voor deze inleerfase uitgeschakeld. Oude automatische sessies tellen niet mee en kunnen na bevestiging worden gewist.
- PicoT HEMS blijft op dev.248. Deze release voegt geen planning of apparaatsturing toe.

Na installatie: start een proefopname, controleer het vermogensverloop en rond de opname af. De browserweergave moet nog in Home Assistant worden bevestigd.

## 0.1.0

Eerste onafhankelijke Energy Devices-add-on met apparaatregistratie en automatische sessieprofielen.
