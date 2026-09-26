# Changelog

## 2.0.0-dev.273

- Financiële historie en bestaande totalen blijven zichtbaar als het resultaat van de huidige dag onvolledig is.
- Netinkoop, teruglevering en het gezamenlijke energieresultaat worden afzonderlijk getoond zodra hun eigen metingen en prijzen compleet zijn.
- Ontbrekende batterij- en PicoT-voordelen blijven onbekend. Het tabblad toont welke bronnen en meetperioden ontbreken en hoeveel dagen meetellen in de totalen.
- De oorspronkelijke numerieke historie en voorraadkosten voor planning blijven behouden; ontbrekende metingen worden niet ingevuld.

## 2.0.0-dev.272

- Bij herplanning tijdens beschermd netladen biedt PicoT behoud en ononderbroken verlenging van het laadblok aan, ook als latere PV op papier het dagdoel kan halen.
- Herstelt de kandidaatuitputting achter de onderbreking rond 15:25 op 26 september. De replay kiest nu doorladen; de bestaande financiële selectie bepaalt de beste geldige optie.
- De schakelhistorie toont de werkelijke uitvoeringsreden. De afzonderlijke plankeuzereden blijft beschikbaar in de diagnose.
- Het 100%-dagdoel, andere beschermde intervallen en de bestaande financiële regels blijven gelden. Het financiële tabblad volgt als afzonderlijk herstelpunt.

## 2.0.0-dev.271

- Herstelt de NOM-terugval bij overbrugging: omzetting van export naar NOM wist ook het exportdoel.
- Bestaande marktroutes kunnen bij een toegelaten herplanning behouden, ingekort of verwijderd worden, met aanvullend laden als dat voordeliger is.
- Financiële selectie vergelijkt de resterende uren van vandaag én morgen, inclusief laadkosten, ingestelde slijtage en gelijkwaardige eindvoorraad. Dagdoelen, reserve en bescherming van lopend laden blijven vereist.
- Ontbrekende prijzen, prognosedekking of een nog ongebonden dagdoel leveren geen fictief financieel voordeel op; een geldige uitvoering en toegelaten laadreparatie blijven mogelijk.
- Dashboard en diagnose tonen de financiële alternatieven en afwijsredenen. Geselecteerde revisies bewaren het oorspronkelijke dagbudget en de uitvoeringshistorie, ook na herstart.
- Het afzonderlijke onderzoek naar de schakelingen rond 15:25–15:31 is geen onderdeel van deze release. Dev.268 blijft de afgesproken eerste terugvalbasis.

## 2.0.0-dev.270

- Herstelt een plannercrash na voltooiing van het dagdoel bij een gecombineerd laad- en marktplan zonder bekende volgende hoofdlaadsessie.
- De overbruggingscontrole volgt de bewaarde laadherkomst; bestaande plannen en voltooide dagdoelen blijven behouden.
- Ontbrekende herkomst wordt expliciet gemeld zonder StopIteration-crash. Laadbeleid, prijsselectie en PV-terugval blijven ongewijzigd.

## 2.0.0-dev.269

- Bij ontbrekende actuele PV kan vijf minuten betrouwbaar Shelly- en batterijbewijs een vermindering van netladen laten beoordelen.
- Het 100%-dagdoel, de reserve en de bestaande volledige MEP-planvergelijking blijven vereist; vrijgekomen laadintervallen worden NOM.
- Ontbrekende PV blijft onbekend. Ongeldige of verouderde bronnen en actieve belastingbescherming blokkeren de terugval.
- Diagnose bevat het onafhankelijke netbalansbewijs en de revisiereden. Dev.268 is de eerste terugvalbasis.

## 2.0.0-dev.268

- Afgewezen huisverbruiksmetingen krijgen een aparte registratie met bronwaarden, brontijden en afwijsreden in de diagnose-download.
- Registratie begrensd op 16 MiB; bestaande gegevens blijven behouden en opslagfouten blokkeren de regeling niet.
- Geldige meetwaarden, plannerregels en batterijaansturing blijven ongewijzigd.

## 2.0.0-dev.267

