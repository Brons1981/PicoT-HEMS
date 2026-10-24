# Instelbare schatting elektrisch CV-hulpverbruik

Alex bevestigt dat er geen aparte elektriciteitsmeter voor de CV-ketel is en heeft expliciet ingestemd met een instelbare schatting, inclusief pomp-naloop. Deze wijziging bouwt voort op de gecombineerde HEMS dev.314-basis.

## Instellingen

De addondefaults en voorbeeldconfiguratie bevatten:

- `cv_auxiliary_mode`: estimated; measured blijft beschikbaar.
- `cv_auxiliary_running_w`: 100 W gemiddeld aangenomen elektrisch vermogen tijdens verwarmen.
- `cv_auxiliary_postrun_w`: 50 W tijdens naloop.
- `cv_auxiliary_postrun_seconds`: 300 seconden naloop.

Dit zijn voorlopige softwareaannames, geen opgezochte of bevestigde ketelspecificaties. Ze zijn via de addonopties instelbaar. De vermogens omvatten samen de bedoelde ketel-/pomplast; er wordt geen extra onbekende pomplast bovenop gezet. Bestaande configuraties zonder expliciete estimated-modus blijven op de oude meetroute. Een ingestelde aparte vermogens- of energiemeter wordt niet bij een fout automatisch vervangen door een schatting. Eenheden zijn W en seconden; ongeldige/niet-eindige waarden maken de schatting onbeschikbaar.

## Berekening en opslag

Voor een geregistreerde opwarmbeurt gebruikt HC de werkelijk verstreken tijd vanaf de startbaseline tot het oorspronkelijke meeteinde (inclusief stabilisatie en wachten op de gasrapportage). Vermogen maal uren geeft de geschatte Wh. De DHW-nacontrole verlengt deze verbruiksperiode niet. De schatting blijft status estimated en electricity_measured=false. De gebruikte aannames staan bij het record en veranderen niet achteraf als de instellingen worden aangepast.

Naloopvermogen maal nalooptijd wordt apart bewaard als postrun_energy_wh. total_energy_if_stopped_wh is het somscenario wanneer de ketel na deze periode stopt. Dit is geen waargenomen naloop: de gewone regeling kan immers blijven verwarmen. Naloop wordt niet bij elk meetpunt als extra verbruik opgeteld. Voorbeeld: een uur op 100 W is 100 Wh; vijf minuten op 50 W is circa 4,17 Wh, samen circa 104,17 Wh indien daarna gestopt wordt.

Als de aannames tijdens de meetbeurt veranderen, blijft de elektrische schatting voor die beurt onbruikbaar, ook na herstel van de oude waarden. De temperatuur- en gaswaarneming blijven bewaard. Een geldige echte elektriciteitsmeting blijft herkenbaar als measured.

Het dashboard toont geschatte Wh en de afzonderlijke verwachte naloop. De gasafbakening en kostenvergelijking krijgen door deze schatting geen automatische vrijgave.

## Geen dubbeltelling in HEMS

De schatting wordt in deze stap niet aan de huisprognose toegevoegd, niet als gemeten aircoverbruik gepubliceerd en niet van het huishoudelijke historische verbruik afgetrokken. Het resultaat markeert forecast_eligible=false met cv_baseline_attribution_required. Zonder aparte meter is de reeds in de huishistorie opgenomen CV-component nog niet betrouwbaar afgezonderd. Het toekomstige CV-plan moet daarom eerst een expliciete vergelijkingsbasis krijgen; alleen een extra profiel bovenop huisverbruik zetten zou dubbel kunnen tellen. Dit blijft onderdeel van de nog te bouwen CV-planroute, niet een afgeronde automatische kostenvergelijking.

Geen HEMS/MEP-productiecode, laadroute of verwarmingsopdracht gewijzigd. Niet live geactiveerd.

## Tests

Gerichte tests controleren de onafhankelijke W-maal-tijd-berekening, afzonderlijke naloop, grenzen/niet-eindige/booleaanse invoer, ontbrekende opt-in, geen stilzwijgende vervanging van een ingestelde meter, volledige CV-opwarmbeurten met echte SQLite-opslag en herstel, blijvende afkeuring bij gewijzigde aannames en expliciete blokkering van gebruik als herleidbare prognosecomponent.

Verse verificatie: 420 tests en 13 subtests geslaagd in 124,20 seconden op de gecombineerde dev.314-basis. Ruff en JavaScript-syntaxiscontrole geslaagd. De HEMS-contractinspectie bevestigt dat de bestaande vervangingsbasis uitsluitend de gemeten aircocomponent bevat; een CV-schatting hierin opnemen zonder afzonderlijke modellering van de historische CV-last zou een onjuiste meetclaim of dubbeltelling veroorzaken. De CV-schatting is daarom nog niet als uitvoerbaar HEMS-plan aangesloten.
