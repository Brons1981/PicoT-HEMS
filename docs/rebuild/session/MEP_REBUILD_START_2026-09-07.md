# MEP-herbouw — start 2026-09-07

Status: STARTED — afbakening en eerste oorzaak onderzocht; geen nieuwe runtime geïmplementeerd.
Basis: ADR-001..037 (bevroren), ADR-037.1 en ADR-019.1.
Live referentie: 2.0.0-dev.243, door gebruiker bevestigd.
Onderzochte bron: main op 39e5fd50bba47367f3934ef7bc93fb9e302b2985.
Werkbranch: docs/session-2026-09-07-linked-adrs.

## Opdracht en grens

De bestaande pipeline blijft intact. Vervang tegenstrijdige planningsbesluiten door één samenhangende route. Geen nieuwe parallelle planner, pipeline, controller of diagnostische rekenroute. Geen reeks avondlijke gedragsfixes op dev.243.

| Onderdeel | Eerste behandeling |
| --- | --- |
| Invoer, capability mappings, adapters en uitvoeringsketen | Behouden; alleen gericht onderzoeken bij bewezen afwijking |
| Dashboard en diagnostiek | Bestaande records presenteren; geen eigen planning |
| Fysieke simulatie en tariefberekening | Toetsen op hergebruik; geen aanname dat bestaand gelijkstaat aan correct |
| Laadvensterconstructie en vroege kandidaatselectie | Herontwerpen volgens het laadcommitment |
| Commitmentopslag | Bestaande verantwoordelijkheid behouden; levenscyclus en periode-identiteit expliciteren |
| Handelsbesluit | Gebruikersopdracht met optionele hersteltoets; geen autonoom concurrerende herstelroute |

## Eerste vastgestelde oorzaak

Diagnose: picot-diagnostics - 2026-09-07T212500.492.zip.
Laatste volledige beslissnapshot: 2026-09-07 18:51:37 lokale tijd, dev.243, SOC 91%.
Run: run-51f77f69d6acd6b6.
Snapshot: snapshot-885fddfdefec2c87.
De exporttijd is geen bewijs van een nieuwe volledige beslissing om 21:25.

- IndependentDailyChargeWindowDiscoverer._hybrid_schedule geeft NOM voor alle intervallen vóór nom_end_index, vóór de test voor GRID_REQUIREMENT.
- De NOM-periode loopt vanaf horizonstart tot het laatste potentiële PV-overschot. Daardoor omvat zij ook de nacht.
- IndependentDailyReferenceAdapter verwijdert afzonderlijke grid-componenten zodra een hybride pad bestaat.
- De live kandidaatset bevat baseline, hybride avondladen, conservatieve PV-opvang en het bestaande commitment. Baseline en PV-opvang worden wegens het dagdoel afgewezen.
- Zowel het nieuwe hybride pad als het bewaarde commitment laden 8 september 20:30–24:00. Het commitment wordt als gelijkwaardig behouden; het is niet de oorsprong van de uitsluiting van middagladen.
- De gebruikersinstelling preserve_pv_during_grid_charge is false; de genoemde NOM-voorrang bestaat ook zonder die instelling.
- Gemiddelde ruwe getoonde importprijzen: 11:00–15:00 EUR 0,26075/kWh, 20:30–24:00 EUR 0,3780714/kWh. Dit is geen bewezen totale besparing of volledige alternatiefsimulatie.
- Solcast morgen in deze snapshot: lower 2,931 kWh, central 6,641 kWh, upper 10,575 kWh. Eventuele nieuwere voorspelling is hiermee niet aangetoond.

Bronbestanden:
- src/picot/planner/independent_daily_charge_window_discoverer.py
- src/picot/v2/independent_daily_reference_adapter.py

Conclusie: aantoonbare beperking vóór Evaluation. Het vervangen van alleen winnerselectie of commitmentbescherming lost deze oorzaak niet op.

## Gewenste beslisroute

1. Nieuwe prijsperiode herkennen, bestaand commitment en gerealiseerde voortgang meenemen.
2. Dagelijkse laadverplichting vastleggen zonder bestaande opdracht te wissen.
3. Haalbaar basislaadsegment vormen met PV en waar nodig netaanvulling.
4. Bestaande segmenten optimaliseren; een tekort aanvullen zonder vervangende hoofdopdracht.
5. Na laden de energiebalans bewaken; bij voldoende reserve geen volledige prijsherselectie.
6. Handelsopdrachten uit gebruikersregels één keer verwerken in het complete energiepad.
7. Geselecteerde versie via de bestaande Plan Builder en uitvoering afhandelen.

## Verificatiematrix

| Situatie | Vereist gedrag | Bewijs |
| --- | --- | --- |
| Weinig PV en goedkope middag | Netaanvulling tijdens PV blijft mogelijk | Echte snapshot, complete alternatieven en afwijsredenen |
| Nieuwe prijzen tijdens commitment | Huidige opdracht behouden | Twee opeenvolgende snapshots en planversies |
| 100% gevolgd door 99% | Doel blijft behaald | Waarneming plus blijvende periodestatus |
| 10% met PV die huis dekt | Geen extra sessie alleen vanwege 10% | SOC-verloop en behouden segment |
| Tegenval in PV | Tijdig gerichte netaanvulling | Prognosewijziging en resulterende segmenten |
| Extra huisvraag | Alleen noodzakelijke aanvulling optimaliseren | Werkelijke belasting en voorspelde reserve |
| Herstart | Commitment en voltooiing blijven behouden | Voor/na opgeslagen toestand |
| Handel, herstel uit | Ontbrekende herstelprijs is geen verborgen blokkade | Regel, SOC-toets en plan |
| Handel, herstel aan | 100% herstel en ingestelde nettowinst aantonen | Vergelijkbare complete paden |
| Live uitvoering | Opdracht en batterijgedrag stemmen overeen | Plan → primitive → adapter → bevestiging/telemetrie |

Offline replay is voorbereiding, geen LIVE_VERIFIED. Test opeenvolgende beslissingen, niet alleen één snapshot. Bij live afwijking eerst de eerste afwijkende grens aanwijzen; geen extra regel invoeren enkel om het voorbeeld passend te maken.

## Exacte volgende stap

Werk de open specificatiepunten uit ADR-037.1 en ADR-019.1 af voordat daarvan afhankelijke code wordt geschreven. Breng ondertussen de bestaande simulator-ingang, planner-uitgang en commitmentstore gericht in kaart. Kies daarna de kleinste complete laadcyclus als eerste implementatie, binnen dezelfde pipeline.

Niet geverifieerd: volledige economische vergelijking van middag versus avond, overeenstemming tussen gepubliceerde main en geïnstalleerde bronbytes, nieuwste prognose na 18:51, nieuwe functionaliteit in HA.
