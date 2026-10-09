# Changelog

## 0.4.0-dev.3

- Optionele lokale Shelly Switch.GetStatus-meetbron via ev_local_rpc_url, eenmaal per seconde gedeeld door EV-sessies en regeling.
- Geen oude HA-EV-meetwaarde gebruiken bij lokale API-uitval; correctie blokkeren voor de bestaande RAW-terugval.
- Behoud echte blokkeerreden en vermeld local_rpc als meetbron. Originele @gielz en HEMS blijven ongewijzigd.

## 0.4.0-dev.2

- Herken een EV-sessie direct bij plug aan en een nieuwe fysieke meting boven 2000 W; geen ingebouwde wachttijd of vermogensschatting.
- Neem gemeten vermogen over en laat de gebruiker de duur invullen. De sessie blijft beschikbaar na plug-uit.
- Herkenning accepteert minuutrapportage tot 75 seconden oud, maar geen meetwaarde van vóór plug-aan.
- Toon meetleeftijd en blokkeerreden in de tijdlijn en het snapshot. P1-regelcorrectie en HEMS blijven ongewijzigd.

## 0.4.0-dev.1

- Optionele duurzame EV-sessies, herkenning na 30 seconden en een bevestigde laadtijdlijn.
- Alleen de expliciet gekozen EV-switch bedienen na bevestigde hervattest; geen opslagaansturing.
- Onderbreken, hervatten, annuleren, schakelbevestiging en harde eindtijd na herstart.
- Afzonderlijk gedateerd sessiesnapshot voor HEMS; meetenergie blijft een integratieschatting.
- Live BMW-hervatten en EV-uitvoering blijven praktische acceptatiepunten.


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
