# Eenmalige proef

## Wat deze app doet

1. Ongeveer acht seconden een vaste controletik meten zonder opname.
2. Dezelfde meting met vier vooraf opgebouwde synthetische records van ongeveer
   1, 2, 4 en 8 MiB, één per twee seconden.
3. Een apart kindproces ontdekt en verwerkt ondertussen eerder opgeslagen records
   in maximaal vier rondes; iedere ronde maximaal vier jobs. Daarna stoppen.

De proef gebruikt eigen kindprocessen met geheugen-/CPU-limieten. Baseline en gelijktijdige fase hebben ieder 25 seconden timeout. De indexworker
heeft een aanvullende begrensde wachttijd; bij een fase-timeout wordt de eigen
procesgroep beëindigd. Normaal duurt het programma ongeveer twintig seconden
na het opstarten. De beschikbare schijfruimte moet vooraf minimaal
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
pending werk en SQLite-integriteit `ok`. `overlap_observed` moet bovendien waar
zijn om deze specifieke gelijktijdigheidsproef als uitgevoerd te beschouwen.
Ontbrekende overlap levert geen automatische herhaling op. Bekijk daarnaast CPU-tijd, piek-RSS,
maximale aanbiedduur en p95/maximale controletikvertraging vóór en tijdens opname.
Er is geen automatische prestatiegrens of plannergoedkeuring.

Dit is een korte proef met synthetische records tot ongeveer 8 MiB, geen bewijs
voor alle echte plansnapshotstructuren, grotere records, langdurige inventarisgroei
of storingsvrij plannen. De objectstructuur en compressie verschillen van echte
plannen; er worden geen inhoudelijke plannerberekeningen uitgevoerd.
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


## Aanvullende begrenzing in 0.2.0

Per meet-/indexproces blijft maximaal 128 MiB virtuele adresruimte gelden.
Opname en baseline krijgen ieder vijf CPU-seconden; de gehele indexfase twee.
Er is dus geen verdubbeling van de toegestane index-CPU per ronde. Het bewijsbudget
voor deze afzonderlijke grotere proef is 64 MiB en het SQLite-budget 8 MiB.
Er is geen wijziging van productie-instellingen of automatische budgetverhoging.

Indexwerk begint gepland 75 ms na een nieuw aanbod. Die verschuiving houdt rekening
met het 50-ms-pollen van de bestaande recorder. De meetrunner registreert begin/einde
van werkelijke `publish`-aanroepen en indexrondes op dezelfde monotone klok. Alleen
hun daadwerkelijke tijdsdoorsnede telt als overlap; geplande gelijktijdigheid alleen
is onvoldoende. Indexperioden bevatten ontdekking, lezen, parsen en schrijven;
het is geen meting van gelijktijdig gebruikte CPU-kernen. De timinginstrumentatie
bestaat alleen in de proefrunner en verandert de meegeleverde historiecode niet.

Het oude 0.1.0-programma blijft meegeleverd voor regressiecontrole. De standaard
startopdracht van de app voert uitsluitend de nieuwe grotere proef uit.
