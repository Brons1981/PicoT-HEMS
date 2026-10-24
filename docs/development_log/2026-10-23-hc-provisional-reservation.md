# HC-plan vooraf meenemen in HEMS

HEMS neemt nu ook het gekozen maar nog niet gestarte verwarmingsprofiel mee in zijn verbruiksprognose. Dit is een voorlopige reservering in de planning, geen gegarandeerde hoeveelheid batterij-energie. De bestaande regels voor batterijafspraken en het opnieuw beoordelen van de start blijven gelden.

## Voorwaarden en levensduur

HC publiceert `hc-energy-reservation:v1` op `sensor.picot_hc_energy_reservation`. Dat gebeurt alleen voor een vastgelegd startvoornemen met een passende HEMS-keuze, ingeschakelde proefoptie in het comfortschema, geldige meetgegevens en een nog geldig startvoornemen. De bestaande controles op schema- en verwarmingsrevisie, automatische verwarming, leerinstellingen, comfortvenster, afkoeling en uitgeschakelde bronnen blijven daarbij van toepassing. Een bronfout of ontbrekende prijs verhindert reserveren.

De melding bevat uitsluitend voorstelidentiteit, vingerafdruk, planidentiteit, status en tijden. HEMS haalt het energieprofiel uit zijn eigen opgeslagen goedkeuring. Onbekende profielen, extra velden, toekomstige meldingen en een geldigheid langer dan 120 seconden worden geweigerd. Alleen het selecteren of toestaan van een plan reserveert nog niets: HC moet expliciet melden dat het plan daadwerkelijk voorbereid wordt.

Elke bevestiging geldt maximaal twee minuten. Zonder nieuwe bevestiging vervalt de voorlopige toevoeging automatisch. Uitschakelen, gewijzigde instellingen of een ongeldig startvoornemen leveren een annulering op. Een geannuleerd profiel kan niet door een latere melding van dezelfde keuze worden heropend. Een nieuwer goedgekeurd profiel kan het oude vervangen; oudere keuzes kunnen de nieuwere reservering niet terugdraaien.

De laatste bevestiging blijft kort geldig tijdens het wachten op opdrachtfeedback en het ophalen door HEMS. Een bevestigde uitvoering vervangt de reservering zonder beide op te tellen. Beide tabellen worden in één SQLite-leestransactie ingelezen om een overgang tijdens een herberekening consistent te houden. Annuleren van een reservering verwijdert nooit een reeds bevestigd lopend profiel.

Een geldige reservering mag langer bestaan dan de oorspronkelijke beoordeling, mits HC haar blijft bevestigen. Dat verlengt **geen starttoestemming**. Vlak voor starten blijven een actuele HEMS-beoordeling, exact passende starttoestemming en alle lokale startcontroles vereist. Herstart van HC hervat automatische uitvoering niet; een HEMS-herstart herstelt alleen nog niet verlopen reserveringen.

## Herbeoordeling zonder dubbeltelling

Het vooraf opgenomen profiel wordt via dezelfde invoerroute verwerkt als bevestigd verbruik. Bij aantoonbare toeschrijving vervangt het de al verwachte component. Voor één voorlopige reservering maakt HEMS een nieuwe vervangingsbasis die ook de reservering bevat. Daardoor vervangt een volgend voorstel het eerder gereserveerde profiel in plaats van dat beide worden opgeteld. Een herbeoordeling met exact hetzelfde profiel laat de berekende energie onveranderd.

Deze nieuwe basis wordt alleen aangeboden bij volledige, passende onderbouwing. Aantoonbaar nulverbruik is geldig; ontbrekende componenten zijn dat niet. Bij ontbrekende onderbouwing telt HEMS conservatief op en biedt geen nieuwe vervangingsbasis. Voor een al lopend profiel blijft heronderhandeling uitgesloten in deze stap.

De diagnostiek onderscheidt `reserved_load_count` en `running_load_count`. De toelichting bij de bestaande proefoptie beschrijft dat HEMS het profiel vooraf meeneemt, zonder batterijdekking voor alle comforturen te beloven. MEP ontvangt uitsluitend de aangepaste algemene energieprognose, geen apparaatkennis. De thermostaatregeling, minimale uitschakeltijd, overige ruimtes en CV-aansturing zijn niet aangepast.

## Verificatie en grenzen

De eerste regressietest faalde omdat vooraf reserveren nog niet bestond. De toegevoegde controles gebruiken de echte opslag, HEMS-beoordeling, profielvervanging en HC-runtime met nagebootst HA-transport. Ze controleren reserveren vóór starten, vervallen en herstel uit opslag, annulering, ongeldige meldingen, verlengen zonder verlengen van starttoestemming, geen dubbele telling bij herbeoordeling of start, conservatieve toevoeging, nulverbruik en ontbrekende onderbouwing. De HC-test controleert ook daadwerkelijke publicatie via de runtime en het uitschakelen van de proefoptie.

Er zijn geen echte apparaten aangestuurd en geen live instellingen veranderd. Werkelijke netwerktiming, gerealiseerde SOC en financiële opbrengst zijn niet live geverifieerd. Geen commit, release of publicatie uitgevoerd.

Laatste volledige verificatie na alle codewijzigingen: **222 tests en 6 subtests geslaagd in 111,46 seconden**. De reeks omvat `hc-comfort-work/tests` plus de HC-tests voor energievoorstellen, outlook, opwarmenergie, opwarmplannen, volledige starts, uitgestelde starts, leren, startvoornemens en startuitvoering. Ook een vertraagde annulering van een oude keuze na goedkeuring en reservering van een nieuw profiel is getest met de echte HEMS-beoordeling. Ruff, F-controles op de grote HC-runtime en gedeelde fixture, `node --check` op app.js en `git diff --check` slagen.
