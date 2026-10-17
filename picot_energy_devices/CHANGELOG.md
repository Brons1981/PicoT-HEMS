# Changelog

## 0.4.0-dev.9

- Sluit batterijondersteuning uit voor alle EV-sessies, inclusief direct laden en eerder opgeslagen sessies.
- Werk ook HEMS bij naar 2.0.0-dev.301 voor de bijbehorende planning en uitvoeringsbeveiliging.

## 0.4.0-dev.8

- Zet een actueel HEMS-laadadvies vast met Automatisch uitvoeren; de knop bevestigt dat de auto aangesloten is.
- Schakel de plug automatisch op de geplande start- en eindtijd; bewaar de uitvoering na herstart en respecteer annuleren en handmatig onderbreken.
- Controleer adviesidentiteit, leeftijd, energie en laadduur voor acceptatie. Een voorlopig advies blijft een vastgezet laadblok en wordt niet automatisch herpland.
- Toon resterende geschatte energie na afloop. HEMS 2.0.0-dev.300 blijft vereist.

## 0.4.0-dev.7

- Vraag HEMS-laadadvies aan met een eindtijd en resterende energie aan de stekker; gebruikt het opgeslagen laadvermogen.
- Toon het geadviseerde aaneengesloten laadblok, geschatte extra kosten en eventuele voorlopige status. Vereist HEMS 2.0.0-dev.300.
- Bewaar aanvragen na herstart en verwerp oud advies na wijzigen, annuleren of starten van een echte sessie.
- Advies schakelt de plug nog niet automatisch. Nu laden en de bestaande EV-regeling blijven beschikbaar.

## 0.4.0-dev.6

- Start een EV-sessie met Nu laden, zonder voorafgaande laadproef of BMW-aansluitdetectie.
- Bewaar een vast laadvermogen en maximale laadduur voor volgende sessies. De startknop bevestigt dat de auto aangesloten is.
- Controleer werkelijk laden na inschakelen; toon ontbrekende metingen of niet gestart laden. Behoud herstart, annuleren en handmatig onderbreken/hervatten.
- HEMS ontvangt de bestaande sessieprognose. Prijsplanning met eindtijd is nog niet toegevoegd.

## 0.4.0-dev.5

- Diagnose downloaden vanuit Energy Devices: meetgegevens van de laatste 48 uur en blijvend bewaarde status- en terugvalgebeurtenissen.
- Legt de oorspronkelijke oorzaak en tijd van een RAW-vergrendeling vast, ook na herstel en herstart.
- Registreert asynchroon; uitval van diagnoseopslag onderbreekt de regeling niet. De bestaande regeling en originele @gielz blijven ongewijzigd.

## 0.4.0-dev.4

- Bewaakt of de werkelijk aangeboden CT-correctie overeenkomt met de bedoelde correctie, met 50 W tolerantie en maximaal vijf seconden overdrachtsvertraging.
- Gelijkblijvend batterijvermogen blokkeert de vrijgave niet meer; EV-, oven- en PV-wisselingen gelden niet automatisch als pendelen.
- Overbrugt korte meetuitval maximaal tien seconden vanaf de oorspronkelijke bronmeting. Herstel geeft direct een nieuwe kandidaat.
- Vergrendelt RAW-terugval bij aanhoudend verkeerde correctie of langdurige meetuitval. De vergrendeling blijft na herstart actief totdat correctie expliciet wordt uitgezet en herstart.
- Behoudt originele @gielz-regeling en bestaande PV-berekening. De bestaande HA-selector moet API-meetleeftijd tot tien seconden toestaan; API-rapportleeftijd blijft drie seconden. Zie DOCS.md.

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

