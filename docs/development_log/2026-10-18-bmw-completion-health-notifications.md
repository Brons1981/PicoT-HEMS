# BMW-laadeinde en eigen gezondheidsmeldingen

Gebruikersopdracht: voeg BMW-einddetectie en iPhone-meldingen voor fouten/terugval
van HEMS, HC en ED toe. Nog geen releaseopdracht voor deze wijziging.

ED verwerkt verse `chargingactive` → `chargingended` binnen de lopende sessie.
Pauzes, onderbrekingen en oude statuswaarden voltooien de sessie niet. Bestaande
geplande eindtijd blijft gelden. BMW-details blijven bij ED; generieke afsluitreden
is `vehicle_charging_ended`, zonder claim over 100% SOC.

Elke app meldt eigen incidenten via `picot_health_alert`. De gedeelde stdlib-helper
bewaart incidentstatus en uitgaande wachtrij en verstuurt op een achtergrondthread
met retry. HC krijgt een identieke lokale kopie vanwege de aparte Docker-context.
HEMS/ED Docker-packaging neemt de helper expliciet mee. Bestaande HEMS persistent
notifications en regelgedrag blijven behouden. Normale handmatige holds en
kalibratiewachttijden zijn geen fouten.

Blueprint: `blueprints/automation/picot_health_notifications.yaml`.
Instellen: `docs/picot-health-notifications.md`. Telefoonselectie gebeurt in HA;
geen live push, installatie of release uitgevoerd.

Verificatie:
- Gecombineerde notifier/BMW/ED-runtime/add-onpackagingselectie: 47 geslaagd.
- Laatste HEMS-filtertests: 12 geslaagd; eerdere HEMS-runtime-regressies: 33 geslaagd.
- HC: 5 nieuwe en 8 bestaande gerichte tests geslaagd; vendorkopie gelijk.
- ED/BMW/guard-selectie: 48 geslaagd; eerdere EV-regressieselectie: 69 geslaagd.
- Ruff en mypy voor gewijzigde Python-runtimebestanden geslaagd.
- Blueprint volgt officiële HA mobile_app device-action-structuur; niet in live HA
  geladen. Lokale YAML-parser niet beschikbaar. iPhone-aflevering niet getest.

Beperkingen: HA-eventacceptatie bewijst geen pushontvangst. Een volledig gestopte
app kan zelf geen nieuwe melding publiceren. HC aparte ongelatchte sensorverlies-
signalering is niet toegevoegd; bestaande commandofouten worden wel gemeld.
