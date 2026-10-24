# CV-opwarmraming en resterende integratie

## Geïmplementeerd

`cv_energy_model.estimate` maakt een expliciete schatting uit minimaal drie verschillende, passende CV-opwarmbeurten. De bestaande SQLite-registratie blijft de bron. De runtime geeft de actuele context en het ingestelde gastarief door; de HC-interface toont gas, gaskosten, tijd en elektrisch hulpverbruik. Boven bepaalt deze raming niet.

Een sessie telt alleen mee na volledige warmwatercontrole inclusief de 90 seconden na de oorspronkelijke eindmeting. Waargenomen DHW, gaten, onvoltooide controle, veranderde bron of hulpverbruikaannames, dubbele command-ID's, ongeldige getallen en afwijkende temperaturen tellen niet mee. De eerste gasstand mag hoogstens 60 seconden vóór de start liggen; de laatste moet de stabilisatieperiode dekken. Deze extra grens voorkomt dat een oude beginstand stilzwijgend als nauwkeurig afgebakende sessie wordt behandeld. Hierdoor kan het verzamelen bij een traag rapporterende gasmeter langer duren.

De raming gebruikt het hoogste gasverbruik van de passende sessies plus 25%. De tijd gebruikt de volledige registratie, inclusief stabilisatie en wachten op de laatste gasrapportage, eveneens plus 25%. Hulpverbruik wordt voor deze tijd berekend met de expliciete aannames. Een eventuele toekomstige pompnaloop blijft apart en wordt niet meermalen toegevoegd. Ontbrekend of ongeldig gastarief betekent onbekende kosten, niet nul euro.

Dit is een empirische schatting, geen bewezen bovengrens en geen meting van uitsluitend ruimteverwarming. Een DHW-puls kan tussen pollmomenten vallen. Daarom blijft `heating_only_confirmed=false`. Ook `comparison_eligible` en `execution_authorized` blijven false: de complete CV-planroute ontbreekt nog. De bestaande actieve huisprognose en de fysieke apparaten worden door deze toevoeging niet aangepast.

## Concrete resterende werkzaamheden

1. Een gezamenlijke vervangingsbasis voor airco en geschatte CV-ruimteverwarming. De huidige geschatte ketelhistorie omvat ook warmwaterbedrijf; dat deel moet in de restprognose blijven. Alleen de hele ketellast aftrekken zou de vergelijking onjuist maken. De vertraging van DHW-meldingen moet hierbij worden meegenomen.
2. CV-verbruik tijdens handhaven leren en daarmee complete plannen opstellen tot het einde van het comfortvenster. De nieuwe functie dekt alleen opwarmen. De bestaande aircoplannen dekken nog korte deelvensters.
3. CV-alternatieven aan hetzelfde HEMS-aanbod koppelen en de keuze via bestaande bewaking, starttoestemming, reservering en uitvoeringsbevestiging uitvoeren. Deze uitvoeringsketen ondersteunt nu alleen de airco beneden.
4. Extra laden tegenover gasverwarming afwegen. HEMS beoordeelt de huidige voorstellen bij de behouden batterijroute; het optimaliseert nog geen extra laadroute voor elk alternatief.
5. Wind/bewolking als leercontext toevoegen en het gedrag met echte woningmetingen valideren. De huidige thermische modellen gebruiken binnen- en buitentemperatuur.

Dit zijn ontbrekende implementaties; ze verdwijnen niet vanzelf door meer meetgegevens. De totale opdracht is daarom nog niet releaserijp. De dev.314-nachtreparatie blijft behouden en is afzonderlijk op AST-gelijkheid gecontroleerd.

## Verificatie

De gerichte tests beginnen met een echte CV-sessieregistratie en warmwatercontrole, bewaren/herladen de historie via SQLite en controleren de ramingen en blokkeringen. De eerste run faalde omdat de nieuwe module ontbrak; na implementatie zijn de gerichte tests groen. De brede HC/HEMS-regressie en statische controles worden hieronder vastgelegd na afronding.

Verse resultaten: gecombineerde reeks 453 tests en 13 subtests geslaagd in 314,40 seconden. Na de laatste aanscherping van DHW-bronidentiteit en diagnosetekst is de volledige gerichte CV-reeks opnieuw uitgevoerd: 79 tests geslaagd in 12,61 seconden. Ruff op de nieuwe module, de CV-registratie en de nieuwe tests, F-controle op de runtime en node --check op app.js geslaagd. Geen live communicatie of echte woningproef uitgevoerd; geen commit, push of release.
