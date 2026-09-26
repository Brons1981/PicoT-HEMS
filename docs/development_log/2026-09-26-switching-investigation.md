# Onderzoek fix 2 — laden, NOM, opnieuw laden

Alex vraagt op 26 september om het schakelen van vanmiddag te blijven onderzoeken.
Dit heeft voorrang op het afzonderlijke financiële tabblad. Alleen onderzoek en
overleg: geen productiecode, tests, instellingen of live-aansturing gewijzigd.

## Contract en bewijsgrens

Doel: verklaren waarom het lopende netlaadblok eindigde terwijl de tabel behoud
van laadcontinuïteit noemt, en waarom zes minuten later opnieuw werd geladen.
Autoriteit: ADR-037.15, ADR-024/031/032 en V2ADR-061; kandidaatconstructie,
Evaluation, tijdgebonden uitvoering en weergave behouden hun eigen rol.
Geen wijziging van dagdoel, marktbeleid, laadvermogens of belastingduur aannemen.

Bron: diagnose van 26 september circa 16:52, dus het oorspronkelijke dev.270-
incident. Volledige PlanningInputSnapshots staan in de twee oversized
incidentarchieven; vermogens- en SOC-metingen in het ruwe meetarchief van vandaag.
Alle tijden hieronder zijn Europe/Amsterdam.

## Tijdlijn

| Tijd | Bewijs |
| --- | --- |
| 15:20:31 | Plan `plan-6614002634def2b2` wordt gekozen: netladen tot 15:25:30,042180, daarna NOM. |
| 15:23:49 | SOC 94%; bestaand plan verwacht 8.098,187 Wh piek bij doel 8.160 Wh: 61,813 Wh tekort. Laadcontinuïteitsfilter verwerpt de hersteloptie. |
| 15:25:22 | SOC 95%; bestaand plan verwacht 8.093,968 Wh: 66,032 Wh tekort. Opnieuw geen toegelaten hersteloptie. |
| 15:25:37 | Verse uitvoeringswaarneming valt na de segmentgrens. Het behouden plan vraagt nu NOM; run `run-a8728bd3525bfc68`. |
| 15:26:59 | De oude netlaadgrens is verstreken. Drie PV/NOM-opties passeren nu dezelfde continuïteitscontrole. Een nieuw NOM-plan wordt gekozen. |
| 15:28:45 | Herstel van het volgende dagdoel wordt gekozen; de huidige modus blijft NOM. |
| 15:29:50 | Werkelijke SOC daalt naar 94%. |
| 15:30:35 | Nieuwe berekening verwacht 63,632 Wh tekort voor vandaag; 24 hybride netlaadopties worden gemaakt. |
| 15:31:05 | Geselecteerd plan `plan-0dcabee3230cdd87` schakelt naar snel laden; run `run-b280aabaaa4cbb96`. |
| 15:56:48 | Ruwe SOC-reeks meldt 100%. |

De belastingbescherming was bij alle genoemde planningsronden actief en
betrouwbaar; extra vraag rond 1,9–2,1 kW. Haar afgesproken extrapolatie is vijftien
minuten. Dit was geen bewijs dat de belasting daarna werkelijk verdwenen zou zijn.

## Gereproduceerde grens in kandidaatconstructie

De oorspronkelijke dev.270-bron is uit commit
`db9aa7391c55add746b3d57a074a39798a0a955f` naar een geïsoleerde scratchmap gelezen.
Vier originele snapshots zijn rechtstreeks via `main_charge_windows` verwerkt,
met de vastgelegde conversieparameters. Een tijdelijke waarnemingswrapper rond
de echte discoverer registreerde zijn resultaat zonder dat te veranderen.

| Snapshot | Resultaat discoverer | Na adapterfilter |
| --- | --- | --- |
| 15:23:49 | 1 PV-optie; `pv_only_covers_main_goal` | 0; `ongoing_load_requires_committed_grid_continuity` |
| 15:25:22 | 3 PV-opties; dezelfde reden | 0; dezelfde afwijzing |
| 15:26:59 | 3 PV-opties | 3; lopend netlaadsegment is afgelopen |
| 15:30:35 | 24 hybride opties; `residual_grid_windows` | 24 |

