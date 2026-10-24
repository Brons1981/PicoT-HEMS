# Eindreserve en uurverwachting

Vervolg op de CV-keten en de eerste extra-laadvergelijking in de volledige dev.314-werkboom. Geen commit, push, release of live apparaatbediening uitgevoerd.

## Reserve zonder nieuw dagdoel

Een verwarmingsprofiel kan nu worden beoordeeld met aanvullend laden wanneer uitsluitend de afgesproken eindreserve tekortschiet. Een afzonderlijke generieke reserveportfolio simuleert extra netladen en beschikbare PV-opname. De bestaande dagopdrachten worden niet heropend; ook als het dagdoel al behaald is, kan een reserveactie worden vastgelegd.

De berekening houdt bestaande laadacties, export, dagdoelen, aanvullende doelen, vermogensgrenzen en reservecheckpoints aan. Tarieven en conversieverliezen komen uit de gewone HEMS-berekening. Kandidaatkeuze verloopt via de gewone Evaluation en PlanBuilder. De berekening van voorstellen schrijft niets. Een gekozen alternatief blijft voorwaardelijk totdat de echte route is vastgelegd en HC opnieuw toestemming krijgt.

Een gedeelde reserveroute heeft eigen opslag en herkomstverwijzingen. Herladen controleert zowel de route als de geprojecteerde checkpointonderbouwing. Bestaande voltooiingsinformatie blijft aan de oorspronkelijke dagopdracht gekoppeld. Vastgelegde reserveacties mogen niet stilzwijgend vervallen bij een andere dag- of marktroute of bij het verlopen van de tijdelijke HC-reservering. Een expliciete planningsreset gebruikt de bestaande herstelprocedure.

De kandidaatzoektocht is begrensd: per startpunt wordt een minimaal aaneengesloten extra laadblok onderzocht, naast PV-opname. Dit is geen bewijs van een globaal optimum over iedere mogelijke combinatie van gescheiden laadblokken. Ontbrekende prijzen, onvoldoende fysieke ruimte of een niet-haalbare reserve leveren geen starttoestemming op.

## Uurverwachting

De uurverwachting wordt alleen opgehaald als de bestaande HA-weerentiteit die functie adverteert. De dagelijkse verwachting blijft afzonderlijk. Temperatuur, wind, bewolking, tijdsdekking en actualiteit worden gecontroleerd. Onbekende toekomstige dag/nacht vereist passende onderbouwing voor beide omstandigheden.

Gemeten leergegevens blijven gemeten gegevens: voorspellingen worden niet als waarnemingen opgeslagen. Voor toekomstige opwarming en handhaven gebruikt HC de conservatieve begrenzing uit passende metingen voor de voorspelde omstandigheden. Een gewijzigde of verlopen verwachting wordt ook vlak voor starten gecontroleerd.

Als de integratie geen uurverwachting ondersteunt, blijft het bestaande gedrag op waargenomen omstandigheden beschikbaar, met zichtbare status. Een ondersteunde maar ontbrekende/onvolledige uurverwachting blokkeert de betreffende optimalisatie; gewone comfortregeling blijft beschikbaar. Zie 2026-10-24-hc-hourly-weather.md.

## Herstel en regressies

De herstelfunctie voor dagopdrachten herkent nu ook gedeelde reserveroutes. Daardoor is haar volledige AST niet langer gelijk aan de eerdere dev.314-kopie. De uitbreiding voegt uitsluitend deze routeherkenning toe; de eerder gerepareerde dagovergang blijft onder de bestaande regressietests vallen.

Gerichte tests gebruiken echte opslag, planning, herladen, voortschrijdende tijd na een behaald dagdoel en de HC/HEMS-uitwisseling. Een onafhankelijke prijstest controleert de keuze voor een goedkoper beschikbaar laadblok. Boven de fysieke capaciteit wordt geen winnaar toegelaten.

Definitieve gecombineerde verificatie volgt hieronder. Geen echte HA-/woningproef en geen volledige repositorybrede typecheck uitgevoerd.


### Definitieve verificatie, 24 oktober 2026

- Gecombineerde HC/HEMS/planner/opslag/herstelreeks: **607 tests en 13 subtests geslaagd**, 215,41 seconden, exitcode 0.
- Inclusief volledige reservering-tot-toestemming-keten voor alleen een eindreservetekort; behoud van dagopdrachten; voortschrijdende tijd na gemeten voltooiing; herstart en herhaalde planning; goedkope prijskeuze; onhaalbare capaciteit; corruptie en gewijzigde beschermde opdrachten; uurdekking en dubbele wintertijduren.
- Vijf voorwaardelijke alternatieven met alleen eindreservetekort samen berekend in 4,71 seconden. Een plan gekozen, geen directe uitvoeringsmacht. Dit is een synthetische prestatieproef, geen garantie voor iedere situatie op de NUC.
- Ruff voor nieuwe/gewijzigde moderne modules en tests geslaagd. F-controles op de betrokken bestaande grote modules geslaagd. JavaScript-syntaxcontrole geslaagd. Manifest compleet; Python-syntaxis van opgenomen bestanden gecontroleerd.
- Herstelcode gecontroleerd met AST-vergelijking: na het weglaten van uitsluitend de vier toevoegingen voor reserverouteherkenning is de functie gelijk aan de dev.314-basis. De gewone dagovergangsregressies zijn tevens uitgevoerd.
- De live uurondersteuning van de huidige HA-weerbron is niet vastgesteld; de functie gebruikt uurdata uitsluitend als de bron die ondersteunt. Geen live woningproef, commit, push of release.

Vervolgcontrole: zie 2026-10-24-hc-release-checks.md voor herstel van de HC-testworkflow,
de volledige HC-testreeks en de nog open publicatiecontroles.
