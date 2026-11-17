# ED: eenvoudige laadopdrachten en geschat SOC-doel

Lokale implementatie op ED dev.15 / HEMS dev.339. Geen release of live wijziging.
Werkmap: ed-simple-charging. De marktroute-update in market-policy-work is niet gewijzigd.

## Gebruikersopdracht

- Starten op een tijdstip zonder aansluitcontrole of voorafgaande vermogensherkenning.
- Een blijvende opdracht voor automatisch laden, zonder wachten op een adviesknop.
- Bij aansluiten automatisch het passende laadmoment aanvragen; gereed voor de
  eerstvolgende 07:00 Europe/Amsterdam (instelbaar).
- Aansluitstatus: binary_sensor.330e_laadkabel.
- Doelpercentage instelbaar; UI stelt 80% en 11,7 kWh voor 0–100% aan de stekker voor.
- SOC-sensor: sensor.wba5x71010fj59919_state_of_charge_predicted_on_integration_side.

## Gedrag en grenzen

ED bewaart de gebruikersautorisatie. HEMS blijft laadvensters en batterijwijzigingen
beoordelen. Een gezamenlijke route begint alleen na de bestaande passende HEMS-receipt.
Er is geen nieuwe prijsplanner of batterijaansturing in ED. De rekentijd van de HEMS-
zoekfunctie is niet gewijzigd; de gebruiker hoeft het resultaat niet af te wachten.
De adviesuitwisseling controleert elke twee seconden en wordt bij een opdracht gewekt.
Automatische acceptatie wordt direct gepubliceerd. Verlopen selectie / veranderd
batterij-eigenaarschap krijgt een nieuwe aanvraagrevisie. Andere blokkades blijven
zichtbaar. Een wachtende bevestiging kan ook met één nieuwe opdracht worden vervangen.

Een aansluitgebeurtenis wordt duurzaam onthouden, ook bij annuleren en herstart.
Onbeschikbaar is geen loskoppeling. Loskoppelen annuleert alleen de door aansluiten
gestarte aanvraag/sessie. Een vaste starttijd gebruikt de aansluitstatus niet.
Automatisch aansluiten blijft standaard uit tot de gebruiker het inschakelt.
Een verlopen deadline wordt niet stilzwijgend naar morgen doorgeschoven.

De SOC-berekening is (doel - huidige SOC) / 100 * 11,7 kWh. Dit is netenergie;
geen tweede verliesfactor. De parameter is configureerbaar en er is geen onbewezen
zelflerende kalibratie toegevoegd. SOC-gebruik wordt eenmalig ingeschakeld met
Laaddoel opslaan. Zonder dat doel blijft het bestaande laadprofiel geldig.
Een ontbrekend/ongeldig of meer dan 30 minuten oud SOC-rapport blokkeert een nieuwe
SOC-doelopdracht. Gebruik last_reported (terugval last_updated) als rapporttijd.
Een al actieve sessie behoudt haar geschatte eindtijd bij meetuitval. Een bruikbare
SOC boven het vastgelegde sessiedoel stopt de sessie eerder. De bron is een voorspelling,
dus dit is geen garantie op exact 80% werkelijk SOC. Wijzigingen gelden voor nieuwe
opdrachten; het sessiedoel wordt vastgelegd.

## Validatie

Nieuwe regressies faalden eerst voor ontbrekende start_at, aansluitbeleid en blijvende
automatische uitvoering. Daarna gerichte regressies, bestaande ED/EV-tests, Ruff en
gerichte strikte Mypy. Zie verificatieresultaat in de overdracht. Windows blokkeert
lokale HTTP-client-sockets (WinError 10013); de echte HTTP-handler is aanvullend met
een geheugentransport getest. Geen test met de fysieke auto/HA uitgevoerd.

## Integratie

Alleen de gewijzigde ED-bestanden, add-on-configuratie en gerichte tests integreren.
HEMS-bronbestanden uit deze werkmap zijn uitsluitend testbasis, geen vervanging van
het werk uit de andere chat. Geen versie verhogen of publiceren vóór releasecontrole.

## Aanvulling: eenmalig 100%

Knop Eenmalig naar 100% maakt een automatische opdracht met een eigen SOC-doel.
De normale instelling blijft behouden (voorgesteld 80%). HEMS kiest de starttijd
voor de eerstvolgende opgeslagen eindtijd, standaard 07:00 Europe/Amsterdam.
Een open aanvraag kan worden vervangen; een bevestigde/lopende sessie moet eerst
worden geannuleerd. De opdracht overleeft herstart en gebruikt actuele SOC.
Het sessiedoel blijft 100% bij uitvoering, daarna geldt weer het normale doel.

11,7 kWh is een voorlopige AC-rekenbasis uit vergelijking van BavarianData en
Shelly op 1, 8, 11 en 16 november (omgerekend circa 11,5-11,9 kWh voor 0-100%).
Batterijenergie en AC-energie worden niet gelijkgesteld. Geen extra verliesfactor.
Kortere sessies volgen uit bijladen naar 80%; deze wijziging voegt geen opsplitsing
van een laadopdracht in meerdere blokken toe aan de HEMS-planner.

## Release ED dev.16

Alex heeft publicatie goedgekeurd. Bestaande ED-basisbestanden zijn exact tegen
main 68503d888892a132febd1faa936809700e10466a gecontroleerd met Git-blobhashes.
HC dev.35 blijft behouden; uitsluitend de geselecteerde ED-bestanden worden
gepubliceerd. Geen live installatie of automatische inschakeling.
