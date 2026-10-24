# CV-plannen gekoppeld aan HC en HEMS

Deze wijziging verbindt de drie eerder open CV-onderdelen: een gezamenlijke vergelijkingsbasis, een raming voor handhaven en de uitvoering van een gekozen CV-plan. Werkbasis: de volledige geïntegreerde dev.314-boom. De nachtreparatie is AST-identiek aan de live releasebasis gebleven. Geen commit, push, release of live aansturing uitgevoerd.

## Van waarneming naar vergelijkbare plannen

`CvMaintenance` verzamelt afzonderlijke perioden van minimaal twintig minuten waarin HC zelf bevestigd via de CV verwarmt, beneden stabiel rond het doel blijft en de gasrapportage de periode dekt. De gegevens staan in een aparte SQLite-tabel. Onderbrekingen, een andere opdracht/schemaherziening, temperatuurdrift, tellerproblemen, ontbrekende aannames en herstarts onderbreken de lopende periode. Afgeronde perioden krijgen dezelfde onafhankelijke controle op vertraagd warmwatergebruik als opwarmbeurten. Drie passende, definitief gecontroleerde perioden zijn nodig voor een raming. Een nul of ontbrekende gasdelta geldt niet als bewijs van gratis warmte.

De gemeten aircolast en het geschatte ketelvermogen blijven verschillende gegevens. `LoadReview` houdt toeschrijving van de geschatte ketellast eerst 90 seconden vast. Een in die tijd ontvangen DHW-melding houdt de betrokken last, inclusief aan warmwater toegeschreven naloop, buiten het vervangbare verwarmingsdeel. Onbekende dekking blijft onbekend. Het resultaat is nog steeds een model: een volledig tussen pollmomenten vallende DHW-puls kan niet worden bewezen of uitgesloten.

HEMS bewaart de controles als aanvullende metadata bij de fysieke huishistorie. Bij herladen worden alleen de optionele toeschrijvingen aangevuld; totaalvermogen, EV en gemeten aircopower worden niet overschreven. Herhaalde controles worden tijdens registratie ontdubbeld. Schrijven en deze ontdubbeling zijn geserialiseerd. De gezamenlijke prognose gebruikt dezelfde historische meetpunten en gewichten als de bestaande prognose. Alleen gemeten aircolast plus het gecontroleerde, geschatte vervangbare deel komen in de vervangingsbasis. Het overige ketelverbruik blijft onderdeel van de restvraag.

Een gezamenlijke basis wordt pas aangeboden als de historische dekking compleet is. Hij bevat een generieke modelidentiteit die HC expliciet moet bevestigen. Oude of niet-passende voorstellen worden geblokkeerd. Een vastgelegd plan mag bij latere prognoses alleen dezelfde bron- en modelidentiteit vervangen. Bij ontbrekende/gewijzigde toeschrijving blijft de bestaande conservatieve verwerking gelden: geen onbewezen aftrek.

## Voorstellen en uitvoering

HC kan in één batch maximaal vijf starttijdplannen aanbieden: maximaal twee aircoplannen en drie CV-plannen zodra beide routes onderbouwd zijn. Als de CV nog niet onderbouwd is, blijven de ondersteunde airco-alternatieven beschikbaar. Een CV-plan vereist dekking tot het einde van het comfortvenster. De mogelijke ramingshorizon is verruimd tot vijftien uur, zodat ook een weekendvenster kan worden meegenomen. De bestaande aircoroute kan bij een kortere beschikbare HEMS-horizon nog een begrensd deelvenster aanbieden.

Een CV-plan omvat gemeten aircostandby, geschatte CV-opwarming, handhaven en een eenmalige naloopreserve. De toekomstige naloopreserve wordt conservatief in het laatste verwarmingsslot geboekt; het werkelijke stopmoment is niet gemeten. Eventuele reeds lopende naloop telt alleen vanaf het begin van het nieuwe plan en, bij een nieuwe CV-start, tot die start. Eerder verbruik staat al in de bestaande prognose. Gas wordt als niet-elektrische kosten doorgegeven. HEMS en MEP ontvangen geen thermostaat-, CV- of DHW-regels: alleen generieke profielen, kosten en bronidentiteiten.

