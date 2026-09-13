# PicoT Home Climate — ADR’s en ontwerp eerste versie

13 september 2026. Afkorting: PicoT HC.

Deze versie vervangt de startnotitie en verwerkt de verdere afspraken in dit gesprek. De ADR-reeks is onafhankelijk van PicoT HEMS. De besluiten hieronder zijn in het gesprek bevestigd. De observatiebasis is gebouwd en lokaal getest. Bediening en planning zijn ontwerp en nog niet geïmplementeerd. Live HA-validatie staat open.

Actuele implementatie: dev.8-bronbediening en terugkoppeling zijn door de gebruiker
live bevestigd. Dev.9 voegt het opt-in basisschema toe volgens HC-ADR-013.
Dev.10 corrigeert dit naar bronvrije comfortvensters volgens HC-ADR-014;
het schema levert comfortvraag en deadlines, geen directe bronopdrachten.
De historische oplevervolgorde hieronder blijft richtinggevend voor prijsoptimalisatie.

## Korte ADR’s

### HC-ADR-001 — Volledig binnenklimaat

**Besluit:** HC omvat verwarmen, later koelen en luchtkwaliteit, waaronder CO₂ en luchtvochtigheid. Verwarmen en het beoordelen van vocht boven vormen de eerste functionele basis.

**Gevolg:** Dezelfde zones en apparaatkoppelingen ondersteunen meerdere functies. Actieve ontvochtiging wordt eerst beproefd; algemene koeloptimalisatie volgt later.

### HC-ADR-002 — Drie zones

**Besluit:** Beneden, boven/slaapkamer en badkamer krijgen eigen metingen, comfortinstellingen en thermisch gedrag. Cv bedient beneden en boven gezamenlijk. De badkamer heeft directe elektrische verwarming en geen cv.

**Gevolg:** Cv-besluiten wegen beide bediende zones mee. Indirecte warmte en luchtuitwisseling worden apart beschreven. Afzonderlijke cv-zoneregeling mag niet worden aangenomen.

### HC-ADR-003 — Prijsoptimalisatie binnen comfortgrenzen

**Besluit:** HC optimaliseert verwarmingsmoment en warmtebron op prijzen, binnen instelbare comfortgrenzen. Het heeft eigen prijsgegevens, prijsgrafiek, planning en kostenberekening.

**Gevolg:** Eerder verwarmen is alleen zinvol als het voordeel opweegt tegen extra warmteverlies. Vergelijk airco, cv en relevante combinaties met onderbouwde efficiëntieaannames. Toon onzekerheid; geen vaste temperatuurwaarden in code.

### HC-ADR-004 — Woninggedrag leren

**Besluit:** Leer opwarming, afkoeling en warmteverlies per zone uit temperatuur, ΔT met buiten, apparaatgedrag en energieverbruik.

**Gevolg:** De badkamer boven de uitstekende garage heeft een eigen verliesprofiel door dak, slecht geïsoleerde buitenmuur en groot raam. Warmte vanuit cv/airco boven is volgens gebruiker beperkt. Gelijktijdige bronnen, douchen en open deuren beïnvloeden metingen. Elektriciteitsmeting alleen bewijst geen COP. Warmte bufferen en kosten bij één graad warmer/kouder volgen met een bruikbaar model.

### HC-ADR-005 — Klimaatfuncties afstemmen

**Besluit:** Verwarmen, ontvochtigen, later koelen en ventilatie worden afgestemd zodat functies elkaar niet onbedoeld tegenwerken.

**Gevolg:** Mechanische ventilatie in de badkamer draait continu; de deur staat doorgaans open. Boven en badkamer wisselen lucht en vocht uit. Debiet en regelbaarheid zijn niet vastgesteld. Verwarmen beïnvloedt relatieve vochtigheid zonder zelf vocht af te voeren; airco-ontvochtiging kan afkoelen. Temperatuur- én vochtgrenzen tellen mee.

### HC-ADR-006 — Volledig zelfstandig

**Besluit:** HC functioneert volledig zonder PicoT HEMS. Een eventuele latere koppeling communiceert in twee richtingen.

