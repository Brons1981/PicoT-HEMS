# Weer meewegen in het leren beneden

De bestaande `weather_entity` levert nu naast de losse weerweergave ook context aan de empirische modellen voor beneden. HC leest wind, bewolking en dag/nacht uit de reeds opgehaalde HA-staten. Er komen geen nieuwe netwerkverzoeken, apparaatopdrachten of instellingen bij. Boven, garage en badkamer krijgen hiermee geen eigen regeling.

## Waarneming en vergelijking

Wind wordt vanuit m/s, km/h, mph of knopen naar m/s omgerekend. De weerwaarneming moet maximaal dertig minuten oud zijn, een bekende toestand hebben en een eindige, niet-negatieve windwaarde binnen de gevalideerde grens leveren. Bewolking wordt ingedeeld als helder, gemengd of bewolkt via `cloud_coverage`, of via een ondersteunde HA-weertoestand als dit attribuut ontbreekt. `sun.sun` moet aangeven of de zon boven of onder de horizon staat. Helder overdag wordt dus niet als gelijk aan een heldere nacht beschouwd.

Vergelijkbare waarnemingen hebben dezelfde weerbron, bewolkingsgroep en dag/nachtstatus en verschillen maximaal 2 m/s in wind. Dit zijn begrenzingen voor vergelijkbare waarnemingen, geen berekende warmteverliesfactoren. Bestaande temperatuurgrenzen en marges blijven gelden.

Deze context wordt bewaard bij afkoelmetingen en bij airco- en CV-metingen voor opwarmen en handhaven. Een verandering buiten de vergelijkbaarheidsgrens onderbreekt een lopende meetperiode. De bestaande eisen aan onder meer meterdekking, opdrachtbevestiging en vertraagde warmwatercontrole blijven intact. Na een herstart blijft het weerlabel onderdeel van de opgeslagen onderbouwing.

De feedback voor voorverwarmen en terugregelen gebruikt passende weeruitkomsten. Zonder drie passende uitkomsten wordt geen eerder geleerde korte voorlooptijd of diepe verlaging overgenomen: de initiële voorlooptijd en voorzichtige verlaging blijven de ondergrens. De status toont de gebruikte wind, bewolkingsgroep, dag/nacht en het aantal passende opwarmbeurten.

## Ontbrekende gegevens en grenzen

Ontbrekende of verouderde weergegevens worden niet als windstil of helder ingevuld. Oude metingen zonder weerlabel blijven een afzonderlijke populatie: ze kunnen alleen met een vraag zonder volledig weerlabel worden vergeleken, volgens de bestaande temperatuurgrenzen en conservatieve marges. Bekende weerlabels en ontbrekende labels worden nooit gemengd. Normale comfortregeling blijft beschikbaar als er onvoldoende passende leergegevens zijn.

De bestaande dagelijkse weersverwachting wordt niet gebruikt om het weer voor een specifiek uur te verzinnen. Dit is leren op waargenomen weer; voorspelde veranderingen tijdens een toekomstige opwarmperiode blijven onzeker. Het model kent geen windrichting, geveloriëntatie, zoninstraling of afzonderlijke stralingsverliezen. Het afleiden van zulke effecten zonder metingen is niet toegevoegd.

## Verificatie

Nieuwe tests controleren normalisatie van windeenheden, ongeldige/verouderde data, bewolking en dag/nacht, opslag en herladen van gemeten handhaafperioden, afbreken bij weersverandering, behoud van CV-warmwatercontrole, voorzichtige voorlooptijd/verlaging bij nieuw weer en de runtime-koppeling. Een aanvullende runtimeproef controleert dat gewijzigde bewolking een eerder onderbouwde afbouw terugbrengt naar het comfortdoel. De definitieve testuitslag wordt opgenomen in de overkoepelende overdracht.
