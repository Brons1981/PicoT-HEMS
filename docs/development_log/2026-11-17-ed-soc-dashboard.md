# ED dev.17: SOC en laadpaneel

Een BMW-SOC van 72% bleef ongewijzigd na het aansluiten en werd na 30 minuten afgewezen. De planner bleef daardoor wachten zonder bruikbare uitleg.

Een ouder rapport is nu bruikbaar binnen dezelfde aansluiting als de kabelstatus recent gecontroleerd is en geen later laadvermogen is waargenomen. Een rapport van vóór het aansluiten wordt geweigerd. De geldigheid wordt opnieuw beoordeeld bij een opdracht. Onbeschikbare, ontbrekende, toekomstige en verouderde metingen krijgen een concrete uitleg met bron, waarde en tijd.

Het laadpaneel staat boven de technische onderdelen. Status, acties en opdracht staan bij elkaar; instellingen en sensordetails zijn inklapbaar. Bestaande instellingen en sessies blijven behouden.

Validatie vóór publicatie: 153 relevante tests geslaagd, één lokale sockettest uitgesloten; Ruff en strikte Mypy geslaagd; JavaScript-syntax, unieke DOM-ID's en rendering met ontbrekende SOC gecontroleerd. Nieuwe regressies omvatten herstart, opnieuw aansluiten, laadvermogen en de 72%-naar-80%-opdracht van 936 Wh bij 11,7 kWh rekenbasis. Volledige CI wordt op de release-PR uitgevoerd. Geen live auto- of visuele browsertest; het eindpercentage blijft een benadering.