**Gevolg:** Geen HEMS-planner, batterijstatus of HEMS-service als vereiste. Eigen configuratie, opslag, dashboard en planning. Inhoud, bevoegdheden en foutgedrag van de toekomstige koppeling worden later besloten.

### HC-ADR-007 — Beneden: aanwezigheid en schema

**Besluit:** Beneden combineert aanwezigheid met een instelbaar basisschema en temperaturen voor thuis, afwezig en slapen.

**Gevolg:** Voorlopig is de iPhone-app de aanwezigheidsbron. UniFi loopt alleen ter observatie. Onbekend/onbeschikbaar betekent niet afwezig. Vertrekvertraging en een handmatige gast-/aanwezigheidskeuze horen bij de instellingen.

### HC-ADR-008 — Boven: temperatuur en vocht

**Besluit:** Boven vereist geen schema. Gewenste en minimale temperatuur zijn instelbaar. De gewenste relatieve vochtband is aanvankelijk 40–60%, met 50% als streefwaarde. Ook deze waarden zijn instelbaar.

**Gevolg:** Binnen de band hoeft HC niet naar exact 50% te regelen. Aanhoudende overschrijding vraagt beoordeling; onder de ondergrens stopt actieve ontvochtiging. Duur en temperatuur bepalen de reactie. Een korte douchepiek leidt niet direct tot schakelen. Klam beddengoed is een comfortwaarneming; de oorzaak is nog niet gemeten.

### HC-ADR-009 — Badkamer: tijdelijk comfort

**Besluit:** Huidig gebruik is elektrisch verwarmen rond douchen. Een knop voor een tijdelijk verwarmvenster is het voorlopige bedieningsontwerp, met instelbaar doel en maximale duur.

**Gevolg:** Geen cv of slaapkamerairco starten uitsluitend voor de badkamer. Indirecte warmte telt mee als beperkte bijdrage. Alleen bij gebruik, voorverwarmen of een basistemperatuur aanhouden blijven te vergelijken strategieën.

### HC-ADR-010 — Meting en opdracht onderscheiden

**Besluit:** Bewaar gewenste actie, verzonden opdracht en gemelde apparaatstatus afzonderlijk, met tijdstippen en gegevenskwaliteit.

**Gevolg:** Cv-terugmelding is vertraagd; de betekenis van de statussensor moet nog worden vastgesteld. Een oude status veroorzaakt geen directe herhaalopdracht. Onbekende waarden zijn geen nulmetingen. Handmatige bediening moet herkenbaar blijven en mag niet telkens worden overschreven.

### HC-ADR-011 — Distributie via bestaande repository

**Besluit:** HC wordt een afzonderlijke HA-app in `Brons1981/PicoT-HEMS`, zoals Energy Devices. De gebruiker heeft deze route bevestigd nadat een afzonderlijke repository eerder niet zichtbaar werd in HA.

**Gevolg:** Eigen map `picot_hc/`, manifest, container, versie, configuratie, opslag en Ingress-paneel. Alleen distributie wordt gedeeld. HC-ADR-006 blijft gelden; er is geen afhankelijkheid van HEMS of wijziging aan de canonieke HEMS-planning. De toekomstige koppeling vereist een afzonderlijk besluit.

## Ontwerp eerste versie

### Oplevervolgorde

1. **Fundament en observatie:** zelfstandige HA-koppeling, configuratie, duurzame meetregistratie, eigen prijsgrafiek en dashboard. Leest werkelijke gegevens; nog geen autonome klimaatopdrachten.
2. **Gerichte bediening en metingen:** met de nieuwe sensoren bron voor bron opdrachten, terugmeldingen, opwarming en afkoeling controleren. Midea-ontvochtiging beproeven. Geen vaste wachttijd in dagen: voldoende bruikbare waarnemingen zijn bepalend.
3. **Advies en prijsplanning:** uitvoerbare opties vergelijken en verwacht comfortverloop en kosten uitleggen. Ontbrekende kennis blijft zichtbaar.
4. **Automatische regeling:** per zone activeren wanneer metingen, bediening en stopgedrag zijn gecontroleerd. De badkamerknop kan als begrensde bediening eerder worden beproefd.

Prijsoptimalisatie is het productdoel. De eerste oplevering levert de meetbasis en presenteert nog geen onbewezen optimale planning.

