# ADR 019 — Actuele temperatuurontvangst

Live bewijs 16 september: HA-sjabloon om 22:05 toont boven `last_reported`
22:04:05, terwijl de HC-export om 22:05:08 nog 21:53:06 bevat. HA 2026.9.2
cachet de JSON-statusweergave; een ongewijzigde melding vernieuwt de interne
ontvangsttijd zonder die JSON opnieuw op te bouwen. De oude tijd mag geen
sensoruitval bewijzen. De maximale meetleeftijd wordt niet verruimd.

HC leest na `/api/states` één `/api/template` voor uitsluitend de geconfigureerde
drie ruimtetemperaturen en buitentemperatuur. Het sjabloon leest `state`, eenheid,
`last_updated` en `last_reported` rechtstreeks, zonder `as_dict` of samengestelde
oude waarde/nieuwe tijd. Dit gebeurt ook bij de verse uitlezing vóór een opdracht.

Ongeldige/ontbrekende antwoorden of transportfouten markeren de betreffende
temperatuurcontrole als mislukt. De waarde blijft voor inzicht zichtbaar, maar
kan geen warmtevraag starten. Bronstanden blijven beschikbaar voor stoppen van
eigen verwarming. Geen fallback naar polltijd, geen nieuwe aannames over ontvangst.
Een actuele gatewaymelding bewijst niet zelfstandig dat elke radiosensor werkt;
dit blijft afhankelijk van de gegevens en beschikbaarheid die HA ontvangt.

Regressie: oude REST-tijd + actuele template-melding werkt; actuele template-waarde
wint van oude REST-waarde. Oude, toekomstige, ontbrekende en foutieve meldingen
blokkeren; template-uitval stopt eigen bron. Timer gebruikt dezelfde meetcontrole.
