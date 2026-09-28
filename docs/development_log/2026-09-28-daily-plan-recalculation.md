# 28 september 2026 — expliciet opnieuw berekenen

Alex vraagt om reparatie om 23:48 Europe/Amsterdam, na overleg over de
achtergebleven resetknop. Lokale implementatie vanaf dev.279; geen opdracht tot
publicatie of livebediening.

## Wijzigingscontract

De bestaande knop heet voortaan **Planning opnieuw berekenen**. Een expliciet
verzoek wordt duurzaam in dezelfde Plan Store geregistreerd en via verse input
en de bestaande Runtime Monitor aan MEP aangeboden. De knop wist geen dagdoelen,
uitvoeringsplannen, werkelijk voltooiingsbewijs of historie.

MEP herberekent resterende open hoofdlaadroutes onder dezelfde dagidentiteit,
achtereenvolgens per dag. De reguliere Candidate/Evaluation/Builder/Store-keten
blijft eigenaar. Het verzoek geeft toestemming de oude indeling van vrije
intervallen opnieuw op te bouwen; de oude indeling is niet langer de verplichte
incumbent voor die expliciete herberekening. Andere dagdoelen, marktverplichtingen,
lopende laadbescherming, reserves, bekende prijzen en fysieke grenzen blijven
gelden. Een ongeldige of onhaalbare kandidaat wordt nooit gepubliceerd.

De bestaande uitvoering blijft opgeslagen tot een vervanger geldig is opgebouwd.
Het resultaat (opnieuw berekend, geen open dagroute of niet uitvoerbaar) wordt
zichtbaar. Het verzoek wordt na afhandeling niet elke poll herhaald; herstart,
dubbele verzoeken en mislukte opslag moeten herleidbaar en veilig blijven.

## Bewijs

De diagnose van dev.279 bevestigt behouden van het oude plan en twee resets die
nul legacy-commitments verwijderen. De lokale resetreplay laat bytegelijk
opslagbehoud en nul kandidaten zien. De regressie moet beginnen met een reeds
opgeslagen dagplan, via het verzoek echte kandidaten opleveren en een nieuwe
uitvoeringsversie vastleggen zonder doelidentiteiten of voltooiing te verliezen.
Ook verzoek zonder open dagroute, ontbreken van input, onhaalbare berekening,
opslagfout, herstart en normale polls zonder verzoek worden gecontroleerd.
De gedetailleerde huishoudelijke diagnose blijft buiten de repository.

## Implementatie en laagverdeling

- Dashboard hergebruikt het bestaande endpoint en toont aangevraagd, afgehandeld,
  geen open route of mislukt. Het kiest geen plan en geeft geen apparaatopdracht.
- Runtime registreert het verzoek na een lopende cyclus, met de bestaande
  synchronisatie. Het uitvoeringsgeheugen wordt niet gewist. De actuele status
  wordt na de berekening en bij volgende waarnemingen gepubliceerd.
- Planning Input herstelt het opgeslagen verzoek. Runtime Monitor ziet een
  expliciete commitmentwijziging; ook na een herstart blijft het verzoek zichtbaar.
- MEP gebruikt een afzonderlijke reden `explicit_user_recalculation`, gekoppeld
  aan de echte opdracht, actuele planversie en verse snapshot. Er wordt geen
  SOC-tekort verzonnen. De gewone Candidate-generatie berekent complete alternatieven
  met vrijgegeven oude vrije intervallen. Evaluation kiest de beste geldige
  vervanger; het oude intervalpatroon is bij deze expliciete opdracht geen
  verplichte incumbent. Normale waarnemingen behouden hun bestaande gedrag.
  Wanneer beide dagen al aantoonbaar tekortkomen, geldt dezelfde bestaande
  volgorde als bij automatisch SOC-herstel: de latere ongewijzigde tekortroute
  krijgt een eigen herberekening en blokkeert het herstel van vandaag niet.
  Gezonde doelen van andere dagen en alle eerdere doelen blijven harde grenzen.
