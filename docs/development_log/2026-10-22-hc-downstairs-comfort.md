# HC beneden: centrale comfortinstellingen en handhaven

Status: lokaal geimplementeerd, gedeeltelijk geverifieerd; geen release, push,
commit, installatie of wijziging aan Home Assistant uitgevoerd.

## Afgesproken scope

- Beneden gebruikt bij een actief schema de venstertemperaturen en een centraal
  minimum buiten die vensters.
- Zonder actief schema geldt een handmatig thermostaatdoel zonder tijdschakelingen.
- Na bereiken van het doel blijft de door HC gekozen benedenbron in heat; de bron
  regelt zelf. Een lager doel wordt als setpoint verzonden, niet als off/on-cyclus.
- De temperatuur, ontbrekende temperatuurmeting of doeltemperatuur boven mag CV
  voor beneden niet blokkeren. Meeverwarming boven wordt door Alex geaccepteerd.
- Handmatige bronkeuzes, storingen, meetkwaliteit, uitschakelen van de regeling,
  bestaande herstartvertraging en deurbeveiliging blijven van toepassing.

De leermotor, voorspellend opwarmen/afbouwen en de uitwisseling met HEMS/MEP zijn
niet onderdeel van deze eerste implementatiestap. Er is geen HEMS/MEP-code gewijzigd.

## Werkbasis

Werkmap: `hc-comfort-work`, afzonderlijke gedeeltelijke repositorykopie met origin
`https://github.com/Brons1981/PicoT-HEMS.git`. De oorspronkelijke werkmap
`ev-deadline-advice` is niet gewijzigd. De oorspronkelijke bestanden zijn lokaal
in de git-index gezet om een diff te kunnen beoordelen; er is geen baselinecommit.
Voor publicatie moet de diff op een actuele volledige checkout worden toegepast.

De volgende oorspronkelijke bestanden zijn op 22 oktober tegen GitHub geverifieerd:

- heating.py: b9c6dcce42572561401070fa1b52940189f33742
- schedule.py: 3d2ca921430c0f0804a678ecec2f0476a7457dfb
- __main__.py: b3a91dfa1ab8e9088da980898acf7c31cff88a67

De webbestanden zijn via de GitHub-connector opgehaald. HC-versie blijft dev.22;
er is nog geen nieuwe versie toegekend.

## Wijzigingen en migratie

Schedule-opslag gaat naar format 4. `setback_temperature` en
`thermostat_temperature` worden eenmalig gevuld vanuit het bestaande beneden-doel.
Een ontbrekend doel blijft leeg; een actief schema zonder bruikbaar minimum wordt
uitgeschakeld. Bestaande format-3-inhoud wordt bewaard in `hc_schedule_archive`.
Oudere migraties blijven beschikbaar. Herstart verandert de nieuwe doelen niet.
Rollback naar oude code vraagt beoordeling/herstel van het opgeslagen schemaformaat.

De oude zonevelden voor beneden zijn na migratie geen regelinvoer meer. Het oude
`/api/settings`-schrijfpad weigert beneden; het dashboard gebruikt `/api/schedule`
met revisiecontrole. Andere zones behouden hun instellingen en regelgedrag.
Bij uitschakelen van het schema vervallen oude automatische eindtijden van
handmatige beneden-/CV-overrides; expliciet hervatten blijft beschikbaar.

CV-keuze vergelijkt nu beneden-airco en CV. Boven kan nog handmatige
bronbeperkingen opleggen om conflicterende opdrachten te voorkomen; dit is geen
temperatuurvoorwaarde. De bestaande deurbeveiliging is specifiek voor de airco.
CV kan dus beschikbaar blijven wanneer de airco door de deurvoorwaarde geblokkeerd
is. Dit is bestaand bronbeleid, nu niet meer indirect begrensd door de temperatuur boven.

## Verse verificatie

- 51 controles geslaagd: 12 nieuwe benedencontroles, 4 meetarchiefcontroles,
  4 bestaande kerncontroles, 2 schema/tijdzonecontroles en 29 bestaande
  verwarmingscontroles met een nagebootste HA-transportlaag.
- Echte SQLite, Runtime, Schedule, Heating en Control gebruikt. Nieuwe API-test
  voert de echte HTTP-handler uit met byte streams, inclusief CSRF en afwijzing
  van het oude beneden-instellingenpad; geen netwerktransport.
- Twee nieuwe regressietests uitgevoerd tegen de ongewijzigde code: beide falen
  op de bedoelde afwijking (uitschakelen bij doel, CV afhankelijk van boven).
- `node --check picot_hc/picot_hc/web/app.js`: geslaagd.
- Python AST-controle gewijzigde productiemodules: geslaagd.
- `git -c core.autocrlf=false diff --check`: geslaagd.

Omgevingsbeperkingen: echte localhost-HTTP-tests falen al op de oorspronkelijke
code door sockettoegang WinError 10013. Een onafhankelijke HA-config-request
bevestigt die oorzaak. De aanwezige Python mist standaard tijdzonegegevens;
tests gebruiken PYTHONTZPATH naar de bestaande tzdata-kopie in
`night-audit-1021/test-deps/tzdata/zoneinfo`. Geen tijdzonecode aangepast.
Browsercontrole kon niet worden voltooid: Playwright-browser ontbreekt en de
aanwezige Edge sluit onder de beperkte uitvoeringsomgeving af.

## Nog voor release

1. Volledige HC-suite met echte HTTP-testservers draaien in een geschikte omgeving.
2. Dashboardbediening daadwerkelijk controleren in browser/HA.
3. Diff op actuele volledige repository beoordelen, projectcontroles uitvoeren,
   daarna uitsluitend na release-opdracht publiceren.

Actuele prijsvergelijking, vaste rendementsaannames en blokkering bij ontbrekende
prijsgegevens zijn niet vernieuwd. De geplande woning-/energieoptimalisatie volgt
afzonderlijk; deze eerste stap is daarvan nog geen uitvoering.
