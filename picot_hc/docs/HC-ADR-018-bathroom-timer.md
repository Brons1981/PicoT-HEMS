# ADR 018 — Tijdelijk badkamerdoel

De gebruiker vraagt instelbare minuten en temperatuur met één startknop.
Een opgeslagen timer geeft alleen badkamer een tijdelijk doel. Hij activeert
geen andere bronnen en vereist geen algemeen enable of tarief: er is slechts
één badkamerbron. De bestaande temperatuurterugkoppeling, hysterese, rusttijd,
meetleeftijd, bronbeschikbaarheid en opdrachtregistratie blijven leidend.

POST /api/heating/timer gebruikt CSRF en een afzonderlijke revisie. Start slaat
duur (1–180 hele minuten), temperatuur (5–35 °C binnen ingestelde zonegrenzen)
en absolute eindtijd duurzaam op vóór aansturing. Een dubbel verzoek met dezelfde
revisie verlengt de timer niet. De pollingcyclus beoordeelt afloop en stop.

Stop/afloop herstelt het vaste doel bij actieve algemene regeling; anders stopt
HC de eigen badkamerbron. Algemeen uitschakelen annuleert ook de timer.
Handmatige bronwijziging annuleert de timer en draagt de bron over aan de gebruiker.
Herstart annuleert de timer zonder herhalen van Aan; de eerstvolgende beschikbare
uitlezing mag uitsluitend de eigen timerbron uitschakelen. Andere bronnen worden
hierdoor niet overgenomen. Een mislukte stop blijft zichtbaar vergrendeld tot
expliciete storingsvrijgave. HC kan zonder HA-verbinding niet fysiek uitschakelen.

Voorkeuren blijven na afloop en herstart bewaard. Dashboard toont resterende hele
minuten bij iedere verversing; bewerkingen overleven verversing. Timer opslaan
stuurt zelf geen apparaatopdracht. De vaste temperatuur boven blijft op de zonekaart.
