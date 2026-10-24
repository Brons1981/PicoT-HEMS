# Optionele meting elektrisch CV-hulpverbruik

HC kan bij bestaande passieve CV-opwarmmetingen een aparte elektriciteitsmeting vastleggen. Dit wijzigt geen verwarmingsopdrachten, comfortgrenzen of HEMS/MEP-plannen.

## Configuratie

- `cv_power`: aparte vermogenssensor in W; standaard leeg.
- `cv_energy`: cumulatieve verbruiksensor in kWh; standaard leeg.
- `cv_meter_scope_confirmed`: standaard false. Alleen bevestigen nadat fysiek is vastgesteld dat deze meter uitsluitend het bedoelde CV-hulpverbruik meet, inclusief de relevante pompen. Een sensornaam is daarvoor geen bewijs.

Beide sensoren zijn nodig. Een sensor die al als zonevermogen of zone-energie is ingesteld wordt geweigerd. Bestaande configuraties zonder deze opties blijven werken. Er is geen werkelijke meter ingevuld of geactiveerd.

## Meetcontract

De elektriciteitsdelta komt uit de cumulatieve teller, niet uit een geschat vermogen. Vermogen is een aanvullende beschikbaarheidscontrole; HC integreert dat vermogen niet als vervangende energie. Beide waarden moeten niet-negatief, eindig, correct van eenheid en maximaal 60 seconden oud zijn, met tijdzone en zonder toekomstige rapporttijd of rapportfout.

Een ontbrekend meetpunt, gewijzigde meteridentiteit, teruglopende teller/tijd of gewijzigde teller bij dezelfde rapporttijd maakt het elektrische traject definitief onbruikbaar voor die opwarmbeurt. De gas- en temperatuurwaarneming kan wel doorgaan. Ontbrekend verbruik wordt nooit als nul ingevuld. Gemeten nulwaarden zijn toegestaan.

Een geldig record bewaart Wh en de werkelijke begin- en eindrapporttijd van de teller. Die periode omvat ook de stabilisatie en het wachten op de gasrapportage; dit is dus niet uitsluitend de opwarmtijd tot het bereiken van de doeltemperatuur. De eindrapportage moet de stabilisatieperiode afdekken. Herstart hervat geen gedeeltelijke meting; afgeronde records blijven bewaard. Oude records zonder elektriciteitsvelden blijven leesbaar.

Het dashboard onderscheidt een aparte gemeten CV-elektriciteitsdelta van onbekend/onvolledig. Gas blijft het huishoudelijke totaal en kan koken of warmwater bevatten. Daarom blijven `comparison_eligible` en `execution_authorized` false. Geen automatische CV-alternatieven of wijzigingen aan MEP.

## Verificatie

Gerichte tests controleren een volledige meetreeks, blijvende afkeuring na een onderbreking/tellerreset/meterwissel/tijdfout, opslag en herladen, ontbrekende configuratie, onbevestigde meetafbakening, hergebruik van de aircometer, eenheden, oude/toekomstige metingen, ongeldige waarden en gemeten nul. De lokale runtime-integratietest doorloopt een gewone CV-start met beide elektrische sensoren en controleert dat er slechts één verwarmingsopdracht volgt. Home Assistant transport is vervangen door testdata; geen hardwaretest of live activatie.

Verse verificatie: 260 tests en 13 subtests geslaagd in 131,29 seconden in de gecombineerde HC/HEMS-selectie (tests plus energy_proposals, energy_outlook_hc, warmup_energy, warmup_plans, startup_energy, delayed_start, learning, start_intent, energy_start en cv_warmup). Ruff op de gewijzigde Python-modules/tests, `node --check` voor app.js en `git diff --check` geslaagd. Niet gedeployd, gecommit of gepusht.