- Herstelt uitvoering van geplande standby-opdrachten via de Zendure-moduskoppeling.
- Plannerregels, laadplanning en handmatige overrides blijven ongewijzigd.

## 2.0.0-dev.266

- Nieuwe diagnose- en proefrecords behouden de oorspronkelijke tijdzone-offset voor reproduceerbare historische ID’s.
- Wijzigingsdetectie blijft UTC gebruiken; plannerregels en aansturing blijven gelijk.
- Bestaande archieven blijven behouden. Laat `history_capture_trial_enabled` op `false` staan.

## 2.0.0-dev.265

- Diagnose-download bevat nu de bewaarde snapshotproefobjecten en een exportmanifest.
- Export is begrensd op 16 MiB en 64 objecten; opgeslagen gegevens blijven behouden.
- Laat `history_capture_trial_enabled` op `false` staan bij installatie en download daarna één nieuwe diagnose-ZIP. Een nieuwe opnameproef is niet nodig.

## 2.0.0-dev.264

- Begrensde praktijkproef voor volledige snapshots, standaard uit (`history_capture_trial_enabled: false`).
- Na inschakelen maximaal 30 minuten nieuwe opnamen; begrensde wachtrij en eigen opslag. Opname stopt bij een schrijffout.
- Compacte logregels met looptijd, CPU, geheugen en opgeslagen/gemiste records, ook voor de baseline met opname uit.
- Geen automatische indexverwerking of verwijdering; plannerregels, MEP en batterijaansturing blijven ongewijzigd.
- Start de praktijkproef met 30 minuten opname uit. Inschakelen vereist een appherstart.

## 2.0.0-dev.263

- Nacontrole integreert vermogens over gelijke klokkwartieren en toont apart het afgeleide huisverbruik.
- Volledige kwartierwaarden in de meetarchieven; samenvatting en ongeldige tijdvakken in het dashboard.
- Bronuitval en negatieve energiebalansen blijven ongeldig. Afgeleide waarden zijn geen sluitend bewijs van besparing.
- Geen wijzigingen aan MEP-planning, commitmentregels of batterijaansturing.

## 2.0.0-dev.262

- Nacontrole haalt meetgeschiedenis in begrensde stukken op en daarna alleen nieuwe gegevens; mislukte aanvragen worden opnieuw geprobeerd.
- Ruwe meetreeksen van vandaag en gisteren worden bewaard en meegenomen in de diagnose-download.
- Meetonderbrekingen tonen de sensor en het exacte tijdvak. Ontbrekende waarden blijven ontbrekend.
- Geen wijzigingen aan MEP-planning, commitmentregels of batterijaansturing.

## 2.0.0-dev.261

- Schakelhistorie ververst direct bij klokschakelingen, ook zonder nieuwe planningsrun.
- Een vervallen eigen netlaadsegment blijft NOM in de revisiekandidaat.
- Gele SOC-verwachting wordt vanuit actuele SOC vernieuwd voor het geldende plan; verstreken voorspellingen blijven behouden en planwissels krijgen een markering.
- Paarse SOC-lijn blijft meetgeschiedenis; ontbrekende actuele prognose-invoer wist alleen de toekomst.
- Onbekende confidence verschijnt als — in plaats van 0%.
- Dagdoel, reserve, belastingbescherming en uitvoeringsautoriteit blijven gelden. Dev.254 blijft terugvalbasis.

## 2.0.0-dev.260

- Herplanning vereist Monitor-vrijgave; segmentklok en planbehoud blijven afzonderlijk herleidbaar.
- Bestaand dagplan en vervangers worden vanuit dezelfde actuele snapshot vergeleken; bij gelijke kosten krijgt minder netlaadduur voorrang.
- SOC-bronidentiteit, uitvoeringsgrenzen, dispatchfouten en begrensde selectorfeedback hersteld.
- Tegel 5 verklaart planbehoud en blokkades; diagnostiek bewaart volledige uitvoeringssnapshots en evaluatiebewijs.
- Externe Gielz- en recorderconfiguratie worden niet door deze add-on aangepast; zie docs/development_log/2026-09-14-ha-followup.md.
- Dagdoel, minimumreserve en belastingbescherming blijven gelden. Dev.254 blijft terugvalbasis.

