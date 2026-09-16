# HC-ADR-017 — Eerste automatische verwarmingsregeling

Alex vraagt op 16 september 2026 alle vier bronnen direct mee te nemen: gedeelde
cv, beide airco's en elektrische badkamerverwarming. Dit besluit breidt
HC-ADR-012/014/015 uit met opt-in uitvoering; het comfortschema blijft bronvrij.

## Contract

- Apart activeren; bij installatie en na herstart uit. Geen opdrachten vanuit
  constructor, GET of schema-opslag. Alleen de regelcyclus mag via Control sturen.
- Beneden volgt het actuele venster of de ingestelde basis, boven/badkamer hun
  vaste doel. Start bij doel minus 0,3 °C, stop bij doel. Dit is regelhysterese,
  geen economische temperatuurband. Nog geen voorverwarming, voorspelde deadline,
  koeling, automatische ontvochtiging, thermische buffer of automatisch bijleren.
- Kosten per kWh warmte: stroom/COP, gas/(bovenwaarde × rendement), elektrisch
  direct = stroom. Startschattingen: MHI 3,72 (nominaal testpunt, geen curve),
  Qlima 3,0 (aanname, niet SCOP 4), cv 0,90 op bovenwaarde 35,17/3,6 kWh/m³.
  Alle waarden zijn instelbaar. Alleen bevestigd huidig tarief en geldig gasprijs-
  tijdvak. Ontbrekende prijzen blokkeren nieuwe economische bronkeuze.
- CV is één ondeelbare bron met beneden als thermostaatreferentie. Alleen inzetten
  bij warmtevraag beneden én ruimte om boven te verwarmen (onder het doel), en
  niet duurder dan de airco voor iedere zone met warmtevraag. Geen fictieve
  verdeling van gaswarmte over zones. Bij alleen boven-vraag gebruikt HC de airco.
  Airco boven kan na uitschakelen van CV de resterende vraag overnemen.
- Eerst oude overlappende bron uit en bevestiging afwachten, dan nieuwe bron aan.
  Minimaal 300 s tussen economische bronwissels en 180 s uitrusttijd per bron.
  Comfortstop, meetfout, deur en handmatig gaan vóór de wisselvertraging.
- Handmatige keuzes blijven leidend; CV-hold blokkeert beide airco's. HC stopt
  uitsluitend eigen opdrachten, nooit een handmatig bediende bron. Een al lopende
  niet door HC beheerde bron wordt niet stilzwijgend overgenomen.
- Achterdeur: geen nieuwe airco-start bij open/onbekend; eigen airco stoppen na
  openvertraging, onmiddellijk bij onbekend, hervatten na sluitvertraging. Deze
  stop werkt ook bij ontbrekende temperatuur of nog wachtende verwarmopdracht.
- Brontijd temperatuur (last_reported, anders last_updated) moet binnen de
  ingestelde meetleeftijd vallen. Oude HA-standen zijn geen verse fysieke meting.
  Ongeldige of conflicterende comfortwaarden blokkeren vraag. Bij meetverlies
  eigen verwarming stoppen zodra het apparaat bereikbaar is.
- Nieuwe HA-uitlezing en herbeoordeling direct vóór verzending. Duurzame intentie
  vóór apparaatopdracht, geen herhaling bij fout/timeout/herstart. Storingen blijven
  staan tot expliciet vrijgeven; stop mag een onzekere aan-opdracht vervangen.

## Grenzen en bewijs

HC heeft geen onafhankelijke radiatorkleppen of gemeten warmteverdeling. De cv-
keuze is daarom conservatief; dit is geen optimalisatie van totale woningkosten.
Een setpointbevestiging blijft apart van gemeten warmte/vermogen. Elektrisch
hulpverbruik van CV en leidingverliezen zijn nog niet afzonderlijk gemodelleerd.
Handmatige badkamer Aan blijft een handmatige hold tot hervatten; automatisch
bedrijf gebruikt het vaste doel, geen nieuw badkamer-tijdvenster.

Scope: HC-regelaar, bestaande opdrachtgrens, runtime, dashboard en regressies.
HEMS blijft buiten scope. Tests gebruiken echte lokale HTTP-fakes en SQLite:
vier bronnen, gedeelde CV, feedback, handmatige race, deur, stale, prijzen,
herstart, fouten en opslag. Terugval dev.16 laat metingen en comfortdata intact;
schakel automatische regeling eerst uit en controleer apparaatstanden.

Bronnen: Remeha Tzerra Ace-Matic handleiding 7836957-05 (35c: 88,1% hoog,
98,9% laag, seizoenswaarde 94%); MHI SRK50ZS-W/SRC50ZS-W nominaal COP 3,72;
Qlima SC5225 productblad noemt SCOP 4,0, geen gevalideerde COP-curve.
