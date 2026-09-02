# PicoT HEMS chatlog — keuzes en ontwerpbasis DEV.214 t/m DEV.232

Datum vastlegging: **2026-09-03**  
Status: **geaccepteerde sessiebesluiten en ontwerpbasis; geen nieuwe ADR**

## Doel van dit document

Dit document legt de relevante keuzes uit de ontwikkelgesprekken rond
DEV.214 t/m DEV.232 vast. Het moet voorkomen dat een volgende wijziging:

- opnieuw buiten de afgesproken architectuurlagen wordt gebouwd;
- persoonlijke gebruikersvoorkeuren als verborgen plannerlogica invoert;
- een geldig compleet energiepad vervangt door losse kwartierbeslissingen;
- opnieuw een explosie van kandidaten, rekentijd of geheugenverbruik veroorzaakt;
- een eerder geaccepteerde marktroute onbedoeld ongeldig maakt.

Dit document beschrijft zowel reeds gebouwde delen als richtinggevende keuzes.
Een keuze die hier staat is niet automatisch volledig geïmplementeerd of live
bewezen.

## Normatieve grens

Voor deze herstel- en ontwikkellijn zijn uitsluitend **ADR-001 t/m ADR-037**
normatief. Latere ADR's, waaronder V2ADR-056, mogen niet als geaccepteerde
ontwerpbasis worden gebruikt.

Bij strijdigheid geldt de volgende volgorde:

1. veiligheid en harde fysieke/technische grenzen;
2. ADR-001 t/m ADR-037 en het Canonical Pipeline Contract;
3. expliciete User Rules;
4. optimalisatie volgens de actieve Planner Strategy;
5. dit document als sessiecontext en ontwerpintentie.

Een persoonlijke voorkeur die niet algemeen uit ADR-001 t/m ADR-037 volgt,
wordt als zichtbare User Rule gemodelleerd en niet als verborgen dwang in de
planner geplaatst.

## Gewenst dagelijks energiepad

De voorkeursroute voor de thuisbatterij is een compleet en doorlopend pad:

1. vroeg in de ochtend NOM voor huishoudondersteuning;
2. beschikbare PV opvangen en opslaan;
3. alleen indien nodig een begrensd netlaadvenster gebruiken;
4. daarna opnieuw NOM of slim huishoudelijk ontladen;
5. een begrensde marktexport uitvoeren wanneer daarvoor een geldig prijsvenster
   en voldoende vrijgegeven SoC beschikbaar zijn;
6. na de export terugkeren naar NOM zolang het geprojecteerde PV-venster nog
   loopt, en daarna naar het resterende huishoudpad.

PicoT mag een financieel of technisch beter compleet pad kiezen, maar moet dan
met herleidbaar bewijs tonen waarom dat pad beter of noodzakelijk is.

## Verantwoordelijkheden per architectuurlaag

### Planning Input

- Levert één onveranderlijke momentopname per plannerrun.
- Bevat onder meer actuele SoC, huishoudvraag, prijsforecast, PV-forecast,
  confidence, technische mogelijkheden, User Rules en Planner Strategy.
- Verandert de gegevens niet tijdens dezelfde run; een materiële wijziging
  veroorzaakt een nieuwe momentopname en herplanning.

### Opportunity Engine

- Detecteert objectieve, onderbouwde kansen zoals een laag prijsdal en een hoge
  terugleverwaarde.
- Levert vensters en bewijs, maar geen laad-, ontlaad- of exportopdracht.
- Kiest geen apparaat, vermogen, SoC-budget, kandidaat of winnaar.
- Bij afwezigheid van een relevant prijsvenster wordt geen marktactie voor die
  periode voorbereid.

### Candidate Engine

- Bouwt een kleine, begrensde verzameling betekenisvolle **complete Energy
  Paths** over de planninghorizon.
- Gebruikt kansen als bewijs en nooit als directe opdracht.
- Past geldige User Rules toe bij het vormen van complete paden.
- Behoudt een technisch geldige basisroute als vergelijkingsalternatief.
- Voorkomt combinatorische groei door benodigde energie eerst naar tijd om te
  rekenen en alleen de passende tijdblokken op relevante vensters te projecteren.

### MEP / simulatie en Candidate Outcomes

