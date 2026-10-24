# HEMS dev.315 / Home Climate dev.23

Alex heeft op 24 oktober 2026 expliciet publicatie aangevraagd.
Publicatie via PR #725 en geslaagde CI; installatie volgt afzonderlijk.

## Releasegrens

Functionele basis: 30557c9fdffb8cbcad44471437ea6f11ac62281c.
De releasecommit wijzigt uitsluitend versies, de bestaande versieassertie,
wijzigingsnotities, handleiding en overdrachtsregistratie.
De nachtelijke dev.314-reparatie en het regelgedrag blijven behouden.
Energy Devices krijgt geen nieuwe versie.

## Bewijs

Op de functionele basis slaagden alle vier PR-workflows:
- HEMS 2.559 tests, 1 overgeslagen, run 40093089014.
- HC 438 tests en 30 subtests, Docker/container/browser, run 40093089003.
- v2 878 tests, 1 overgeslagen, typecontrole/lint, run 40093088990.
- Core CI, run 40093088984.
De releasecommit wordt opnieuw gecontroleerd voor samenvoegen.
PR #725 bevat de actuele uitslagen en publicatiestatus.

## Ingebruikname

1. Maak een HA-back-up inclusief HC. Werk eerst HEMS bij naar dev.315,
   daarna HC naar dev.23. Bestaande gegevens blijven bij een gewone update bewaard.
2. Controleer de Ecowitt-ruimtemeting, aircometer beneden, CV/thermostaat,
   beide tapwatersignalen, prijsbronnen en ingestelde gasprijs/geldigheid.
3. Stel comfortvensters en grenzen voor beneden in bij Comfortschema.
   Zonder actief schema geldt de handmatige thermostaat.
4. Controleer doelen, apparaatstanden en meldingen; schakel daarna zelf
   automatische regeling in. Na herstart staat deze uit.
5. Leerfuncties en automatisch uitvoeren van gekozen starts zijn afzonderlijke
   opties. Controleer de eerste echte HC/HEMS-uitwisseling en bronoverdracht.

CV-hulpstroom blijft expliciet geschat. Echte HA-uurweerondersteuning,
warmtelevering, comfort en financieel resultaat zijn nog niet live bewezen.
Teruggaan vereist passende oudere configuratie/data; bewaar de back-up.
Geen installatie, livebediening of wijzigingen aan HA uitgevoerd bij publicatie.
