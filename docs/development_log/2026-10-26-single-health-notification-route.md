# Een meldingsroute voor HEMS

Lokale vervolgstap op akkoord van Alex: dubbele terugval-/herstelmeldingen opruimen.
Geen release of livewijziging; bestaande aansturing en plannerselectie blijven buiten scope.

## Eigenaarschap

`health_alerts` bepaalt de betekenis van planning- en uitvoeringsuitkomsten.
`HealthNotifier` bewaart, dedupliceert en verzendt de gebeurtenissen asynchroon via
het bestaande `picot_health_alert`-event en de bestaande blueprint.

De oude `PlanningFallbackNotifier` en zijn rechtstreekse HA persistent-notification
transport zijn verwijderd. De live-compositie publiceert eerst het plan en de SOC;
daarna ontvangt de ene healthroute de uitkomst. Een observerfout kan de publicatie
niet terugdraaien. De aparte uitvoeringsobservatie op plangrenzen blijft hetzelfde
healthkanaal gebruiken en dedupliceert op dezelfde incidentidentiteit.

## Garanties

- Identieke oorzaak wordt niet opnieuw verzonden bij iedere poll of herstart.
- Een gewijzigde planningsreden tijdens een actief incident wordt wel opnieuw gemeld.
  Hiervoor ondersteunt HealthNotifier een optionele persistente fingerprint. Die
  bevat de reden, niet de klok of vervaldatum van het uitvoeringsbewijs.
- De standaard zonder fingerprint behoudt het bestaande HC/ED-gedrag.
- Terugval, tijdelijk behouden uitvoering en volledige planningshervatting blijven
  onderscheiden. Tijdelijk behoud meldt niet dat het toekomstige plan opgelost is.
- Van onopgeloste planning terug naar fallback wist de onopgeloste melding niet.
  Een geldig plan kan beide planningsincidenten afsluiten; dit bewijst op zichzelf
  geen geslaagde batterijopdracht. Uitvoeringsherstel blijft afzonderlijk bevestigd.
- Wachten op de eerste geldige planning na opstart is geen uitvoeringsfout en ook
  geen herstelbewijs. Verlopen tijdelijk uitvoeringsbewijs vraagt eveneens om
  herbeoordeling, zonder een extra actuatorstoring/herstel te verzenden. De exacte
  blocker blijft in diagnose/dashboard en planning_fallback blijft echte planningsfouten melden.
- Mislukte verzending blijft in de bestaande persistente wachtrij; storing en herstel
  blijven op volgorde. De regelcyclus wacht niet op de netwerkverbinding.

De notificatieopslag krijgt alleen het optionele veld `fingerprints`; oudere bestanden
zonder dat veld blijven leesbaar. Bij een al actief incident zonder fingerprint kan
de eerste nieuwe concrete oorzaak eenmaal opnieuw worden gemeld.
Bestaande oude HA persistent notifications worden niet automatisch verwijderd.
Er is geen nieuwe configuratie of blueprint nodig voor het bestaande healthkanaal.

## Verificatie

Een nieuwe regressietest voor oorzaakwijziging en herstart faalde eerst op de ontbrekende
fingerprint-parameter. Na implementatie slagen de bestaande en nieuwe healthtests.
Een persistente incidentreeks controleert fallback -> tijdelijk behoud -> herstart ->
opnieuw fallback -> geldig plan, inclusief ongewijzigde oorzaak bij later geldig-tot.
De publicatievolgordetest controleert dezelfde plan/SOC-versie voor health en financieel
observer, ook wanneer een van beide faalt. De live-compositie gebruikt de nieuwe
functiehandtekening zonder tweede notifier.
Ruff en mypy voor beide betrokken notificatiemodules zijn groen.
Gecombineerde notificatie-/publicatie-/live-compositieregressies: 40 geslaagd in 4,13 s.
Uitgevoerd: test_health_notifications.py, test_hems_health_alerts.py,
test_v2_planning_fallback.py, test_live_plan_publication_order.py en
test_v2_live_pv_actual_coupling.py. Extern HA-verkeer is daarbij vervangen door
transportgrens-testdoubles; er zijn geen meldingen naar de installatie verstuurd.
