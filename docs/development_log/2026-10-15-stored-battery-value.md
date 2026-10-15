# Geschatte batterijwaarde — lokaal, geen release

Alex vraagt een extra kolom met alleen korte uitleg bij de titel. Bestaande
financiële berekeningen en historische bedragen blijven ongewijzigd.

De kolom toont een afzonderlijke bruto eigenverbruiksschatting: actuele energie
boven de minimumreserve, na het bestaande ontlaadrendement, maal de tijdgewogen
gemiddelde inkoopprijs voor de komende 24 uur. Dit is een expliciet scenario,
geen verbruiksvoorspelling, verkoopwaarde, winst of voorraadkostengrondslag.
Geen zonnebonus, nieuwe plannerbeslissing, weekoptelling of terugverdienbijdrage.

De optionele `estimated_battery_value` wordt alleen aan nieuw bijgewerkte
dagrecords toegevoegd. Oude records worden niet aangevuld of gemigreerd.
De laatst vastgelegde schatting blijft bij die dag horen. Geen passende unieke
batterij/limiet, SOC ouder dan 15 minuten, of ontbrekende/overlappende/niet-eindige
prijzen betekent onbekend. Nul en negatieve schattingen blijven echte waarden.
Onbeschikbaarheid of een fout in deze optionele laag blokkeert de bestaande
financiële administratie niet. De bestaande voorraadkosten blijven identiek.

De UI voegt uitsluitend een tabelkolom toe: `≈ bedrag`, `—` bij onbekend en
een punt voor toekomstige dagen. Eén toelichting bij de kop, geen extra
uitklapvak. De oude diagnose van 15 oktober bevat nog geen nieuwe schatting
en toont daarom streepjes in de lokale preview.

Verificatie: 91 gerichte voorraad-, dagboek-, financiële UI- en dashboardtests
geslaagd met Python UTF-8-modus. Zonder UTF-8 gaf de bestaande JS-syntaxcheck
op Windows een encodingprobleem; met `-X utf8` slaagt dezelfde check.
Ruff en mypy slagen. Browsercontrole: vijf kolommen, desktop en mobiel zonder
pagina-overflow of JavaScript-fouten. Screenshot visueel gecontroleerd.
Geen release, push of livewijziging.

## Herstel na tweede controle

De SOC-versheid gebruikt nu de geldige HA-uitleestijd indien aanwezig, met
terugval op het meettijdstip. Een gelijkblijvende SOC wordt zo niet afgewezen
omdat last_updated oud is. Tests bewijzen de 15-minutengrens en afwijzing van
toekomstige uitleestijden. De kolomkop heeft nu een echte knop met aria-controls
en aria-expanded die één korte toelichting toont/verbergt; geen daguitklappers.

De regressietests faalden eerst op beide fouten; na herstel slagen 96 tests.
Browsercontrole met touch en toetsenbord (Enter/Spatie) bevestigt openen en
sluiten. Ruff, mypy en diffcontrole slagen. Vergelijking met HEAD bevestigt
opnieuw identieke 50 historische dagrecords en totalen, plus identieke bestaande
updatevelden bij positieve, nul- en negatieve tarieven. Geen release.
