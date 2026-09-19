# Eenmalige proef

## Wat deze app doet

1. Vier seconden een vaste controletik meten zonder opname.
2. Dezelfde meting met vier synthetische records van ongeveer 256 KiB, één per seconde.
3. De records ontdekken en één batch verwerken; vervolgens stoppen.

De proef gebruikt eigen kindprocessen met geheugen-/CPU-limieten. Per fase geldt
vijftien seconden timeout. Normaal duurt het programma ongeveer acht tot tien
seconden na het opstarten. De beschikbare schijfruimte moet vooraf minimaal
512 MiB zijn. Alleen zijn eigen tijdelijke proefdirectory wordt opgeruimd.

## Starten nadat de afzonderlijke app beschikbaar is gemaakt

Installeer uitsluitend **PicoT History Probe**. PicoT HEMS dev.263 hoeft niet te
worden bijgewerkt of herstart. De eerste image-download/bouw is extra belasting
op de NUC en valt buiten de gemeten proef; plan die op een rustig moment.

- Laat beveiligingsmodus aan. Er zijn geen instellingen of toegangsrechten nodig.
- Start de app één keer handmatig.
- Bekijk na afloop het logboek. De status wordt weer gestopt.
- Kopieer het volledige JSON-rapport, inclusief de drie `phases` en
  `workload_complete`, voor beoordeling. Verwijder de app pas nadat het rapport is
  overgenomen. Het rapport wordt niet apart in een gedeelde map opgeslagen.
- Bij een fout of proceslimiet: stuur het log, zonder opnieuw proberen of limieten
  verhogen. Bij merkbare hinder voor de woningautomatisering: stop de proef.

`boot: manual_only` verhindert automatisch starten bij opstarten van Home Assistant;
`startup: once` markeert de app als eenmalige taak. Er is geen eigen scheduler,
watchdog of herhaallus. De concrete Supervisor-uitvoering moet nog worden getoetst.

## Resultaat beoordelen

`workload_complete: true` vereist vier publicaties, vier verwerkte jobs, geen
pending werk en SQLite-integriteit `ok`. Bekijk daarnaast CPU-tijd, piek-RSS,
maximale aanbiedduur en p95/maximale controletikvertraging vóór en tijdens opname.
Er is geen automatische prestatiegrens of plannergoedkeuring.

Dit is een korte proef met kleine synthetische records, geen bewijs voor grote
plansnapshots, langdurig gebruik, gelijktijdige workers of storingsvrij plannen.
De NUC deelt CPU, RAM en schijf tussen apps; afzonderlijke containers maken die
resources niet onafhankelijk. De proef wijzigt geen MEP-regels of PicoT-bestanden.

## Herkomst en reproduceerbaarheid

Het buildcontext bevat een expliciete kopie van het beoordeelde proefprogramma en
zes passieve bron-/schemabestanden, zonder live-runtime of planner. De hashes staan
in `source-manifest.json`. De zelfstandige pakkettest verifieert deze hashes. Bij samenstellen zijn de
bestanden bovendien byte voor byte met de canonieke lokale bronnen vergeleken. Bij een volgende wijziging moeten het
pakket en manifest samen opnieuw worden bijgewerkt en beoordeeld.

De Dockerfile kopieert uitsluitend deze bestanden. De basisimage heeft een
expliciete Python/Alpine-versietag; deze is niet op een immutable image-digest
vastgezet. Een image-download is alleen nodig bij bouw/installatie, niet door de
proefcode tijdens uitvoering.

Configuratiebasis:
[Home Assistant-appconfiguratie](https://developers.home-assistant.io/docs/apps/configuration/).
