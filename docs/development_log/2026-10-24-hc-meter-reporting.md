# HC-vermogensrapportage bij ongewijzigde meting

Status: lokaal toegevoegd aan de goedgekeurde dashboardreparatie; niet gepubliceerd.
Alex gaf expliciet opdracht deze oorzaak mee te repareren. Deze aanvulling raakt
nu ook Home Climate; een volgende release vereist zowel HEMS als HC bijwerken.

## Bewijs en begrenzing

De HC-export picot-hc-woningmetingen.jsonl (9).gz en HEMS-diagnose
2026-10-24T230037.044.zip tonen de airco uit, bronmeter beschikbaar met 0 W,
maar verouderde source_reported. Om 22:54:19 was die tijd 85,8 seconden oud;
om 23:01:22 was dat 509,1 seconden. Reproductie van measurement() accepteert
59 seconden en weigert 61 seconden. HEMS selecteerde om 22:58 nog een winnaar:
bronfout is niet gelijk aan uitval van de hele planner of ED.

Nadere code-inspectie: fetch_states() kent al een rechtstreekse HA-template-
uitlezing voor last_reported, omdat de algemene states-JSON een gecachte oude
rapportagetijd kan bevatten. Alleen temperatuursensoren gebruikten die uitlezing;
de aircovermogensmeter niet. De export bevat niet de rechtstreekse actuele
HA-templatewaarde voor die meter. Het is dus geen bewijs dat de fysieke meter
altijd binnen 60 seconden rapporteert. Die resterende vraag moet live worden
gecontroleerd; echte stilte blijft ongeldig.

## Wijziging en invarianten

- Collector én onafhankelijke controller-read vragen de bestaande template-
  uitlezing ook voor de beneden-vermogensmeter aan. Bestaande temperatuurbronnen
  blijven behouden; geen extra HTTP-call per poll, alleen één extra entiteit in
  dezelfde template. Waarde, eenheid en rapportagetijd komen uit dezelfde read.
- measurement() accepteert geen gecachte waarde als die uitlezing mislukt,
  onvolledig is of een ongeldige tijd bevat (hc_report_error).
- TTL 60 seconden, vermogensgrenzen, eenheid, meetbronidentiteit en toekomstige-
  tijdcontrole blijven gelijk. Geen nulvulling, geen gebruik van polltijd als
  meettijd en geen afleiding van nul uit alleen de apparaatstand.
- Onbeschikbaar krijgt reden/error en bronrapportagetijd. HEMS behoudt de
  concrete fouttekst van het gecontroleerde measurement-contract. Het dashboard
  benoemt Home Climate-belastingsmeting, niet algemene ED-uitval.
- Geen MEP-, selectie-, dispatch-, dagdoel- of meettoerekeningsbeleid gewijzigd.
  Additieve metadata is compatibel met oudere consumenten. De nieuwe redenen
  verbeteren de zichtbaarheid van echte uitval; oude data blijft onbekend.

## Verse verificatie

9 regressiegevallen faalden vooraf; de bestaande live-template-leesroute zelf
slaagde al als de meter expliciet werd geselecteerd. 63 gerichte controles slagen
na herstel: actual report versus cached JSON, ongewijzigd nul, mislukte/ontbrekende
rapportage, echte veroudering van nul en positief vermogen, toekomstige/ongeldige
waarden, controller-bronselectie, HC-naar-HEMS-foutdoorgifte, concrete dashboard-
melding, bestaande controlled-load-attribution en HC-energiemodellen.

Ruff op gewijzigde HEMS-bronnen en tests groen, syntax/foutcontrole op de drie
HC-bronnen groen, mypy op planning_input/web_ui groen en volledige dashboard-JS-
syntax groen. Geen live HA-templatecontrole uitgevoerd. Echte socket-/HC-runtime-
integratie en container-/releasechecks volgen in CI; de lokale omgeving blokkeert
sockettests. Eerder 167 dashboardtests blijven afzonderlijk geregistreerd.
