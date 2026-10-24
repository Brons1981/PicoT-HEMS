# Geschatte ketellast naast gemeten aircolast

De nieuwe HC AuxiliaryHistory verwerkt verse binaire CV- en DHW-statussen met de expliciete hulpverbruikaannames. Een actieve bron geeft geschat bedrijfsvermogen; na de overgang naar beide uit volgt eenmaal de ingestelde naloop. Bij onbekende/te oude/toekomstige gegevens, gewijzigde aannames, herstart of een onderbreking begint onbekende dekking. Bij een start met beide uit is eerst nalooptijd plus 90 seconden aaneengesloten status nodig voordat een geschatte nul wordt gepubliceerd. Bedrijfsvermogen, naloop en nul blijven modelschattingen, geen metingen. Standbyvermogen buiten deze aannames is niet gemodelleerd.

HC voegt estimated_component met contract modeled-load:v1 toe aan de bestaande verbruikspublicatie. De gemeten aircopower, source_id en controlled-load-measurement:v1 blijven apart. De modeled source-id is een hash van beide bronentiteiten en de gebruikte aannames: andere instellingen leveren een andere historie-identiteit.

HEMS slaat modeled_power_w en modeled_source_id optioneel op naast de gemeten controlled_power_w/source_id. Het fysieke totale vermogen verandert niet. De geschatte last moet passen binnen totaal minus EV minus gemeten airco, en de actuele powerbalans/aircotoeschrijving moet geldig zijn. Anders blijft alleen de schatting onbekend; er wordt niet begrensd naar een aannemelijke waarde. De publicatietijd moet actueel zijn en aansluiten op de fysieke waarneming. Oude historie zonder modelgegevens wordt niet achteraf gevuld. Een ongeldige optionele schatting wist geen geldige fysieke of aircometing.

## Prognosebasis

De parallelle modelprognose gebruikt exact dezelfde kwartierselectie en weging als de bestaande huishoudelijke historie. Elk geselecteerd meetpunt moet bij dezelfde modelidentiteit horen. Totaal = geschatte component + rest; gemeten waarnemingen worden hiervoor niet gewijzigd. De uitkomst heeft expliciete modeled-method/source-labels. Ontbrekende componenthistorie geeft geen bruikbare parallelle prognose en wordt nooit nul.

De nieuwe diagnostiek modeled_component beschrijft alleen beschikbaarheid van deze parallelle historie. active_forecast_corrected blijft false. De actieve MEP-prognose, laadroute, SOC-grenzen en dev.314-reparatie blijven ongewijzigd. MEP krijgt geen CV-entiteiten of apparaatregels.

Deze registratie is een benodigde basis voor latere vervanging, niet de volledige CV-planner. De geschatte ketellast omvat hier zowel zichtbaar CV- als warmwaterbedrijf. Een toekomstige verwarmingskeuze mag het verwachte warmwaterdeel niet verwijderen. Het koppelen van een volledig CV-plan aan een expliciete gezamenlijke vergelijkingsbasis (inclusief behouden warmwatervraag), gasraming en uitvoering blijft vervolgwerk. Het huidige ontbreken van dubbeltelling volgt uit behoud van de actieve totale prognose; er is nog geen schatting bovenop gezet of van afgetrokken.

## Verificatie

Tests gaan van HC-status en schatting via HEMS-attributie naar echte JSONL-opslag/herladen; controleren onmogelijke som, ontbrekende aircometing, ongeldige identiteit, NaN, tijdsafwijking, herstart, naloop, identieke prognoseweging, energiebehoud en ontbrekende/corrupte optionele historie. De echte planning-inputassembler controleert dat de component wordt geregistreerd terwijl de actieve huisprognose ongewijzigd blijft. Geen live systemen aangestuurd.

Verse gecombineerde regressie: 430 tests en 13 subtests geslaagd in 123,45 seconden, inclusief dev.314-nachtreparatie, prognose-invoer en laadroutecontroles. Ruff op nieuwe modules/tests en F-controles op gewijzigde grote modules geslaagd. Niet gecommit, gepusht, gereleased of live geactiveerd.
