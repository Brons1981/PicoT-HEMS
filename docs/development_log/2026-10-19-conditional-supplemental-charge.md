# Voorwaardelijke aanvullende laadopdrachten

Gebruikersopdracht: herstel onnodig blijvend aanvullend netladen; beperk deze
wijziging tot laden, met behoud van marktroutes. ADR-037.25 legt de expliciete
uitzondering op het vasthouden van aanvullende opdrachten in ADR-037.10 vast.

De diagnose van 19 oktober bevat de herplanning van 18 oktober: hoofdlaadroutes
konden worden verkort, terwijl eerder toegevoegde aanvullende opdrachten als
blijvende verplichtingen terugkeerden. Een oud doel kon bovendien opnieuw aan
een NOM-interval met al voldoende SOC worden gekoppeld zonder werkelijk laden.
Een administratief gemist doel werd daardoor behandeld als nieuwe laadbehoefte.

De adapter genereert nu ook alternatieven waarin toekomstige aanvullende
opdrachten expliciet vervallen. Hij controleert het fysieke overbruggingstekort,
de dagdoelen en ongewijzigde, uitvoerbare marktexport. Kandidaten behouden alle
opdrachten, laten elk afzonderlijk vervallen of laten ze gezamenlijk vervallen;
dit is bewust geen exponentiele zoektocht door alle combinaties. Een draaiende
laadopdracht valt buiten deze nieuwe bevoegdheid.

Evaluation kiest tussen complete routes. Bij een hoofdroutevergelijking met
aanvullende annulering worden importkosten en exportopbrengsten over dezelfde
horizon vergeleken, uitsluitend met gelijke eindvoorraad. Er is geen fictieve
waarde voor resterende batterij-energie en geen vaste voorkeur voor annuleren.
De trigger en Store tellen beide hoofd- en aanvullend netladen mee.

De Store bewaart vervallen doelen met oude opdracht, tijdstip, reden en nieuw
plan-ID in dezelfde opslagtransactie als de vervangende route. Vervallen wordt
niet als werkelijk voltooid geregistreerd. Een herstart opent deze identiteit
niet opnieuw. Het binden van een behouden laadopdracht vereist een echte
toename van opgeslagen energie; een dalend NOM-interval is niet voldoende.

De eerste volledige diagnose-replay vond nog een restfout: een oude netlaadactie
kon als `retained-route` blijven staan nadat haar doel naar eerdere PV was
verplaatst. De binding splitst nu runs op intentie en bestaande doelgrenzen,
behoudt de eigenaar van nog aanwezige netlaadacties en weigert anonieme restanten.
Een verplaatsing naar een ander interval moet het doel daadwerkelijk van onderaf
bereiken. De nieuwe regressietest faalt met de vorige bindingslogica en slaagt
met de reparatie.

Aanvullend is de marktscope expliciet begrensd: bij de bestaande zoektocht door
marktherzieningen krijgt alleen de variant met exact de oorspronkelijke
exportintervallen en -doelen de nieuwe mogelijkheid tot aanvullend vervallen.
Varianten met gewijzigde export houden hun bestaande bevoegdheid, zonder deze
extra keuze. Dit voorkomt ook vermenigvuldiging van het aanvullende zoekwerk
over alle gewijzigde marktvarianten.

Nieuwe tests controleren noodzaak, bescherming van begonnen opdrachten,
afzonderlijk vervallen, marktexport, vergelijkbare financiele uitkomsten,
opslagvalidatie en de volledige selectie/opslag/herstartketen. Bestaande tests
voor hoofdrouteverkorting, overbrugging, PV-optimalisatie en marktroutes worden
meegenomen. Resultaten en diagnose-replay worden hieronder vastgelegd.

Verificatie: 84 verschillende tests geslaagd over de geselecteerde suites.
Na de laatste bindingsreparatie zijn de 42 tests voor economie/opslag,
hoofdrouteverkorting, overbrugging en PV opnieuw uitgevoerd, naast 19 tests
voor aanvullende opdrachten en de nieuwe bindingsgevallen. De 22 markttests
waren reeds groen. Een tussentijdse run had nog de oude tweedoelen-testfixture
geladen; de gecorrigeerde fixture en volledige betreffende testfile zijn daarna
opnieuw geslaagd. Ruff is schoon voor alle vijf gewijzigde bronbestanden en
drie nieuwe testbestanden; mypy is schoon voor de gewijzigde bronbestanden.
De extra marktscope-test controleert zowel hoofd- als overbruggingskandidaten:
gewijzigde exportvarianten krijgen geen aanvullende annuleringsalternatieven,
de variant met oorspronkelijke export wel.

Definitieve replay: diagnose `picot-diagnostics - 2026-10-19T051803.106.zip`,
planning-input van 18 oktober 15:11 lokale tijd, met gereconstrueerde toenmalige
opdrachteigenaren in een lokale Store. Dit is geen volledige chronologische
replay van alle historische Home Assistant-waarnemingen.
De afzonderlijke hoofdroute-ontdekking levert 31 kandidaten, waarvan 22 zonder
het oorspronkelijke laadkwartier van 02:00 uur. De volledige CanonicalPipeline
selecteert en bewaart `plan-e62b90e1e0784b22` met `winner_selected` op financieel
resultaat. De vier oude aanvullende opdrachten `11e566e5870a537c97a4`,
`66ae7c21d578ee032697`, `a4740311c184e364fae0` en `d601481747bd08debd4e`
worden expliciet als vervallen opgeslagen. Exporttijden en gevraagd vermogen
zijn exact gelijk aan het voorgaande plan. Geen anonieme netlaadactie blijft over.

Het geselecteerde hoofdlaadblok ligt nog steeds in de nacht, 19 oktober
02:00-04:45 Europe/Amsterdam. De reparatie verbiedt nachtelijk hoofdnetladen
niet: zij voorkomt dat oude aanvullende doelen onafhankelijk van hun noodzaak
blijven staan. De hoofdroute blijft via de bestaande economische selectie lopen.

Alex heeft controle en release aangevraagd. Releasevoorbereiding als HEMS
2.0.0-dev.308 via afzonderlijke PR en CI op basis van main aa924453.
Energy Devices en HC worden niet gewijzigd. Installatie en livecontrole volgen
na publicatie afzonderlijk.