## 2.0.0-dev.259

- Voorkomt afwijzing van behouden marktroutes door een negatieve afrondingsrest; echte ongeldige energietoewijzingen blijven afgewezen.
- Behoudt de laatste werkelijke SOC-historie bij een tijdelijke ophaalfout, met zichtbare verouderingsmelding en ongewijzigd meeteindpunt.
- Begrensde PicoT-sensorattributen voor Home Assistant Recorder; volledige details blijven in dashboard en diagnostiek.
- Planningsregels ongewijzigd. Dev.254 blijft de afgesproken pre-stable terugvalbasis.

## 2.0.0-dev.258

- Houdt aanhoudende extra huisbelasting tijdelijk bij in de prognose voor alle laadkandidaten.
- Beschermt lopend netladen tegen korte onderbrekingen zolang de belasting aanhoudt; vrijgave bij verdwenen belasting, werkelijk 100% SOC of het bestaande blokeinde.
- Kleine SOC-tekorten mogen alleen wachten wanneer tijdig herstel tot werkelijk 100% aantoonbaar haalbaar blijft. Reserve en dagdoel blijven verplicht.
- Diagnose bevat de belastingbescherming. Vaste klokkwartieren blijven behouden; dev.254 blijft pre-stable en terugvalbasis.

Na installatie: observeer langdurige belasting, vrijgave na afloop en werkelijk afvinken van het dagdoel.

## 2.0.0-dev.257

- Zet het verstreken SOC-lijnverloop vast op het tijdstip van een nieuwe prognose. Een gewijzigd start-SOC trekt de historische lijn niet meer mee.
- Begint de nieuwe verwachting afzonderlijk en tekent geen verbinding over een periode zonder prognose.
- Bewaart de lijnsecties en bronverwijzingen na herstart; vergroot de begrensde cache voor de extra snijpunten.
- Alleen SOC-weergave gewijzigd. MEP en aansturing blijven ongewijzigd; dev.254 blijft de vaste pre-stable terugvalbasis.

Na installatie: controleer dev.257 en vergelijk hetzelfde verstreken tijdstip vóór en na een nieuwe prognose.

## 2.0.0-dev.256

- Bewaart verstreken SOC-prognosepunten naast de werkelijke SOC; alleen de toekomstige verwachting wordt vervangen. Prognosehistorie blijft bewaard na herstart.
- Verduidelijkt de legenda: SOC-prognose (historie + actuele verwachting).
- Voorkomt een losse herstelmelding wanneer Home Assistant de voorafgaande storingsmelding niet heeft ontvangen, bijvoorbeeld tijdens een herstart.
- MEP en de klokkwartierproef blijven ongewijzigd. Dev.254 blijft de vaste pre-stable terugvalbasis.

Na installatie: controleer dev.256 en of verstreken prognosepunten bij updates blijven staan.

## 2.0.0-dev.255

- Gebruikt vaste klokkwartieren voor historische huisvraag, zodat alleen een verschoven polltijd de toekomstige verbruiksverwachting niet verandert.
- Rekent gedeeltelijke begin- en eindkwartieren evenredig mee. Dagdoel, reserve, prijsselectie en actuele invoer blijven van kracht.
- Begrensde observatieproef: dev.254 blijft de vaste pre-stable terugvalbasis. Bij slechter gedrag direct terug; maximaal één kleine optimalisatie als het gedrag niet slechter is. Daarna bij onvoldoende resultaat terug en opnieuw ontwerpen.

## 2.0.0-dev.254

- Toont de geplande SOC als doorgetrokken lijn met behoud van de moduskleuren.
- Geeft de werkelijke SOC een vaste paarse kleur, inclusief legenda. Ontbrekende metingen blijven zichtbaar als onderbreking.
- Alleen weergave gewijzigd; SOC-gegevens, planning en aansturing blijven ongewijzigd.

Na installatie: controleer dev.254 en de SOC-lijnen in de prijsgrafiek.

## 2.0.0-dev.253