- Simuleert de reeds gevormde complete Energy Paths over de tijdlijn.
- Berekent fysieke haalbaarheid, SoC-verloop, energiebronnen, verliezen,
  reserves en financiële gevolgen.
- Houdt rekening met reeds lopende energie-zandlopers en verplichtingen.
- Maakt geen onbeperkte nieuwe routecombinaties en kiest geen winnaar.
- Mag een pad ongeldig verklaren op basis van expliciet bewijs, maar mag een
  upstream pad niet stilzwijgend vervangen of herinterpreteren.

### Evaluation Engine

- Vergelijkt uitsluitend geldige Candidate Outcomes.
- Selecteert precies één bestaande kandidaat volgens de actieve Planner
  Strategy, User Objectives, confidence en vaste tie-breaks.
- Maakt geen nieuwe kandidaat, simuleert geen alternatief en wijzigt geen User
  Rule.

### Execution Plan Builder en Execution

- De Builder vertaalt het winnende Energy Path zonder nieuwe energie-inhoud of
  herinterpretatie naar uitvoeringssegmenten.
- Execution bewaakt lopende zandlopers, doel-SoC, technische beschikbaarheid en
  actuele veiligheid.
- Exact stoppen bij het vrijgegeven energie- of SoC-budget is uitvoering; het
  vereist geen nieuwe kwartierkandidaat.
- Vendorvertaling blijft uitsluitend de verantwoordelijkheid van de adapter.

## Begrensd rekenen: energie wordt tijd

De kern van het eenvoudige ontwerp is:

> benodigde of vrijgegeven energie = belasting × benodigde tijd.

Voor een batterijactie wordt het SoC-verschil naar energie omgerekend en bij
het geldige laad- of ontlaadvermogen naar een duur. MEP schuift deze begrensde
duur over de tijdlijn met prijs, PV en bestaande verplichtingen als context.

De kwartierprijzen vormen de beschikbare tijdvakken, maar de batterij hoeft niet
altijd exact op een kwartiergrens te stoppen. Zodra uitvoering begint, loopt een
energie-/SoC-zandloper totdat het exacte doel of budget is bereikt.

Dit principe moet later ook bruikbaar zijn voor EV, wasmachine en droger:
bekende belasting en benodigde energie/looptijd leveren één begrensde taak die
over de tijdlijn kan worden geplaatst. Dat toekomstbeeld autoriseert in deze
DEV-lijn nog geen implementatie voor die apparaten.

## PV en confidence

### Planningsbasis

- De vooraf gebruikte PV-basis ligt tussen Solcast `lower` en `central`.
- Hoge confidence beweegt de gebruikte forecast richting `central`.
- Dalende confidence beweegt de gebruikte forecast richting `lower`.
- `upper` wordt niet vooraf als extra permanente kandidaat doorgerekend. Het
  wordt pas relevant wanneer actuele metingen aantonen dat de productie hoger
  uitvalt en een materiële herplanning gerechtvaardigd is.
- Onzekerheid leidt tot conservatievere reserve en herstelbaarheid, niet tot het
  stilvallen van Price Driven planning.

### Monitoring tijdens de dag

PicoT moet de werkelijke PV-productie blijven volgen. Als Solcast onzeker of te
laag blijkt en er toch PV beschikbaar is, moet een nieuwe momentopname die
werkelijkheid kunnen benutten.

Netondersteuning wordt zo laat binnen het geldige goedkope venster geplaatst
dat PV eerst een reële kans krijgt de batterij zonder onnodige netimport te
vullen. Tijdens de dag mogen benodigde laadkwartieren worden toegevoegd of
verwijderd op basis van actuele voortgang en een nieuwe plannerrun.

## SoC-doel en seizoensrichting

- Wanneer voldoende PV wordt verwacht om 100% SoC te bereiken, is 100% de
  gewenste gewogen richting.
- Bij minder PV kiest PicoT een geldig financieel en technisch pad met een zo
  hoog mogelijke zinvolle SoC; structureel de hele winter tussen bijvoorbeeld
  20% en 80% pendelen is niet de gewenste standaard.
- De bovenste capaciteit kan later nodig zijn voor een duurder moment en helpt
  ongecontroleerde batterijkalibratie te vermijden.
