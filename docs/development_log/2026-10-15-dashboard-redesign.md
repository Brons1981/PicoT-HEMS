# Rustig dashboard en verversbestendige bediening

## Contract

Alex heeft lokale implementatie gevraagd van het goedgekeurde lichte ontwerp:
Vandaag, Historie en Financieel, met de bestaande 48-uursprijsgrafiek en een
kleinere SOC-grafiek met lege kwartierstaven, groene metingen en gele verwachting.
Automatisch verversen mag invoer, selectie en open toelichtingen niet verstoren.
Geen release, publicatie of wijziging van historische bedragen.

De eerste probleemgrens is DOM-vervanging in de dashboardprojectie: native
invoervelden/selecties worden opnieuw gevuld terwijl de gebruiker bezig is;
gebruikersregels werden na focusverlies overschreven. De verantwoordelijke laag
is uitsluitend de UI. CANONICAL_PIPELINE_CONTRACT en V2ADR-066 blijven leidend;
de laatstgenoemde beslissing krijgt uitsluitend de goedgekeurde displayaanpassing.
MEP, evaluatie, planopslag, uitvoering, bronregistratie en financiële administratie
zijn buiten scope. Terugrollen beperkt zich tot deze UI en bijbehorende tests/docs.

## Implementatie

- Drie primaire tabs; oude Overzicht-keuze leidt naar Vandaag. Strategie,
  Apparaten en Techniek blijven bereikbaar via Instellingen & diagnose.
- Lichte gezamenlijke stijl, centrale pipeline-status (geen extra claim over
  fysieke omvormerwerking), handmatige blokkade en verbindingsfouten zichtbaar.
- Vandaag bevat bestaande prijs-/planinformatie, SOC, Solcast en batterijplan.
  Technische referenties en herstelbediening blijven op het technische scherm.
- SOC-staven gebruiken uitsluitend bestaande gemeten recorderwaarden, nooit de
  verwachting. Bewezen nul, ongeldige/onbeschikbare waarden en toekomstige
  kwartieren blijven onderscheiden. De bestaande kalendergrens blijft behouden,
  inclusief zomer-/wintertijd; geen wijziging van plannerhorizon of simulatie.
- Historie toont energiestromen en zelfverbruik eerst. Schakelingen standaard
  vandaag in Europe/Amsterdam; meer beschikbare dagen zijn apart te kiezen.
- Updates wachten tijdens focus in input/select/textarea of tekstselectie;
  alleen de nieuwste wachtende update wordt toegepast na afloop. Onopgeslagen
  gebruikersregels blijven ook na focusverlies behouden. Details met vaste ID,
  bestaande keyed disclosures, tab, weekkeuze en scrollpositie blijven behouden.
- Kalenderverversing behoudt het open dagoverzicht en wordt niet nogmaals bij
  elke algemene dashboardupdate aangeroepen.

## Verificatie

Nieuwe regressies faalden eerst op de ontbrekende SOC-staven, oude navigatie en
invoerbescherming. Daarna getest met echte JavaScript-uitvoering en een lokale
Edge-browser met uitsluitend onderschepte test-API's (geen Home Assistant).
De browser bewijst 192 omlijningen, 76 verstreken vullingen, toekomstige lege
staven, behouden open details, focus, onopgeslagen invoer na focusverlies,
nieuwste wachtende update, dagfilter en mobiele pagina zonder buitenste overflow.
Grafieken delen één horizontaal scrollvlak op kleine schermen.

AST-vergelijking met HEAD: alle Python buiten DASHBOARD_HTML identiek.
De volledige financiële JavaScript-sectie is bytegelijk. De diagnose van
15 oktober bevat 50 dagrecords; het dashboard leest deze zonder mutatie.
Financiële bedragen, schattingsformule, totalen en terugverdienen blijven gelijk.

215 gerichte regressietests geslaagd. Na de laatste aanpassing voor behoud van
een dicht instellingenmenu: 74 UI-/HTTP-/financiële tests opnieuw geslaagd, plus
herhaalde browsercontrole inclusief dat menu. Ruff en mypy slagen (mypy met
`--platform linux`, passend bij het add-onplatform; de Windows-standaard mist
de bestaande POSIX-constanten in passive_history/export.py). Diffcontrole schoon.

Geen versieophoging, commit, PR, push, installatie of release. Livegedrag op
Alex' Home Assistant is nog niet getest.

## Herstel na review: opslaan en toetsenbordfocus

Op verzoek van Alex twee UI-randgevallen hersteld. Ieder input/change-event
verhoogt de lokale invoerversie. Een succesvol opslagantwoord bevestigt alleen
de verstuurde versie. Nieuwere invoer blijft onopgeslagen staan, met expliciete
melding; opslagfouten behouden eveneens het concept. Tijdens een lopend verzoek
wordt een tweede submit geweigerd, zonder nieuwe apparaat- of planneractie.

Verversen bewaart de identiteit van het gefocuste bedieningselement. Bij DOM-
vervanging wordt het overeenkomstige element teruggevonden via ID of een unieke
combinatie van container-ID, elementtype en label. Geen focusverplaatsing bij
verdwenen/ambigue elementen of wanneer de gebruiker inmiddels elders focus heeft.
Herstel gebruikt preventScroll en behoudt de bestaande scroll-/uitklaptoestand.

Regressies faalden eerst op beide fouten. Na herstel: 121 gerichte tests groen,
Ruff en mypy (Linux-doelplatform) groen. Browserproef met vertraagd onderschept
opslagantwoord: 37 versturen, 41 intypen, focus verlaten, antwoord voor 37 en
verversing ontvangen behoudt 41. Na drie verversingen behoudt de uitklapkop focus
en wisselt Enter nog steeds de open toestand. Er zijn geen live verzoeken gedaan.
Een eerdere brede run had 118 geslaagde tests en een afgebroken lokale HTTP-
verbinding (Windows 10053); de afsluitende volledige run slaagt. Dit incident
is niet stilzwijgend als bewezen productfout of bewezen testflakiness aangemerkt.

Verse vergelijking met HEAD: Python buiten de HTML is identiek, financiële
JavaScript bytegelijk, financiële weergave van 50 opgeslagen dagrecords gelijk.
Ingelezen records en hash van de diagnose-ZIP zijn onveranderd. Geen release.

## Releaseautorisatie

Alex heeft na de bijgewerkte voorvertoning expliciet PR, automatische controles,
samenvoegen en release aangevraagd. De eerdere lokale-only beperkingen hierboven
beschrijven de voorafgaande fase. Releasevoorbereiding: dev.298 vanaf
`c621518118cec6d71006df17a918d8f7e8afda08`, met versie-afstemming en changelog in
dezelfde PR als de UI. Samenvoegen pas nadat de controles op deze PR groen zijn.
Installatie in Home Assistant en livecontrole volgen afzonderlijk.

CI-correctie PR #705: de bestaande SVG-renderertest laadde alleen renderPriceTimeline en verwachtte nog de vervangen werkelijke SOC-lijn. De test laadt nu ook socQuarterSlots en controleert vier lege omtrekken, uitsluitend twee gemeten vullingen op de juiste kwartieren, 30% hoogte, prognoseonderbrekingen, arcering en onveranderde invoergegevens. Geen productiecode gewijzigd. Gerichte grafiek- en dashboardtests: 26 geslaagd; Ruff geslaagd.