- Neemt de oorspronkelijke marktroute mee in de ongearceerde planreferentie. De eerste handel geldt niet meer ten onrechte als een latere optimalisatie.
- Herstelt de oorspronkelijke handelssegmenten via hun bewaarde bronverwijzingen, ook na planrevisies en herstart. Latere laadwijzigingen worden niet in de oorspronkelijke referentie overgenomen.
- Alleen latere afwijkingen van het volledige oorspronkelijke plan krijgen arcering. MEP en aansturing blijven ongewijzigd.

Na installatie: controleer dev.253 en of oorspronkelijke handel ongearceerd is.

## 2.0.0-dev.252

- Corrigeert arcering: alleen afwijkende delen ten opzichte van het eerste vastgelegde dagplan worden gearceerd. Ongewijzigde delen blijven zonder arcering, ook bij een nieuwe planrevisie.
- Herstelt de oorspronkelijke referentie uit de bestaande planhistorie na herstart. Ontbrekende referentie wordt expliciet gemeld.
- Toont het kostenverschil bij minder netladen boven de terugbliktabel onder Financieel, met datum en status of de reden waarom nog geen bedrag beschikbaar is.
- MEP, financiële rekenregels en aansturing blijven ongewijzigd.

Na installatie: controleer dev.252, de arcering bij aangepaste plandelen en Financieel > Terugblik netladen.

## 2.0.0-dev.251

- Voegt een passieve dagelijkse terugblik op netladen toe: modelmatig vermijdbare kWh, kostenverschil en afwijking van de vastgelegde PV-verwachting. De berekening behoudt batterij-export, het hoofdlaaddoel en de eindvoorraad; onvolledige meetdagen tellen niet mee in de trend.
- Toont de werkelijke SOC als groene traplijn naast de gestreepte oorspronkelijke prognose in de prijsgrafiek. Ontbrekende metingen blijven zichtbaar als onderbreking.
- Arceert de prijsbalken precies binnen gekozen NOM-, netlaad- en handelssegmenten, inclusief gedeeltelijke kwartieren.
- Bewaart de terugblik over herstarts en voegt de gegevens toe aan de diagnose-download. MEP, evaluatie en aansturing blijven ongewijzigd.

Na installatie: controleer dev.251, de twee SOC-lijnen en arcering. Onder Financieel verschijnt de terugblik; de lopende dag is voorlopig. Dit is een modelschatting met voorkennis en geen automatisch gewijzigd laadbeleid. Browser- en livecontrole volgen na installatie.

## 2.0.0-dev.250

- Beoordeelt vermindering van netladen ook bij een hogere actuele SOC wanneer de gemeten PV niet boven CENTRAL ligt.
- Vermindert uitsluitend via de bestaande planning, met behoud van het laaddoel en controle van de overige hoofdopdrachten.
- Een gewijzigde SOC kan dezelfde PV-metingen opnieuw relevant maken; identieke herhaalde metingen starten geen nieuwe prijszoektocht.

Na installatie: controleer versie dev.250 en of netladen bij voldoende verwachte energie wordt verminderd.

## 2.0.0-dev.249

- Bewaart de oorspronkelijke SOC-prognose bij het plan, zodat de lijn na een herstart terugkomt bij hetzelfde behouden plan.
- Kan voor bestaande installaties de oorspronkelijke prognose eenmalig uit de diagnosehistorie herstellen, uitsluitend bij overeenkomende plan- en energiepadidentiteit.
- Het oorspronkelijke berekenmoment blijft zichtbaar. Een prognose van een ander plan of een verlopen prognose wordt niet overgenomen.

Na installatie: controleer de SOC-lijn en het oorspronkelijke berekenmoment. De planningslogica blijft ongewijzigd.

## 2.0.0-dev.248

- Herstelt de onterechte melding `daily_reference_household_horizon_incomplete` bij handelssegmenten met tijdgrenzen op fracties van seconden.
- De prognosedekking wordt met exacte tijdsduren gecontroleerd. Afrondingsverschillen veroorzaken hierdoor geen onnodige terugval naar NOM; echte gaten blijven afgewezen.

Na installatie: controleer dev.248 en of NOM- en marktvensters over opeenvolgende berekeningen behouden blijven zonder deze foutmelding.

## 2.0.0-dev.247

