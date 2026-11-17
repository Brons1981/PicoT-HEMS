# EV-laadmoment onafhankelijk van batterijroutes

## Afspraak

HEMS kiest het goedkoopste aaneengesloten EV-laadblok binnen beschikbaarheid en
eindtijd. De Zendure levert niet aan de BMW. Het batterijplan is geen algemene
toelatingsvoorwaarde. Alleen aantoonbaar resterende PV, na huis en geplande
batterijlading, telt mee als zonne-energie voor de auto.

## Oorzaak en wijziging

De diagnose van 17 november 21:51 bevat vier afgeronde/gestopte markttoewijzingen
van 9, 10, 11 en 13 november. De oude gezamenlijke bevestiging voegde die toe aan
een context zonder hun historische plannen. Een lokale kopie reproduceerde vier
niet-actieve verwijzingen via preview_retained_market_bindings.

De normale runtime gebruikt nu ev_independent_advice. Deze vergelijkt alle
start- en eindgrenzen van prijzen en PV-overschot, inclusief gedeeltelijke
kwartieren, tot de gepubliceerde prijshorizon. Ontbrekende prijzen blijven
expliciet voorlopig. Het bestaande batterijplan wordt niet gewijzigd of opnieuw
geoptimaliseerd. Een bruikbare batterijprojectie is uitsluitend bewijs voor
PV-overschot; zonder dit bewijs blijft netprijsplanning mogelijk. PV krijgt de
canonieke terugleverwaarde als opportuniteitskosten. Batterij-export krijgt geen
EV-korting. Bestaande schakel- en uitsluitingscontroles blijven actief.

Nieuwe adviezen hebben geen gezamenlijke selection_id en vereisen geen tweede
batterijbevestiging. ED kan de gekozen opdracht direct duurzaam vastzetten. Een
automatische aanvraag die vastzit op de gemelde historische-planfout wordt
vernieuwd zonder het oude onbevestigde blok te starten. Historische verwijzingen
worden ook uit de oude gezamenlijke controle gehouden als hun plan niet bij de
herstelde context hoort; de opgeslagen historie blijft behouden.

Het dashboard onderscheidt wachten op bevestiging van werkelijk gepland. Het
toont EV-laadkosten en PV-bijdrage, met uitleg als alleen netprijzen konden worden
vergeleken. Diagnosevelden bevatten dezelfde onderbouwing.

## Verificatie en grenzen

Regressies: plannen zonder batterijcontext/SOC, geblokkeerde batterijcontext,
negatieve prijzen tijdens een marktvenster, gedeeltelijk kwartier, verstreken
start, ontbrekende prijzen, PV voor huis, PV voor Zendure, echt PV-overschot,
herstel oude blokkade, echte advisor/ED-uitvoering en herstart.

Eerste regressietests faalden op de oude runtime. De oude end-to-end-test die een
batterijherziening eiste is aangepast aan het expliciet gewijzigde contract.
Lokale sockettest blijft uitgesloten vanwege de bekende Windows-beperking.
Geen live auto- of visuele browsertest. De bestaande voorspelde SOC en vaste
laadvermogens blijven benaderingen. PV buiten een bruikbare batterijprojectie
wordt conservatief niet als beschikbare zonne-energie gewaardeerd.

Voor publicatie beide add-ons bijwerken: HEMS bevat de nieuwe keuze, ED bevat
automatisch herstel en de statusuitleg. Publicatie gevraagd via PR en groene CI; geen live installatie.
Basis hoofdbranch: 92f89a6937ee4735ce949dcd4c38de17bf4c9fd9.

Definitieve lokale verificatie: 275 tests geslaagd, 1 sockettest uitgesloten,
155,14 seconden. Ruff geslaagd; strikte Mypy op zes bronbestanden geslaagd;
JavaScript-syntax gecontroleerd met Node. Publicatiecontrole via CI; geen live wijziging.