- Richting 2027 krijgen zelfgebruik en PV-opslag extra waarde. Daarom moet de
  architectuur nu al alle beschikbare PV kunnen behouden zonder de normale
  financiële vergelijking uit te schakelen.

## Markthandel als begrensde zandloper

### Ontladen

- De gebruiker stelt een maximaal dagelijks handelsbudget in SoC-procent in;
  de standaard is 25%, maar bijvoorbeeld 27% blijft exact 27%.
- Dat budget wordt bij het geldige ontlaadvermogen — tijdens deze sessie
  2400 W — omgerekend naar een maximale uitvoeringsduur.
- Die duur wordt op het hoogste geldige exportvenster geprojecteerd.
- Uitvoering stopt zodra het vrijgegeven SoC-budget daadwerkelijk is verbruikt.
- Er worden geen extra varianten doorgerekend voor ieder denkbaar start- en
  eindkwartier.

Het maximaal instelbare handelsbudget wordt begrensd door:

`100% - 10% technische ondergrens - benodigde huishoudreserve - 10% extra reserve`

Een User Rule mag daardoor nooit toekomstige huishoudondersteuning of benodigde
herstelplannen onmogelijk maken.

### Laden

- Het verschil tussen actuele/verwachte SoC en het benodigde doel bepaalt de
  laadenergie en daarmee de benodigde laadduur.
- De benodigde tijd wordt binnen een breed, geldig laagprijsvenster rond het
  goedkoopste prijsdal geplaatst.
- Buiten het relevante prijsdal ontstaan geen extra laadkandidaten.
- PV-only en grid-only kunnen dezelfde begrensde vensterselectie gebruiken.
- Bij PV met netondersteuning krijgt PV eerst kans; alleen het resterende tekort
  wordt in een later deel van het geldige venster via het net aangevuld.
- Zonder geldig prijsvenster wordt geen markt-netlaadroute gepland.

## Canonieke User Rules

User Rules zijn zichtbaar, persistent, configureerbaar via het
Strategie-dashboard en onderdeel van Planning Input. Ze vereenvoudigen de
kandidatenruimte en maken persoonlijke voorkeuren expliciet.

### Volledig PV-venster behouden bij noodzakelijk netladen

Wanneer netladen onderdeel is van een geldig compleet pad:

- projecteer NOM over het volledige relevante Solcast-PV-venster;
- behoud expliciet netladen als overlay;
- behoud expliciete handel/teruglevering als overlay;
- keer na een overlay terug naar NOM zolang het PV-venster nog loopt;
- vervang de bestaande marktroute niet door een andere hybride bovenliggende
  kandidaat.

De vaste prioriteit binnen hetzelfde energiepad is:

1. expliciet netladen;
2. expliciete handel/teruglevering;
3. NOM tijdens het geprojecteerde PV-venster;
4. de oorspronkelijke huishoudmodus buiten dat venster.

Deze regel beschrijft niet dat alle PV-kandidaten moeten vervallen. Hij legt een
gebruikersvoorkeur over een geldig compleet pad zonder de expliciete marktactie
te verwijderen.

### Maximaal dagelijks handels-SoC

- Configureerbaar in het Strategie-dashboard.
- Technisch begrensd door ondergrens, huishoudreserve en extra reserve.
- Bepaalt vooraf de maximale energie-zandloper en reduceert daardoor het aantal
  te onderzoeken varianten.

### Verrekening energiebelasting bij teruglevering

- De gebruiker kan aangeven of PicoT energiebelasting financieel verrekent.
- Dit is zowel een contract-/salderingsinstelling als een diagnosemogelijkheid
  om een huidig plan met de 2027-achtige waardering te vergelijken.
- Het verandert de financiële waardering, niet de fysieke energieroute of de
  laagverantwoordelijkheden.
- De gebruiker blijft verantwoordelijk voor de juiste contractwaarde wanneer
  PicoT de resterende salderingsruimte niet exact kent.

Later kan het dashboard de uitkomst met en zonder een User Rule naast elkaar
tonen. Dat is uitlegbaarheid/diagnose en mag geen tweede plannerpad worden.

## Herstelervaring en bewakingsgrenzen