- Herkent een historisch gemeten SOC van 100% tijdens het toen geldige hoofdlaadvenster, ook als PicoT op dat moment niet draaide. Het bewijs en de oorspronkelijke laadopdracht blijven bewaard.
- Beoordeelt overbodige herstel-laadsegmenten opnieuw via de canonieke planner. Een achterhaald hoofdlaadsegment wordt niet uitgevoerd terwijl die herbeoordeling nog loopt.
- Gebruikt dezelfde tariefgrenzen bij de berekening van handelscapaciteit en exportsimulatie. Dit voorkomt onterechte afwijzing door een verschil tussen gevraagd en berekend exportvolume.
- Spreadvoorwaarden blijven van toepassing; een groot prijsverschil alleen garandeert geen uitvoerbare marktroute.

Na installatie: controleer dev.247, de historische SOC-herkenning en de nieuwe marktberekening. Werking in Home Assistant moet live worden bevestigd.

## 2.0.0-dev.246

- Verhelpt de StopIteration-crash in de marktplanner bij verschoven tijdgrenzen van de huisverbruiksvoorspelling.
- De exportsimulatie wordt gesplitst op de tariefgrenzen, zodat ieder exportdeel een passend tarief krijgt.
- Een ontbrekende prijsmatch wijst de handelskandidaat af met een expliciete reden. Er wordt geen prijs verzonnen of gedeeltelijke kandidaat gepubliceerd.
- Dagelijkse laadopdrachten, handelsvolume en spreadregels blijven behouden.

Na installatie: controleer dev.246 en of de planner zonder crash blijft draaien. Livewerking moet in Home Assistant worden bevestigd.

## 2.0.0-dev.245

- Het behouden laadplan blijft zichtbaar, inclusief het oorspronkelijke NOM-venster en de planidentiteit.
- Bij hetzelfde behouden plan blijft de oorspronkelijke SOC-prognose zichtbaar met het berekenmoment. Na een herstart zonder eerdere prognose blijven de laadvensters zichtbaar; er wordt geen SOC-lijn verzonnen.
- De marktroute kan alle gepubliceerde dagprijzen gebruiken voor haar fictieve laadreferentie, inclusief verstreken kwartieren. Uitvoerbare acties blijven in het resterende tijdvenster.
- Echte gaten in de prijspublicatie blijven de marktvergelijking blokkeren.

De afspraken voor dagelijks laden, optimalisatie en optionele herstelbaarheid blijven ongewijzigd. Na installatie: controleer dev.245, het behouden NOM-venster en de marktroute. Werking in Home Assistant moet live worden bevestigd.

## 2.0.0-dev.244

Ontwikkelrelease voor de gezamenlijke liveproef van de dagelijkse laadcyclus en de user-rule-marktroute.

- Dagelijkse laadopdracht met eigen identiteit en 100%-doel; PV-, hybride en netlaadsegmenten blijven bij dezelfde opdracht horen.
- Aanvullende laadopdrachten behouden hun eigen doel en voltooiing.
- Marktvolume en minimumspread instelbaar in de strategiepagina; maximaal één handelsopdracht per regel per leveringsdag.
- Optionele herstel-/nettowinsttoets, standaard uit. Een lege minimumspread schakelt nieuwe handel uit.
- Bestaande laad- en handelsvensters blijven behouden tijdens optimalisatie en herstart.
- Stopbewaking gebruikt actuele SOC, het handelsvenster, gemeten export en werkelijke modusterugmelding. Meetgaten leveren geen verzonnen volume op.
- Minder herhaalde laadberekeningen. Tijdens marktberekeningen komt de bestaande uitvoeringsbewaking tussentijds aan bod; vóór uitvoering wordt nieuwe input ingelezen.

Na installeren: controleer dev.244 in PicoT en vul de gewenste handelsfractie en minimumspread in. Herstel kan voor de eerste proef uit blijven. Bestaande instellingen en historische diagnostiek blijven bewaard.

Dit is een ontwikkelrelease: lokale controles zijn uitgevoerd; werking met de echte HA-meethistorie en modusfeedback wordt in de gezamenlijke liveproef beoordeeld.
