# HEMS-afwijzingsvoorwaarden terug naar HC

Op de gecombineerde dev.314-basis verwerkt de HC-voorstelgenerator nu actuele HEMS-afwijzingen. De runtime geeft de ontvangen HA-statussen door aan de generator. Alleen een beoordeling van exact het eigen actuele voorstel, met passende fingerprint, revisie, prognosebasis, vervangingsbasis en geldigheid wordt verwerkt. De bestaande assessment-reader blijft de validatiegrens.

## Geimplementeerd

Wanneer alle afgewezen alternatieven een geldige `end_before`-voorwaarde hebben, gebruikt HC de strengste eindtijd voor een nieuwe berekening. De gewone meetmodellen, comfortgrenzen, doeltemperatuur en deadlinecontroles blijven gelden. De bestaande opwarmenergie wordt niet verlaagd om het voorstel passend te laten lijken. Een nieuwe request-ID vraagt een nieuwe beoordeling; de geldigheid loopt niet voorbij de oorspronkelijke voorwaarden.

Dezelfde reactie wordt maar eenmaal verwerkt. Een volgende afwijzing op dezelfde basis moet de eindtijd echt aanscherpen, anders stopt HC met opnieuw aanbieden. Ontbrekende/ongeldige voorwaarden, een onvolledige afwijzingsset, een algemene blokkering of een verzoek om een ander verbruiksprofiel trekken het voorstel in. Dat stopt geen verwarming: de gewone comfortregeling blijft verantwoordelijk. Metingen voor de leerfunctie gaan door. Een nieuwe HEMS-basis wist de oude beperkingen.

Een `verified_scaled_profile` is nadrukkelijk geen machtiging om het gemeten energieprofiel te halveren. Voor zulke voorwaarden en `revise_replacement_profile` ontbreken nog de alternatieve, gemeten CV-/comfortprofielen. HC wacht daarvoor op nieuw passend bewijs of een nieuwe basis. Deze stap maakt de volledige automatische onderhandeling dus nog niet af.

## Grenzen en vervolg

Geen HEMS- of MEP-productiecode gewijzigd; de dev.314-nachtreparatie blijft behouden. Geen nieuwe verwarmingsopdrachten, temperatuurverlagingen, aanvullende laadroute of CV-planuitvoering toegevoegd. De aparte CV-meter of een expliciet gekozen schatting blijft een open invoerbesluit. Economische CV-alternatieven en plannen over het gehele comfortvenster blijven vervolgwerk.

Tests gebruiken de echte meetmodellen en voorstelgenerator met drie gemeten opwarmbeurten per comfortdoel. Gedekt: kortere geldige horizon, een eindtijd voor de comfortdeadline, schaalvoorwaarde zonder bewijs, foutieve fingerprint, gedeeltelijke afwijzing, verlopen antwoord, andere basis, tijdzone ontbreekt, vreemd voorstel, late herhaling en stoppen van een herhaallus. Nieuwe voorstellen bevatten maximaal vijf alternatieven en blijven apparaatvrij.

Verse gecombineerde verificatie: 407 tests en 13 subtests geslaagd in 222,29 seconden, inclusief de dev.314-nachtreparatie en aangrenzende laadroute-/prognosetests. Ruff op de gewijzigde modules en tests en F-controle op de HC-runtime geslaagd. Geen release, commit, push of live wijziging.
