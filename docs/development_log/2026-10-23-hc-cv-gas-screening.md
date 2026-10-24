# Warmwatergebruik markeren bij CV-opwarmmetingen

## Uitkomst en grens

HC kan waargenomen warmwatergebruik tijdens een passieve CV-opwarmmeting blijvend markeren. De bestaande configuratie bevat een algemene CV-status en een huishoudelijke gasmeter, maar geen bevestigde warmwaterstatussensor. Die algemene CV-status wordt niet als warmwaterstatus gebruikt.

De nieuwe optionele addoninstelling `cv_dhw_active` staat standaard leeg. Alleen een werkelijk passende ketelsensor gebruiken: `on` betekent warmwaterbedrijf, `off` betekent geen warmwaterbedrijf. Geen sensor automatisch ingevuld of live geactiveerd. Een apart ingestelde algemene CV-status, CV-climate-entiteit of huishoudelijke gasmeter wordt expliciet geweigerd als warmwaterbron.

## Gedrag

De reader accepteert uitsluitend expliciet on/off, een beschikbare bron zonder rapportfout en een rapporttijd met tijdzone van maximaal 60 seconden oud, niet in de toekomst. Ontbrekende, verouderde of ongeldige status wordt niet uitgelegd als uit.

Bij elke passieve meetstap telt HC de beginwaarneming en de huidige waarneming mee. Eén geldige on-melding blijft voor de hele poging bewaard. Een ontbrekende waarneming of gewijzigde sensoridentiteit maakt de dekking blijvend onvolledig, ook als de bron later terugkomt.

Het afgeronde record krijgt `gas_screening`:

- `dhw_observed`: warmwaterbedrijf waargenomen; gasmeting mogelijk vermengd.
- `no_dhw_observed`: alle opgehaalde statuswaarden waren beschikbaar en uit, met dezelfde bron.
- `incomplete`: ontbrekende/ongeldige gegevens of gewijzigde bron, zonder waargenomen warmwaterbedrijf.
- `polling_complete`: volledigheid van de opgehaalde meetpunten, geen garantie op gebeurtenisdekking.
- `heating_only_confirmed`: altijd false.

De gasdelta blijft het huishoudelijke totaal. HC trekt geen geschat warmwatergebruik af en noemt dit geen gemeten verwarmingsgas. De temperatuur- en elektriciteitsmeting blijven bewaard. Oude records blijven leesbaar; een herstart hervat geen gedeeltelijke opwarmmeting. Het dashboard toont de uitkomst voor de laatste afgeronde meting.

## Waarom nog geen vrijgave voor kostenvergelijking

Tussen twee polls kan kort warmwaterbedrijf plaatsvinden. Ook gas voor koken en gasrapportage die terugkijkt tot voor de opwarmstart zijn hiermee niet afgebakend. Geen waargenomen warmwaterbedrijf is dus geen bewijs van uitsluitend ruimteverwarming. `comparison_eligible` en `execution_authorized` blijven false. Voor betrouwbare afbakening is eerst nodig te weten welke werkelijke ketel-/warmwatergegevens beschikbaar zijn en welke andere gasverbruikers de woning heeft. Daarna kan een volledige gebeurtenishistorie of aparte verbruikstelling worden beoordeeld.

Deze stap verandert geen verwarmingsopdrachten, comfortschema, HEMS-plannen of MEP-code.

## Verificatie

Tests omvatten blijvend onthouden van een korte warmwatermelding, herstel na ontbrekende status zonder ten onrechte volledige dekking te claimen, bronwissel, opslag/herladen, on/off, ontbrekende configuratie, weigeren algemene CV-status, verouderde/toekomstige/tijdzoneloze rapporttijd en rapportfouten. Een lokale runtime-integratietest doorloopt een CV-opwarmbeurt met één warmwatermelding en controleert dat er slechts één verwarmingsopdracht volgt. Home Assistant-transport is vervangen door testdata; hardwarewerking is niet getest.

Verse verificatie: 274 tests en 13 subtests geslaagd in 54,66 seconden in de gecombineerde HC/HEMS-regressieselectie. Ruff voor de gewijzigde Python-code/tests, JavaScript-syntaxiscontrole en git diff --check geslaagd. Niet gecommit, gepusht of gedeployd.
