# Dashboard: handelen zonder zoeken

Status: lokaal geïmplementeerd na expliciet akkoord van Alex; basis dev.317, PR #727.
Geen release, installatie of livewijziging uitgevoerd.

## Contract en verantwoordelijkheid

Alex verwijdert de losse panelen Huidige planning en besluit, PV Energy Timeline,
Verwacht huishoudverbruik, Energieplan batterij, Onderliggende energiekansen en
Terugblik netladen. Bronnen en pipeline zijn alleen interessant bij fouten.
Maak een nieuw plan moet direct bovenaan zichtbaar zijn. De vergelijking hoort
bij Behoud automatisch plan, met twee routes op dezelfde tijdschaal, verschillen
in tekst, en behoud van de bestaande keuzebevoegdheid.

De eerste foutgrens was Projection/UI: losse opgeslagen planhistorie is niet de
vergelijking van de twee aangeboden routes. Bovendien noemde stap 1 invoer altijd
compleet, ook bij health=fault. ADR-017/030/035 en het canonieke pipelinecontract
blijven leidend: weergave presenteert bestaande feiten. Het expliciete gebruikers-
besluit vervangt de oude eis om negen technische kaarten zichtbaar te tonen;
canonieke records blijven beschikbaar via API en diagnose.

Geen wijzigingen aan MEP, Evaluation, plancommitment, dispatch, dagdoelen,
stand-bykeuze, financiële berekeningen, HC of ED. Terugval is de dev.317-weergave;
extra timeline-velden zijn additief. Geen migratie of planreset vereist.

## Uitwerking

- Resetknop boven de navigatie; bevestiging en bestaande resetactie behouden.
- Genoemde panelen en technische informatiebomen verdwijnen. Instellingen direct
  toegankelijk; geen geneste uitklapvelden. Prijzen/PV/SOC blijven de hoofdgrafieken.
- Bovenaan concrete bron-/stapfouten, de betreffende entiteit en bekende oorzaak;
  optionele ED-catalogusuitval heet geen bewezen planningsinvoeruitval.
- Geen generieke groene/bronnen/pipelinekaarten. Handmatige blokkade met vrijgave-
  knop verschijnt direct bovenaan. Verbindingsfouten worden weer zichtbaar na een
  gezonde weergave. Fouten en override verversen ook tijdens invoer/tekstselectie.
- Meetouderdom en verouderingswaarschuwing blijven op de actieve-moduskaart.
- Routevoorstel toont eigen automatische/PV-tijdlijn, gedeelde absolute tijdschaal,
  Amsterdamtijd met UTC-offset, gelijke kleuren, verschilmarkeringen en tekst.
  Full schedules komen rechtstreeks uit bestaande canonieke kandidaatintervallen;
  maximaal 512 met expliciete afkapping. Geen planning/simulatie in de browser.
- Oude voorstellen tonen alleen hun bewaarde laadvensters met expliciete beperking;
  ontbrekende intervallen worden nooit als stand-by of ontladen ingevuld.
- Geen haalbaar alternatief: één automatische tijdlijn en duidelijke titel.
  Voorstel met gewijzigde planidentiteit/revisie: expliciet verouderd, geen toepas-
  knoppen. Servervalidatie en verzoekcontract blijven gelijk.
- Vergelijkingsprijs blijft een prijs per opgeslagen kWh, niet een verzonnen totale
  besparing. Identieke modi/tijden/instellingen worden expliciet als gelijk gemeld.
- Historische vergelijking verhuist naar Historie en gebruikt dezelfde grafische
  weergave. Selectie wijzigt de actieve grafiek/SOC/het plan niet.

## Verificatie en grenzen

Zes nieuwe acceptatiegevallen faalden vooraf op de verwachte ontbrekende UI-grens;
drie timeline-producerregressies faalden op het ontbrekende evidenceveld.
Node-DOM-tests controleren echte renderfuncties, verschillen bij gelijke laad-
vensters, DST, gedeelde schaal, geen mutatie/actie bij render, verlopen planrevisie,
geen alternatief, beperkte oude data en gelijke exporthoeveelheid per tijdseenheid.

De definitieve testuitslag wordt hieronder toegevoegd. Lokale HTTP-sockettests
worden door Windows-sandbox WinError10013 geblokkeerd; geen productfout verondersteld.
Er is geen aangesloten browser beschikbaar voor visuele eindcontrole. De laatste
Downloads-diagnose is nog 2026-10-24T213406.439 (vóór deze melding/dev.317); de huidige
live invoerfout is daarom niet vastgesteld als ED-uitval. Nieuw diagnosebewijs is
nodig voor die specifieke live oorzaak, los van de gerealiseerde foutweergave.


Definitieve lokale controle: 167 tests geslaagd, 5 HTTP-endpointtests uitgesloten
wegens de genoemde socketbeperking. De set omvat bestaande UI/projecties, prijzen,
financiën, nacht-PV, startup, override/reset, historie en routekeuze-policy/store/
pipeline, plus de nieuwe aandacht/vergelijkingstests. Ruff op alle gewijzigde
Python-bestanden geslaagd; mypy op beide productiebronbestanden geslaagd; volledige
embedded JavaScript-syntaxcontrole met Node geslaagd. Geen browser-/HA-liveclaim.

Onafhankelijke review heeft verborgen verbindingsfouten, override-overschrijving,
meetouderdom, primitiefnamen, gelijke export per tijdseenheid en legacy-tabselectie
laten controleren/herstellen. Werkelijke renders controleren nu ook geen-alternatief-
voorstellen en fout/override-updates tijdens uitgestelde volledige refresh.
