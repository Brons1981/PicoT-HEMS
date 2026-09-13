# HC-ADR-014 — Comfortvraag vóór bronkeuze

Status: geaccepteerde correctie van Alex op HC-ADR-013, verwerkt in dev.10.

## Besluit

- Alleen beneden heeft weekvensters met begin, einde, gewenste temperatuur,
  minimum, maximum en een harde-grenskeuze. Een harde gewenste waarde is een
  ondergrens die bij aanvang bereikt moet zijn en gedurende het venster geldt.
  Het maximum blijft een grens. Flexibel betekent minimum ≤ gewenst ≤ maximum:
  bijvoorbeeld nachtvoorkeur 17 °C, met 18 °C toegestaan als dit totaal goedkoper is.
- Het vensterstarttijdstip is een comfortdeadline, geen inschakeltijd. De planner
  moet later terugrekenen met opwarmtijd, buitenweer en woningverliezen.
- Het schema kent geen bron. De toekomstige planner vergelijkt totale kosten van
  bron/combinatie, prijzen, efficiëntie, warmteverlies en later opnieuw opwarmen.
  Handmatige bronkeuzes en comfortgrenzen gaan vóór kostenoptimalisatie.
- Boven en badkamer gebruiken een vaste gewenste temperatuur. De vochtband boven
  blijft van toepassing, evenals de bestaande minimum- en maximumtemperatuur.
  Vast betekent een constante voorkeur zonder tijdschema. Buiten vensters gebruikt beneden zijn algemene
  comfortvoorkeur en grenzen, als deze zijn ingesteld; er worden geen waarden verzonnen.
- Handmatig een brontemperatuur instellen, via HC of zichtbaar in HA, registreert
  een gedwongen bron met gewenste temperatuur, modus en bevestigingsstatus.
  Cv legt een beperking op aan beneden én boven. Een handmatige modus/off/preset
  is een te respecteren handmatige stand, geen impliciete verwarmopdracht.
- Voor cv en beneden verloopt de keuze bij de volgende grens van een actief
  comfortvenster of HC hervatten. Zonder actieve vensters, en voor boven/badkamer,
  blijft de keuze tot HC hervatten. Bewerken van vensters verlengt een bestaande
  handmatige keuze niet. Hervatten geeft keuzes vrij en verstuurt geen opdracht.
- Eigen vertraagde terugmeldingen verlengen of herschrijven een keuze niet.
  Gevraagde, bevestigde, mislukte en onzekere opdrachten blijven onderscheiden.
  Polling ziet geen niet-gerapporteerde tussenliggende handelingen; een presetwijziging
  tijdens een eigen opdracht kan zonder causale HA-informatie ambigu blijven.

## Implementatiegrens

Dev.10 implementeert de **comfortbasis**, niet de financiële planner. De eerdere
rechtstreekse schemasturing uit dev.9 vervalt. Opslaan, gebruiken, verlopen,
hervatten en herstarten van vensters versturen geen apparaatopdrachten. Handmatige
bronbediening blijft werken. Geen vaste COP, fictief woningmodel of onbewezen bronkeuze.

De snapshot bevat actuele comfortvraag per zone, bronbeperkingen, vensters voor
48 uur, toekomstige harde deadlines, kostenfactoren en expliciet
`planner_status: not_implemented`. Er worden geen bronnen geselecteerd.
De bestaande metingen, prijzen, weer en deurvoorwaarden blijven beschikbaar
voor de volgende plannerstap. De deurvoorwaarden sturen in deze versie niet zelf.

## Tijd en opslag

Weekdagen en kloktijden gelden in Europe/Amsterdam. Eindtijd vóór begintijd loopt
naar de volgende dag; 00:00–24:00 is een hele dag. Overlap wordt ook over middernacht
of de weekgrens geweigerd. Vensters zijn inclusief begin en exclusief einde.
Bij de najaarswisseling gebruiken aangrenzende grenzen dezelfde eerste kloktijd;
bij de voorjaarswisseling schuift een ontbrekende grens naar de eerstvolgende
bestaande minuut. Lege vensters na die omzetting worden overgeslagen.

Dev.9-instellingen worden atomair gearchiveerd en naar vensters omgezet, waarbij
temperaturen en het doorlopende weekpatroon bewaard blijven. Ze staan uit ter
controle. De bronkeuze wordt niet meegenomen als gedwongen bron. Apparaatstanden
worden bij de migratie niet veranderd en oude opdrachten worden niet herhaald.

## Verificatie

Regressies: harde deadline, flexibele nacht, weekend, grenzen/overlap/DST, vaste
zones, geen verzending vanuit comfortvensters, handmatige gedeelde cv, andere
zones, feedback, verlopen/hervatten, opslagfouten, migratie en CSRF/Ingress.
Browser: bronvrije editor, harde/flexibele velden, bewaren/herladen/conceptbehoud,
geen automatische verzending, gedwongen bron zichtbaar, vrijgeven en mobiel.