### Onderdelen

| Onderdeel | Verantwoordelijkheid |
| --- | --- |
| HA-koppeling | Entiteiten/attributen lezen, beschikbaarheid volgen, gecontroleerde opdrachten verzenden |
| Configuratie | Zones, bronnen, entiteiten, comfortinstellingen, tarieven en schema’s |
| Meetopslag | Waarnemingen, bron-/ontvangsttijd, eenheden, kwaliteit, opdrachten en wijzigingen bewaren |
| Woningmodel | Opwarming, verliezen en uitwisseling per zone ramen met zichtbare onzekerheid |
| Planner | Comfortvraag vertalen naar bronkeuze en vensters met eigen prijsgegevens |
| Uitvoering | Geldigheid controleren, opdrachten bewaken en handmatige bediening respecteren |
| Dashboard | Actuele en gewenste toestand, prijzen, plan en verklaringen tonen |

Broncapaciteiten worden expliciet vastgelegd: Mitsubishi beneden, Midea boven, cv beneden én boven, elektrische verwarming badkamer. Gezamenlijk cv-verbruik mag niet dubbel worden geteld of zonder onderbouwing volledig aan één zone worden toegeschreven.

### Eerste dashboard

- **Overzicht:** drie zonekaarten met temperatuur, vocht indien beschikbaar, ingestelde grenzen en gemelde activiteit. Bij een HC-advies of actie staat een reden. Ontbrekende/verouderde metingen zijn zichtbaar.
- **Eigen prijsgrafiek:** beschikbare elektriciteitsprijzen met werkelijke tijdvakken en tijdzone; ontbrekende intervallen blijven leeg. Later geplande warmtevensters eronder. Gasprijs apart zichtbaar.
- **Zoneweergave:** temperatuur- en vochtverloop, beschikbare vermogens-/energiegegevens, bronactiviteit en instellingen. Beneden met schema/aanwezigheid, boven zonder verplicht schema.
- **Badkamer:** voorlopig start/stop van tijdelijk verwarmen, doel, resterende duur en gemeld vermogen.
- **Verbindingen:** entiteiten, meest recente ontvangst, ontbrekende sensoren, vertraagde bevestigingen en meetkwaliteit.

Gebruik duidelijke uitleg zoals “Geen advies: buitentemperatuur ontbreekt”. Tijdens observatie mag een handmatige apparaatstand niet als HC-actie worden gepresenteerd.

### Instellingen en beslisvolgorde

Per zone: gewenste/minimale temperatuur, toegestane bovengrens voor voorverwarmen, relevante vochtgrenzen en regelmodus. Temperatuurwaarden worden nog ingevuld; geen verzonnen standaardwaarden.

Aanvullend: beneden schema en vertrekvertraging; boven duur van vochtoverschrijding en herstelgrens; badkamer doel en maximale duur. Valideer minimum ≤ doel ≤ maximum en ondersteunde apparaatmodi/temperatuurstappen.

Voorgestelde beslisvolgorde: gegevens en handmatige keuzes beoordelen → comfortvraag bepalen → uitvoerbare bronnen toetsen → kosten over dezelfde periode vergelijken → kiezen en uitleggen → bij geactiveerde sturing uitvoeren en terugmelding bewaken.

Bij ontbrekende prijzen vervalt prijsoptimalisatie. Bij ontbrekende temperatuur start HC geen nieuw autonoom temperatuurplan. Exact terugvalgedrag per apparaat wordt vóór automatische sturing uitgewerkt. Een gestart badkamervenster behoudt zijn eindtijd bij herstart.

## Beschikbare koppelingen

Bron: door Alex ingevulde Excel en screenshots uit dit gesprek. Dit is de bekende configuratie, geen live verbindingstest. Attributen en eenheden worden bij aansluiting gecontroleerd.

