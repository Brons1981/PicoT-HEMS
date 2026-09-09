# PicoT Energy Devices

Deze app verzamelt apparaatprofielen. PicoT blijft onafhankelijk plannen; deze
opnames activeren geen optimalisatie of apparaatsturing.

## Een programma inleren

1. Voeg het apparaat toe met een naam en vermogenssensor. Een cumulatieve
   energiemeter is optioneel.
2. Klik vlak vóór het starten van het apparaat op **Start inleren** en geef de
   opname een programmanaam, bijvoorbeeld *Vaatwasser Eco 50°*.
3. Laat de opname het hele programma lopen, inclusief rustige fases. Een daling
   onder 20 W beëindigt de opname niet.
4. Klik op **Programma klaar** zodra het programma werkelijk klaar is.
5. Kies **Bekijken** voor het vermogensverloop en de afzonderlijke metingen.
   Je kunt de naam wijzigen of een foutieve opname verwijderen.

Een lopende opname blijft na een herstart bewaard. Eventuele meetuitval tijdens
het herstarten wordt zichtbaar. Verwijder een lopende opname om deze te annuleren.
Stopknoppen bedienen alleen de opname, nooit het fysieke apparaat.

## Meetkwaliteit

Energie wordt geschat uit het gemeten vermogen en de tijd tussen metingen
(vorige vermogen aangehouden). Bij de start wordt de laatste beschikbare meting
gebruikt als deze nog vers is; dit staat in de meettabel. Zonder verse startmeting
begint de opname met een expliciet meetgat. Optionele energiemeterstanden blijven
bij iedere meting bewaard, maar worden niet als volledige sessie-energie voorgesteld.

Onbeschikbaarheid en te lange meetonderbrekingen tellen niet als nulverbruik en
worden niet met verzonnen energie opgevuld. Bij meetgaten toont de app de bekende
energie als onvolledig. Alleen afgeronde opnames zonder meetgaten en met minimaal
twee vermogenspunten tellen mee voor de samenvatting op de kaart. Een opname blijft
ook met meetgaten beschikbaar voor inspectie. Verschillende programma's blijven
als afzonderlijk benoemde opnames bewaard; de kaartsamenvatting is een algemene
apparaatsamenvatting, geen programmaspecifieke voorspelling.

## Oude sessies

Automatische sessiedetectie is voor deze inleerfase uitgeschakeld. Bestaande
automatisch opgesplitste sessies tellen niet mee in het handmatige leerprofiel.
Via **oude automatische sessies wissen** verwijder je die historie voor het
apparaat, na bevestiging. Handmatige opnames blijven daarbij bewaard.

Automatisch herkennen van programma's, leren van start-/stopdrempels en het
gebruiken van profielen in PicoT's planning zijn vervolgstappen.