Een nieuwe CV-start vereist geldig gastarief, passende meetonderbouwing, een beschikbare bron, geen bekend actief warmwatergebruik en de actuele exacte HEMS-starttoestemming. Een boven al door HC aangestuurde overlappende bron is een uitvoeringsconflict; de temperatuur boven bepaalt de CV-raming of keuze niet. De bestaande controle na verse HA-uitlezing, opslag vóór dispatch, opdrachtbevestiging en minimum-uitduur blijven van toepassing.

Het startvoornemen bewaart nu ook de gekozen bron. Bij herbeoordeling blijft de vastgelegde starttijd en bron behouden. Reservering en uitvoeringsbevestiging gebruiken de juiste bron. Verlopen starttoestemming onderbreekt een al gestarte verwarming niet. Bij een plan voor het volledige comfortvenster blijft de gekozen bron dat venster verzorgen; het bestaande afbouwgedrag binnen comfortgrenzen blijft mogelijk. Een schemawijziging of handmatige bediening houdt voorrang. De interface toont airco/CV bij de voorstellen en keuze, plus de afzonderlijke CV-opwarm- en handhaaframingen.

## Grenzen van deze oplevering

- CV-gas en elektrisch hulpverbruik blijven expliciete ramingen. De instelling voor geschat hulpverbruik moet beschikbaar zijn; een foutieve aparte meter wordt niet stilzwijgend vervangen door een schatting. De voorlopige waarden 100 W bedrijf, 50 W naloop en 300 seconden zijn geen gecontroleerde ketelspecificaties.
- Oude historie zonder de nieuwe gecontroleerde toeschrijving levert niet vanzelf een gezamenlijke basis op. Normale comfortregeling blijft tijdens het verzamelen beschikbaar.
- HEMS beoordeelt kosten en haalbaarheid bij de bestaande batterijroute. Extra laden per alternatief optimaliseren is nog niet geïmplementeerd.
- Wind en bewolking zijn nog geen invoer voor de thermische leermodellen. De gebruikte binnen-/buitentemperatuur en empirische marges geven geen garantie voor veranderend weer over een lang venster.

De CV-keten is hiermee verbonden, maar bovenstaande twee grotere optimalisatiewensen zijn nog open. Er is geen volledige releasegereedheid voor alle wensen uit de oorspronkelijke chat geclaimd.

## Bewijs

Gerichte tests gebruiken echte CV-registratie, SQLite-opslag, JSONL-historie, de planning-inputassembler en de gewone HC-controller. De nieuwe uitvoeringstest biedt CV-plannen aan, verwerkt de HEMS-keuze, vernieuwt de toestemming voor dezelfde start, start precies eenmaal en houdt de CV tijdens comfort aan nadat de toestemming verlopen is. Alleen de HA-transportgrens wordt nagebootst.

Daarnaast zijn vertraagd DHW, ontbrekende dekking, volledige comfortduur, gasprijs, naloop, behoud van warmwater/restvraag, gewijzigde modelidentiteit, reservering na herstart en de dev.314-regressies gecontroleerd. Ruff en JavaScript-syntaxcontroles zijn uitgevoerd. Geen echte HA-/woningproef, browserinteractie of volledige repositorybrede typecheck uitgevoerd. De definitieve gecombineerde testuitslag staat hieronder.


### Definitieve verificatie, 24 oktober 2026

- Gecombineerde HC/HEMS- en dev.314-regressiereeks: **482 tests en 13 subtests geslaagd**, 370,59 seconden, exitcode 0. Inclusief de begrenzing van de controlepublicatie bij iedere vijf seconden pollen.
- Ruff-controle van de laatst gewijzigde historietest: geslaagd na importordening en formattering. Eerder uitgevoerde gerichte lint- en JavaScript-syntaxcontroles blijven van toepassing.
- Alle manifestbestanden aanwezig; 70 Python-bestanden syntactisch geparseerd.
- AST van `_restore_daily_charge_context` opnieuw vergeleken met dev.314: identiek.
- Geen commit, push, release of live apparaatbediening uitgevoerd. De hierboven genoemde open optimalisaties en ontbrekende woningproef blijven gelden.


### Vervolg

De volgende wijziging voegt weerleren op waarnemingen en een begrensde extra-laadvergelijking via de gewone planner toe. Zie 2026-10-24-hc-recharge-and-weather.md voor de actuele mogelijkheden, 520 geslaagde tests en de resterende grenzen.
