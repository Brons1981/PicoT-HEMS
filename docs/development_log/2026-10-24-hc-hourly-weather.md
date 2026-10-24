# Uurverwachting in verwarmingsplannen

HC kan de door de bestaande HA-weerbron aangeboden uurverwachting gebruiken voor beneden. De integratie vraagt uitsluitend `weather.get_forecasts` met `type: hourly` wanneer de bron de officiële hourly-capability (bit 2) meldt. De bestaande dagverwachting blijft afzonderlijk beschikbaar; dagregels worden nooit als uren behandeld.

## Gegevens en terugval

De uurcache bevat expliciet `ready`, `unsupported`, `unavailable` of `stale`. Succesvolle resultaten worden maximaal iedere dertig minuten opgevraagd, mislukte pogingen maximaal iedere vijf minuten. Geldigheid voor plannen is maximaal één uur na ontvangst. Een mislukte vernieuwing maakt het oude uurresultaat direct onbruikbaar. Deze leeftijd betreft ontvangst door HC; een afzonderlijke uitgiftetijd van de weerprovider levert de HA-actie niet.

Regels moeten oplopend exact een uur uit elkaar liggen, met tijdzone, bekende temperatuur- en windeenheden en eindige temperatuur/windwaarden. Een volgend tijdpunt bewijst de eindgrens; het laatste tijdpunt wordt niet vanzelf tot een extra uur verlengd. Ontbrekende of ongeldige gegevens en gaten leveren geen planonderbouwing op.

Een bron zonder hourly-capability blijft de bestaande regeling op waargenomen weer gebruiken. De interface vermeldt dit expliciet. Als de bron hourly wel ondersteunt maar de gegevens verouderd, onvolledig of niet beschikbaar zijn, wachten nieuwe weerafhankelijke voorstellen. Normale thermostaatregeling blijft beschikbaar. Er is geen nieuwe weerprovider geïnstalleerd en er is niet live vastgesteld welke capability de huidige bron aanbiedt.

## Berekening en uitvoering

Opwarmen, handhaven en wachten gebruiken een conservatieve bovengrens van de empirische ramingen voor **alle** uurcondities binnen het relevante venster. Binnen-/buitentemperatuur, wind, bewolkingsgroep en de bestaande sensoridentiteiten blijven aan de onderbouwing gekoppeld. Er worden geen verliescoëfficiënten verzonnen en toekomstige omstandigheden worden niet als echte metingen opgeslagen.

Omdat HA voor hourly meestal geen dag/nachtveld levert, gebruikt HC alleen een expliciet booleaans veld of de ondubbelzinnige voorwaarden `sunny`/`clear-night`. Bij overige omstandigheden is onderbouwing voor zowel dag als nacht vereist en geldt de hoogste raming. De huidige zonstand wordt nooit naar een toekomstig uur gekopieerd.

Voor CV-plannen worden gas, opwarmduur, elektrisch hulpverbruik, handhaven en naloop gezamenlijk begrensd. De gasraming gebruikt dezelfde toekomstige voorwaarden als de elektrische raming. Een gewijzigde uurcache maakt een wachtend voorstel ongeldig en laat het opnieuw beoordelen. Een toekomstig weersverschil op zichzelf is bij een uurplan geen sensorwissel; vóór starten worden wel opnieuw actuele én toekomstige ramingen, de afkoelgrens en de gebruikelijke HEMS-toestemming gecontroleerd. Een al gestarte verwarming wordt niet uitsluitend door een verlopen uurverwachting uitgezet.

Dit is een bovengrens over het venster, geen exacte uur-voor-uur simulatie van warmteopslag. Het kan daardoor eerder geen economisch alternatief vinden of verbruik te hoog ramen. Ontbrekend bewijs wordt niet door extrapolatie vervangen.

## Verificatie

- Nieuwe contracttest faalde vóór implementatie doordat de hourly-module ontbrak.
- Gerichte tests controleren het expliciete HA-hourly-verzoek, caching, fouten, tijdzones, gaten, dagelijkse versus uurlijkse regels, dekking en geldigheid.
- Echte energiemodellen tonen een stijging van 750 naar 1500 W bij onderbouwd kouder toekomstweer, zonder meetrecords te wijzigen.
- CV-recepten nemen hogere toekomstige gasramingen mee voor zowel opwarmen als handhaven.
- De runtime haalt hourly en daily afzonderlijk op. De startcontrole laat een ondersteund uurplan starten en blokkeert een verlopen/niet meer ondersteunde verwachting of niet onderbouwde toekomstige wind.
- De bestaande weather-testfixture is hersteld: een booleaanse testvlag overschreef `unittest.fail`, en de verwachting telde inmiddels toegevoegde niet-weerpublicaties ten onrechte mee als weerservice-aanroepen.

De brede gerichte HC-reeks slaagde met 100 tests en 13 subtests (38,44 s). De definitieve nieuwe uurtests en lintuitslag staan in de overkoepelende overdracht. Geen live acties, release, commit of push uitgevoerd.

Bronnen voor het HA-contract: https://www.home-assistant.io/actions/weather.get_forecasts/ en https://github.com/home-assistant/frontend/blob/dev/src/data/weather.ts (24 oktober 2026 geraadpleegd).
