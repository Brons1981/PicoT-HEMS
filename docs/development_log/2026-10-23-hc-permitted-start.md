# HC: uitvoering van een bevestigde start beneden

De gekozen start kan nu via de bestaande verwarmingsregelaar worden uitgevoerd. De instelling `energy_start_enabled` staat centraal in het comfortschema en is standaard uit, ook bij bestaande opgeslagen schema's. Het dashboard noemt deze proefoptie **Gekozen start beneden automatisch uitvoeren**. Automatische verwarming, een actief schema en leren moeten eveneens ingeschakeld zijn.

## Toestemming en uitvoering

HEMS publiceert een afzonderlijke `hc-energy-start-permit:v1` op `sensor.picot_hems_hc_start_permit`, nadat de HC-keuzebevestiging tegen zijn eigen actuele beoordeling en het opnieuw uitgelezen voorstel is gecontroleerd. De oorspronkelijke adviesbeoordeling en keuzebevestiging blijven `execution_authorized=false`; alleen de afzonderlijke starttoestemming geeft toestemming voor initiatie. De toestemming bevat uitsluitend voorstel-/planidentiteit, vingerafdruk en geldigheid. MEP krijgt geen apparaatkennis.

De toestemming verloopt uiterlijk met de oorspronkelijke beoordeling. Herhaald controleren verlengt haar niet. HC verlangt bij de start zowel deze exact passende toestemming als de actuele, passende beoordeling. Bij een nieuw voorstel of ingetrokken keuze past de oude toestemming niet meer. Een mislukte transportactie kan een oude HA-status laten staan, maar maakt de vastgelegde afloop niet langer.

Een vastgelegde start kan vanaf 30 seconden vooraf opnieuw aan HEMS worden aangeboden. HC probeert de start alleen op of binnen 30 seconden na de gekozen tijd. Deze beperkte uitvoeringstolerantie is onderdeel van deze proef; het energieprofiel blijft een raming. HC controleert opnieuw of de volledige opwarming vóór het comfortvenster past en of de gemeten opwarmenergie, duur en handhaaflast binnen de beoordeelde ramingen blijven.

De opdracht loopt via `Heating.action` en `Control.submit`, inclusief 180 seconden minimale uitschakeltijd, bestaande bronbeperkingen en een verse HA-uitlezing met herbeoordeling vlak vóór verzending. De verwijzing naar het startplan wordt samen met het eigendom van de opdracht opgeslagen voordat een klimaatopdracht wordt verstuurd. Opslagfouten voorkomen verzending. De bestaande commandostatus en foutafhandeling blijven verantwoordelijk voor bevestiging en het voorkomen van automatisch herhalen.

Na starten bewaart HC het gekozen temperatuurdoel tot het comfortvenster begint. Verlopen toestemming veroorzaakt geen uit-opdracht of terugval naar de lagere afwezigheidstemperatuur. De gewone comfortregeling neemt daarna over. Handmatige bediening en gewijzigde schema-/verwarmingsinstellingen blijven voorgaan. Een herstart hervat het economische startplan niet; automatische verwarming wordt zoals voorheen uitgeschakeld.

Bij een expliciete schemawijziging, bijvoorbeeld inschakelen van de proefoptie, kan een nieuw voorstel met een nieuwe HEMS-beoordeling opnieuw een start vastleggen. Oude goedkeuring wordt niet hergebruikt. Zonder zo'n wijziging verschuiven herberekeningen een vastgelegde start niet.

## Beperkte eerste uitvoeringsstap

- Alleen de airco beneden kan via deze koppeling starten. Gelijktijdige zelfstandige warmtevraag boven en de badkamerregeling blijven bestaan. CV-startplannen worden nog niet uitgevoerd.
- De koppeling kan eerder starten dan de gewone comfortstart; hij stelt die gewone start nog niet uit. Als de gewone regeling eerder warmte vraagt, krijgt comfort voorrang en vervalt het startvoornemen.
- Er worden geen nieuwe economische uit-opdrachten geïntroduceerd. Bereiken van de temperatuur geeft geen uit/aanregeling.
- HEMS beoordeelt de start nog op de behouden batterijroute. Dit is geen energie- of SOC-reservering voor de gehele verwarmingsperiode, geen nieuwe laadroute en geen gegarandeerde besparing. Deze beperking staat ook bij de proefoptie in het dashboard.
- Economisch gekozen starts worden niet gebruikt om de oorspronkelijke vaste voorverwarmtijd te kalibreren; die zouden een andere proefopzet vormen. Gemeten volledige startenergie kan wel via de bestaande meetroute worden verzameld.

## Verificatie

De HC-tests gebruiken de echte Runtime, regelaar, opslag, meetmodellen en commandocontrole, met nagebootst HA-transport. De HEMS-tests controleren de echte beoordeling en keuzebevestiging voordat de starttoestemming wordt gemaakt. Positief getest: één start, handhaven na verlopen toestemming en een gelijktijdige zelfstandige warmtevraag boven. Negatief getest: ontbrekende/verlopen/niet-passende toestemming, vervangen of afgewezen voorstel, intrekking tijdens de laatste HA-uitlezing, ontbrekende meter, minimale uitschakeltijd, opslagfout, schemawijziging, handmatige overname en herstart. De proefinstelling krijgt typecontrole en wordt bij oudere schema's uit toegevoegd.

Geen echte apparaten aangestuurd, geen release gemaakt en geen live instelling gewijzigd. Browserbediening en echte HA-transporttiming zijn niet getest.

Een aanvullende regressietest toonde tijdens de eindcontrole dat een nieuw beoordeelde inhoud met hetzelfde requestnummer de oude starttoestemming nog kon passeren. HC vergelijkt nu ook de volledige voorstelvingerafdruk van de actuele beoordeling met de starttoestemming. De test faalde eerst doordat de nagebootste klimaatopdracht werkelijk werd verstuurd en slaagde na deze controle. Een numerieke `1` geldt bovendien niet als de expliciete boolean-toestemming `true`.

Laatste volledige verificatie na alle codewijzigingen: **196 tests en 6 subtests geslaagd in 93,29 seconden**. De reeks omvat `hc-comfort-work/tests` plus de HC-tests voor energievoorstellen, HEMS-outlook/runtime, opwarmenergie, opwarmplannen, volledige starts, uitgestelde starts, leren, vaste startvoornemens en startuitvoering. Ruff slaagt voor de gewijzigde energiemodules en tests; F-controles slagen voor Runtime, Heating en Schedule. `node --check` voor app.js en `git diff --check` slagen eveneens. Geen commit of publicatie uitgevoerd.
