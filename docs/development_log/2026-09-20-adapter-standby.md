# 20 september — standby-adapterherstel

Basis: dev.266, ed0f7346849ba6d8ee7db640b6abf7d1052ad417.
Status: lokaal aangepast en geverifieerd op branch fix/adapter-standby.
Alex heeft release aangevraagd. Dev.267 wordt via PR en CI gepubliceerd;
installatie en liveverificatie volgen afzonderlijk.

## Verandercontract

De diagnose van 11:41 bevat tien mislukte standby-grenzen. Vanaf 10:35 lokale
tijd wilde het plan standby terwijl de Zendure in NOM bleef. Eerste foutgrens:
HomeAssistantAdapter._service_value weigert STANDBY ondanks een gevalideerde
moduskoppeling. Eigenaar: Device Adapter. ADR-015 en V2ADR-050 beschrijven de
primitive; ADR-035 en het Canonical Pipeline Contract bepalen validatie en
herleidbaarheid. Dit is de afzonderlijke testgedekte adapteruitbreiding voor
de bestaande standby-koppeling, geen uitbreiding van live-autorisatie.

Scope: één extra primitive in SUPPORTED_MODE_PRIMITIVES en regressietests.
Planner, MEP, Evaluation, Plan Builder, commitment en runtime blijven gelijk.
Invariant: vertaal exact de aangeleverde opdracht, via de expliciete koppeling;
behoud identiteit, validatie en dry-run/live-poorten. Terugval: verwijder alleen
de nieuwe STANDBY-vermelding; geen opslagmigratie.

## Bewijs

- Nieuwe vertaaltest faalt vóór de fix in dry-run en live met exact de gemelde
  ValueError. Na de fix worden input_select.select_option en option=Standby
  geproduceerd met behouden opdracht-, plan-, segment- en mappingreferenties.
- Ongeldige koppelingen blijven geweigerd; live zonder transport blijft geblokkeerd.
- 63 gerichte tests slagen: adapter, HTTP/dry-run, canonieke uitvoering,
  handmatige override/herkomst, capability-koppelingen en architectuurbewaking.
- Ruff slaagt; mypy slaagt op 224 bestanden inclusief de aangepaste tests.
- Alle tien mislukte grenzen uit de aangeleverde diagnose zijn offline opnieuw
  vertaald met de opgeslagen plan-/segmentidentiteit en getoonde doelmodus.
  Resultaat 10/10 juiste Standby-opdrachten. Dit is een adaptergrensreproductie
  met een expliciet synthetische plan-setreferentie, geen volledige plannerreplay.
  Er is geen netwerktransport of echte HA-aansturing gebruikt.

Live werking vereist na afzonderlijke publicatie/installatie nieuw bewijs van
geslaagde dispatch en waargenomen Standby. De bestaande 10%-hardwaregrens was
geen bewijs van een geslaagde PicoT-standby-opdracht.

## Releasevoorbereiding dev.267

Versies en changelog bijgewerkt na releaseopdracht. Volledige lokale pytest-suite:
1.675 geslaagd, 1 overgeslagen (257 seconden). Versie-/adapterselectie: 30 geslaagd.
Push naar Brons1981/PicoT-HEMS is door automatische goedkeuringscontrole
geblokkeerd: expliciete toestemming voor publicatie naar deze repository gevraagd.
Remote branch bestaat nog niet; geen PR, CI of publicatie uitgevoerd.