| Functie | Entiteit / bron | Aandachtspunt |
| --- | --- | --- |
| Airco beneden | `climate.airco_woonkamer` | Mitsubishi WF-rac |
| Vermogen beneden | `sensor.kwh_meter_airco_vermogen` | HomeWizard, W |
| Energie beneden | `sensor.kwh_meter_airco_energie_import` | Cumulatieve kWh controleren |
| Airco boven | `climate.19791209313101_climate` | Midea; onder meer heat en dry gemeld |
| Vermogen boven | `sensor.shellyplugsg3_d0cf13c907e0_vermogen` | Shelly, W; gecorrigeerde entiteitenlijst |
| Energie boven | `sensor.shellyplugsg3_d0cf13c907e0_energie` | Shelly, kWh; cumulatieve meterstand |
| Cv-thermostaat | `climate.huiskamer` | Remeha; actuele attributen nog nodig |
| Cv-status | `binary_sensor.huiskamer_status` | Vertraagd; exacte betekenis nog vaststellen |
| Badkamer schakelen | `switch.1_5_3_badkamer_verwarming_badkamer` | Elektrische verwarming |
| Badkamer vermogen | `sensor.1_5_3_badkamer_verwarming_badkamer_power` | W; energie-entiteit nog niet bevestigd |
| Gas | `sensor.gas_meter_gas` | Verwarming én tapwater |
| Stroomprijzen | `sensor.nordpool_kwh_nl_eur_3_095_0` | Toekomstige prijzen, eenheid, belasting en tijdvakken controleren |
| Gastarief | Handmatige instelling | €1,41197/m³, vast tot 14 juni 2027 volgens gebruiker; daarna nieuw tarief nodig |
| Aanwezigheid | `device_tracker.4_iphone_alex` | Beoogde `person`-entiteit nog aanleveren |
| UniFi | Geen bevestigd entiteit-ID | Alleen observeren; voorlopig geen invloed op HC |
| Achterdeur | `binary_sensor.1_3_woonkamer_deur_raam_sensor_achterdeur_contact` | Homey |
| CO₂ beneden | `sensor.0_energie_co2_monitor_co2` | Homey; regeling later |
| Temperatuur/vocht | Ecowitt verwacht deze week | Binnen per zone en buiten nog koppelen; badkamervocht expliciet controleren |
| Mechanische ventilatie | Continu draaiend in badkamer | Geen bevestigde regelbare entiteit of debietmeting |

## Verificatie vóór automatische regeling

| Situatie | Verwacht gedrag |
| --- | --- |
| Ontbrekende/verouderde temperatuur | Bron benoemen; geen fictieve waarde of nieuw autonoom zoneplan |
| Aanwezigheid onbekend | Niet behandelen als bewezen afwezig |
| Cv bevestigt vertraagd | Opdracht als wachtend tonen; geen opdrachtstorm |
| Korte douchepiek in vocht | Duurvoorwaarde beoordelen vóór ingrijpen |
| Dry dreigt minimumtemperatuur te schenden | Modus niet kiezen/voortzetten als deze de grens schendt |
| Cv helpt één zone maar verwarmt andere te veel | Gezamenlijk effect meenemen |
| Goedkoop voorverwarmen geeft veel extra verlies | Totale geraamde kosten vergelijken; goedkoop kwartier is geen zelfstandig besluit |
| Gasgebruik door douchen | Niet volledig als ruimteverwarming of gemeten cv-efficiëntie boeken |
| Badkamervenster verloopt, ook na herstart | Eindtijd respecteren; niet opnieuw een volledig venster starten |
| Handmatige bediening | Wijziging tonen en afgesproken overnamebeleid volgen |

## Nog nodig voor het bouwen

- Distributie: afzonderlijke app in de bestaande PicoT HEMS-repository volgens HC-ADR-011. De observatiebasis gebruikt Python 3.12, SQLite en een eigen webinterface.
- HA-verbindingsconfiguratie via beveiligde instellingen inrichten; geen toegangstokens in dit document.
- Prijsattributen, cv-attributen en het `person`-ID vaststellen.
- Ecowitt-entiteiten koppelen zodra geplaatst. Ontbrekende metingen blokkeren alleen afhankelijke functies.
- Exacte regelparameters en terugvalgedrag uitwerken voor automatische sturing.

**Volgende uitvoerstap:** de observatiebasis installeren vanuit de bestaande repository en de echte HA-brondata controleren. Daarna Ecowitt koppelen en gerichte bediening voorbereiden.