Tijdens deze ontwikkellijn ontstonden extreme rekentijd en geheugenproblemen
toen routes en diagnostische gegevens onbegrensd groeiden. Waargenomen gevolgen
waren plannerruns van minuten, een dashboard dat traag of niet laadde en een
OOM-kill met circa 6,4 GB geheugenpiek.

Daaruit volgen blijvende grenzen:

- alle kandidaatverzamelingen, historie en diagnostische buffers zijn begrensd;
- een downloadfunctie mag geen volledige grote historie in het geheugen laden;
- dashboardopbouw mag de planner of ingress-server niet blokkeren;
- prestatie- en geheugentelemetrie blijven zichtbaar per belangrijke fase;
- diagnose-download is een afzonderlijk technisch probleem en mag niet worden
  opgelost door plannerverantwoordelijkheden te vermengen;
- normale plannertijd en stabiel geheugen zijn acceptatiecriteria, niet alleen
  functionele bijzaak.

## DEV.232 — huidige herstelde basis

DEV.232 herstelt de regressie waarbij NOM over geprojecteerde PV een expliciet
exportsegment overschreef en een bestaande marktroute door een andere hybride
ouder werd vervangen.

De nu bedoelde route is zichtbaar als:

- NOM over het volledige Solcast-PV-venster;
- netladen als begrensde overlay;
- marktexport als begrensde overlay;
- terugkeer naar NOM na export wanneer het PV-venster nog actief is;
- aansluitend het normale huishoudpad.

De relevante geautomatiseerde planner-, pipeline-, User Rule- en versietests
zijn voor DEV.232 geslaagd. Live is inmiddels een inhoudelijk correct plan
zichtbaar; de feitelijke uitvoering en schakelmomenten moeten nog door de dag
heen worden beoordeeld.

## Acceptatiecriteria voor vervolgwerk

Een volgende wijziging wordt pas als geslaagd beschouwd wanneer:

1. ADR-001 t/m ADR-037 en de laaggrenzen aantoonbaar behouden blijven;
2. Opportunity Engine alleen kansen levert;
3. Candidate Engine een kleine set complete, uitlegbare paden vormt;
4. MEP de paden begrensd simuleert zonder nieuwe kandidatenexplosie;
5. Evaluation de winnaar selecteert zonder verborgen dwang;
6. User Rules zichtbaar zijn in kandidaat, uitkomst en beslisreden;
7. PV-confidence en actuele PV-afwijking traceerbaar zijn;
8. netladen, export en terugkeer naar NOM live correct schakelen;
9. handelsbudget en huishoudreserve fysiek worden gerespecteerd;
10. plannerduur, dashboardduur en geheugen binnen normale grenzen blijven;
11. een financieel afwijkende keuze met concreet bewijs wordt uitgelegd;
12. regressietests het complete energiepad controleren en niet alleen één los
    kwartier of één dashboardkleur.

## Niet opnieuw doen

- Geen onbevroren of niet-geaccepteerde ADR als normatieve basis gebruiken.
- Geen prijsOpportunity direct naar een commando vertalen.
- Geen drie permanente PV-scenario's per marktroute volledig combineren.
- Geen variant per mogelijk kwartier maken wanneer energie eerst naar één duur
  kan worden omgerekend.
- Geen persoonlijke voorkeur als verborgen universele plannerregel coderen.
- Geen marktroute verwijderen alleen omdat NOM over PV gewenst is.
- Geen bestaand compleet pad stilzwijgend vervangen door een andere ouder.
- Geen diagnose-, dashboard- of downloadprobleem oplossen binnen MEP.
- Geen groene CI als enige bewijs voor live correct gedrag aanmerken.

## Openstaande verificatie

- Werkelijke uitvoering van DEV.232 gedurende het volledige dagpad.
- Exact stoppen van de handels-zandloper op het ingestelde SoC-budget.
- Werkelijke laadvoortgang en het tijdig verwijderen/toevoegen van netondersteuning.
- Bereiken van de gewenste hoge/100% SoC bij voldoende PV.
- Financiële vergelijking met en zonder energiebelastingverrekening.
- Robuuste diagnose-download zonder planner-, dashboard- of geheugenregressie.
- Latere toepassing van hetzelfde begrensde tijdlijnprincipe op EV, wasmachine
  en droger via hun eigen canonieke contracten.
