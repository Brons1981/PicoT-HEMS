# PicoT-meldingen op je telefoon

HEMS, HC en ED melden hun eigen fouten en herstel via het Home Assistant-event
`picot_health_alert`. HEMS leest hiervoor geen apparaatentiteiten. Een centrale
HA-automatisering bepaalt welke telefoon de melding krijgt.

## Eenmalig instellen

1. Plaats `blueprints/automation/picot_health_notifications.yaml` uit deze repository
   in HA onder `config/blueprints/automation/picot/picot_health_notifications.yaml`.
2. Open Instellingen → Automatiseringen en scènes → Blueprints en maak een
   automatisering met **PicoT - fouten, terugval en herstel**.
3. Kies je iPhone, de gewenste apps en of je herstelmeldingen wilt. Sla op.
4. Geef de Home Assistant Companion-app op de iPhone toestemming voor meldingen.

De add-onopties `health_notifications_enabled` en
`health_notifications_recovery_enabled` staan standaard aan. Zonder bovenstaande
automatisering worden alleen HA-events verstuurd, geen pushberichten.

## Gedrag

Een incident wordt eenmaal gemeld en na aantoonbaar herstel volgt een herstelmelding.
Dezelfde incidentcode gebruikt dezelfde notificatietag. Open incidenten en nog niet
door HA geaccepteerde events blijven bewaard bij een herstart. HA-verzendfouten
worden op een achtergrondthread opnieuw geprobeerd; ze stoppen de regeling niet.
Een HA-acceptatie bevestigt het event, niet ontvangst op de telefoon. Als HA of een
add-on volledig uitstaat, kan die app zelf geen nieuwe storing melden.

HEMS meldt planningsterugval, uitvoeringsfouten, toegepaste veiligheidsbeperking en
cyclusfouten. HC meldt HA-verbindingsproblemen, verwarmingsfouten en mislukte of
onbevestigde opdrachten. ED meldt problemen in zijn eigen EV/P1-regeling.
Normale geplande moduswisselingen zijn geen incident.

## BMW-einde van laden

ED gebruikt `ev_vehicle_state_entity`, standaard
`sensor.wba5x71010fj59919_charging_ev_charging_state`. Een lege instelling schakelt
dit uit. Alleen een verse eindmelding die bij de lopende sessie hoort sluit de
sessie af als door het voertuig beëindigd. Pauze/onderbreking betekent niet voltooid;
beëindigd betekent niet automatisch 100% SOC. De geplande eindtijd blijft gelden.
