# DHW-bronwaarden in de woningmetingenexport

De gewone HC-snapshot en bestaande woningmetingenexport bevatten nu `dhw_observations.active` en `dhw_observations.diagnostic`. Dit gebeurt tijdens het verzamelen van metingen, onafhankelijk van een CV-opwarmbeurt. Een uitgeschakelde leerfunctie verhindert deze ruwe registratie niet zolang HC meetgegevens verzamelt.

Bronnen in de lokale addondefaults en voorbeeldconfiguratie: `cv_dhw_active=binary_sensor.dhw_status` en de nieuwe optionele instelling `cv_dhw_diagnostic=sensor.dhw_status`. Bestaande opgeslagen addonopties worden niet automatisch overschreven. Een ontbrekende instelling blijft not_configured, een ontbrekende entiteit missing. Alleen de bestaande binaire reader bepaalt de warmwatermarkering; de diagnostische sensor wordt niet geïnterpreteerd.

Per bron blijven de ruwe status, quality, received, source_updated, source_reported en source_changed bewaard. Er worden geen willekeurige bronattributen gekopieerd. De timestamps krijgen geen betekenis als fysieke kraan-open- of kraan-dichttijd. De ruwe observation-quality is geen garantie dat de status vers is; de bestaande reader blijft haar eigen versheidscontrole uitvoeren. Oude exports/records krijgen bij ontbrekende data geen verzonnen historische waarden.

## Praktijktest na installatie

1. Controleer dat beide entiteiten in de addonopties ingesteld zijn en HC meetgegevens verzamelt.
2. Noteer met seconden de werkelijke tijd waarop de warmwaterkraan open en weer dicht gaat.
3. Laat de registratie daarna minstens enkele minuten doorlopen en download de gewone woningmetingenexport.
4. Vergelijk beide DHW-statussen, bron- en ontvangsttijden en gasrapporten met die werkelijk genoteerde tijden. Herhaal om variatie tussen meldingen te beoordelen; één test bewijst geen maximale vertraging.

Controleer daarnaast of tapwater-warmhouden ook zichtbaar is in deze signalen. De voorlopige marge blijft 90 seconden; deze wijziging stelt geen nieuwe marge vast en geeft geen CV-kostenvergelijking vrij. Alex heeft bevestigd niet op gas te koken.

## Verificatie

Tests doorlopen snapshot, SQLite-opslag, opnieuw openen en de echte gepagineerde export. Ze controleren ruwe binaire en tekstwaarden, afzonderlijke wijzigings-/rapport-/ontvangsttijden, ontbrekende bronnen en het weglaten van een privé-bronattribuut. Geen live configuratie of hardware gewijzigd.

Verse verificatie: 282 tests en 13 subtests geslaagd in 78,47 seconden. Ruff op de gewijzigde tests en git diff --check geslaagd. De F-controle van core.py meldt alleen de bestaande ongebruikte datetime.timezone-import (F401); de diff bevestigt dat deze import niet is gewijzigd. Niet live geactiveerd, gecommit of gepusht.
