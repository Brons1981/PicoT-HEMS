# Vertraagde warmwaterstatus: 90 seconden nacontrole

Alex bevestigt `binary_sensor.dhw_status` en `sensor.dhw_status`, een gemelde vertraging van 30 tot 60 seconden en geen gas voor koken. De betekenis van de niet-binaire sensorwaarden is niet bevestigd; de lokale addondefaults en voorbeeldconfiguratie gebruiken daarom `binary_sensor.dhw_status`. Bestaande opgeslagen addonopties worden hierdoor niet automatisch gewijzigd. Geen live configuratie aangepast.

De bestaande opwarmmeting wordt op het oorspronkelijke meeteinde opgeslagen met `gas_screening.provisional=true`, `review_until` en `delay_margin_seconds=90`. De 90 seconden bestaan uit de gemelde maximale vertraging van 60 seconden plus het gebruikelijke HC-meetinterval van 30 seconden; dit is een voorlopige aanname, geen gemeten garantie.

HC verwerkt warmwaterstatus ook onafhankelijk van de lopende verwarmingsvraag. Een on-melding binnen 90 seconden na het meeteinde markeert de vorige meting alsnog als `dhw_observed`: de mogelijke terugwerking is dus 90 seconden. Het resultaat blijft vermengd na een volgende off-melding. Na de marge wordt provisional false; `checked_at` bewaart de afrondtijd. Gasdelta, stroomdelta, meeteinde en opwarmduur blijven onveranderd. De nacontrole voegt geen energie toe.

Een ontbrekende/ongeldige bron, sensorwissel, herstart of meer dan 60 seconden tussen nacontroles maakt de dekking onvolledig. Waargenomen warmwater blijft daarbij bewaard. Voorlopige records blijven persistent, maar na herstart wordt niet aangenomen dat de tussenliggende periode gecontroleerd is. Het dashboard toont het wachten op vertraagde meldingen.

Geen gas voor koken is bevestigd. Dat maakt afbakening eenvoudiger, maar nog geen bewijs dat elk gasinterval zonder waargenomen warmwater volledig ruimteverwarming betreft. Korte activiteiten tussen polls, ketelcomfort/warmhouden en de timing van gasrapporten zijn nog niet in de praktijk gecontroleerd. Daarom blijven heating_only_confirmed, comparison_eligible en execution_authorized false. Geen wijziging aan comfortregeling, schakeltijden, HEMS of MEP.

Tests: late on-melding na 60 seconden, volledige off-nacontrole, ontbrekende melding, sensorwissel, gat van 90 seconden, herstart, opslag/herladen en ongewijzigde gas-/elektriciteitsdelta. Bestaande runtime-integratietest controleert de normale verwarmingsopdracht met fake HA-transport; er is geen hardwaretest uitgevoerd.

Verse verificatie: 280 tests en 13 subtests geslaagd in 55,85 seconden in de gecombineerde HC/HEMS-regressieselectie. Ruff, JavaScript-syntaxis en git diff --check geslaagd. Niet live geactiveerd, gecommit of gepusht.