`IndependentDailyChargeWindowDiscoverer.discover_main_charge` stopt na haalbare
PV-opties, vóór de netlaadzoeklus. Pas downstream in
`IndependentDailyReferenceAdapter.main_charge_windows` wordt getoetst of de
opties het beschermde huidige netlaadblok intact laten. Alle PV-opties vallen
dan weg. De discoverer wordt niet opnieuw aangeroepen voor opties die wel aan
die continuïteitsvoorwaarde voldoen. Evaluation ontvangt in die ronde dus geen
uitvoerbare herstelopties; de bestaande behoudregel houdt het oude plan aan.

De twee snapshots vóór de stop zijn opnieuw door dezelfde adaptergrens van
dev.271 gehaald: dezelfde 1/3 PV-opties en 0 toegelaten opties. Dit is een
gerichte componentreproductie, geen volledige dev.271-live- of pipelinereplay.
De nieuwe marktvergelijking verandert deze afzonderlijke discoverercode niet.

Een offline fysieke proef met behoud van het resterende netladen en het nieuwe
NOM-schema bereikt voor beide snapshots weer 100% op die dag en bewaart de
minimumreserve en exportintervallen. Proeven met langer doorladen zijn eveneens
fysiek mogelijk. Dit bewijst geen financiële winnaar, geen optimale verlenging
en geen volledige toets van alle andere opdrachten. Het is bewijs dat de
afgewezen zoekruimte verdere kandidaatconstructie rechtvaardigt.

## Werkelijk vermogen en SOC

Afzonderlijke integratie van de ruwe, beschikbare vermogensreeksen tussen de
twee gemelde omschakelingen (15:25:37–15:31:05) geeft circa 140,745 Wh ontlading
en 8,906 Wh lading. Gemiddeld ontlaadvermogen is 1.544 W. De SOC-reeks daalt van
95% naar 94%; afronding en conversieverliezen verhinderen exacte gelijkstelling
van die procentstap met de AC-energiestromen.

Vóór de stop liep het gemiddelde gemeten laadvermogen terug: circa 2.045 W in
15:10–15:15, 1.947 W in 15:15–15:20 en 1.815 W in 15:20–15:25. De vastgelegde
fysieke invoer geeft 2.400 W maximale laadcapaciteit. Het lagere werkelijke
vermogen is bevestigd; BMS-begrenzing als oorzaak is met deze gegevens niet
vastgesteld. Deze observatie verandert de kandidaatblokkade niet in een
vermogensregelwijziging.

## Bewezen fout in de redenweergave

`live_runtime._execute_planning_bundle` schrijft bij een dispatch de actuele
`run.evaluation.reason` als schakelreden. Om 15:25 beschrijft die reden het
behouden van het plan wegens laadcontinuïteit. De vers verwerkte uitvoering
volgt inmiddels het volgende NOM-segment. Plankeuze en uitvoeringsreden zijn
hier verschillende gebeurtenissen; de tabel toont de eerste als verklaring
voor de tweede. De dispatch heeft de bestaande segmentgrens correct gevolgd.

## Vervolg voor overleg

Fix 2 heeft twee aangetoonde onderdelen: herstelopties construeren met de
continuïteitsvoorwaarde vanaf het begin, en de daadwerkelijke uitvoeringsreden
zichtbaar maken. Een aanpassing moet doorladen/verlengen en NOM-aanpassingen
canoniek laten beoordelen; deze analyse kiest geen vaste extra laadduur.

Regressie: echte kandidaatconstructie op een actieve laadgrens met bekend tekort,
haalbare PV-opties die continuïteit schenden, en minstens één geldige optie die
continuïteit bewaart; vervolgens canonieke selectie en een tijdgrens die tijdens
berekening verstrijkt. De huidige test
`test_continuity_candidate_exhaustion_retains_charging_and_exposes_shortfall`
vervangt de adapter door een reeds leeg resultaat en bewijst daarom uitsluitend
de behoudregel, niet de volledigheid van kandidaatconstructie.

Verificatie: vier oorspronkelijke adapterreplays op dev.270 en twee op dev.271
voltooid; ruwe meetintegratie zonder ontbrekende waarden in het onderzochte
omschakelinterval. Nog geen reparatie of nieuw schakelbeleid uitgevoerd.