- Plan Store controleert de nog open aanvraag en publiceert doelversie, uitvoering
  en afgehandeld verzoek in dezelfde atomaire opslag. Dubbele klikken worden
  samengenomen. Eerdere verzoekresultaten blijven bewaard.
- Bij mislukking blijft de bestaande uitvoering opgeslagen. Voortzetten vereist
  het bestaande actuele fysieke bewijs. Ontbrekende gegevens en werkelijk
  onuitvoerbare routes behouden de normale bewaakte afhandeling. Een niet
  gepubliceerde vergelijkingswinnaar krijgt niet het SOC-pad of kandidaatreferentie
  van het behouden plan op het dashboard.

De eerdere `clear_all()`-semantiek voor legacy-data is niet verruimd. Geen nieuwe
planner, handelsbudgetten, automatische reset na upgrade of vrijgave van behaalde
100%-doelen. Dit is een reparatie van expliciete gebruikersherberekening.

## Uitgevoerde diagnose-replay

De reeds opgeslagen probleemroute uit de dev.279-diagnose is gestart via dezelfde
aanvraagfunctie als de knop, op een afzonderlijke lokale Store-kopie. De replay
levert 83 kandidaten en een nieuwe uitvoeringsversie. De ongewenste nacht-NOM en
stand-by verdwijnen; de nacht begint met slim ontladen. De bestaande marktopdracht,
werkelijke marktvoortgang en het behaalde dagdoel blijven behouden. Het open
dagdoel bereikt in de projectie 100%.

Na herstart blijven dezelfde route en bytegelijke opslag behouden, zonder nieuwe
kandidaten. Het volledige diagnoserecord en dashboard blijven onder hun bestaande
groottegrenzen. Bronbestanden zijn hashgelijk gebleven; er zijn geen live
apparaatopdrachten of netwerkacties uitgevoerd.

## Gerichte regressies

De nieuwe regressies gebruiken de echte API-callback, Store, Candidate, Evaluation
en Builder. Ze toetsen publicatie, herstart, dubbele klikken, oude snapshots,
normale vervolgmetingen, ontbrekende prijzen, onhaalbare laadkracht, Builder-fout,
atomaire opslagfout, ontbreken van actuele uitvoering, voltooiingsbehoud,
marktbehoud, twee opeenvolgende native dagplannen en beschermd lopend netladen.
De meerdaagse proef omvat ook gelijktijdige tekorten bij beide dagdoelen.
De oude reset die nul legacy-commitments vond kan deze tests niet laten slagen.

## Verificatie afgerond

- Volledige bestaande suite inclusief de eerste elf nieuwe regressiegevallen:
  **1.880 geslaagd, 1 overgeslagen**, 688,83 seconden.
- Na de afsluitende weergavecontrole en uitbreiding met het dubbele SOC-tekort:
  **117 gerichte tests geslaagd**, waaronder alle twaalf nieuwe gevallen.
- Ruff op alle broncode, v2-tests en de nieuwe tests: geslaagd.
- Mypy op alle 235 bronbestanden: geslaagd. `git diff --check`: geslaagd.
- Afzonderlijke bronreview van aanvraag, Monitor-toelating, daggrenzen,
  atomaire publicatie en dashboardprojectie uitgevoerd. Supplemental-doelen
  blijven via de bestaande Candidate- en Store-controles verplicht.

De lokale reparatie is zonder versieverhoging, commit, push, release of
livebediening afgerond. De afzonderlijke releaseopdracht volgt hieronder.

## Releaseopdracht — 29 september 2026

Alex vraagt om 00:23 Europe/Amsterdam: **"maak reease"**. Dit autoriseert publicatie
van deze afgeronde reparatie als **2.0.0-dev.280**, via commit, PR en groene CI.
De actuele hoofdbranch is dev.279 (`a339e001f911b1ff5698ab2903b65baf7d042058`).
Alleen de reparatie, regressies, versieaanduidingen en bijbehorende documentatie
horen bij deze release. Ruwe diagnoses en lokale replaybestanden worden niet
gepubliceerd. Installatie en livecontrole volgen afzonderlijk; de nieuwe knop
blijft een expliciete gebruikersactie en wordt niet automatisch bij upgrade bediend.
