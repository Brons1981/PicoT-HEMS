# Nacht-NOM en actuele dashboardstatus: gecombineerde reparatie

Status: lokaal uitgevoerd en gericht geverifieerd; Alex heeft release dev.316 aangevraagd. Publicatie via PR en CI; installatie volgt afzonderlijk.
Basis: HEMS dev.315 / HC dev.23 (PR #725). HEMS wordt dev.316; HC blijft dev.23.

## Oorzaak en gedrag

Het nachtvenster 04:30–04:45 ontstond in de vrijgave van een overbruggingsblok bij netlaadreductie. Deze tak koos onvoorwaardelijk NOM, terwijl de hoofdlaadblokken al een PV-overschotcontrole hadden. Beide gebruiken nu dezelfde beslissing: zonder voorspeld overschot slim ontladen, met overschot NOM. Bescherming van lopend laden en bestaande reserve-/laadcontinuïteit blijven gehandhaafd.

De actuele modus wachtte op volledige plannerpublicatie en werd bij invoer/tekstselectie uitgesteld. Een afzonderlijke, uitsluitend lezende HA-observer haalt nu de bestaande geconfigureerde modusentiteit op. Een kleine ongecachete endpoint levert deze meting aan de statuskaarten. Observer wacht 10 seconden tussen verzoeken (HA-timeout 5 seconden); dashboard vraagt iedere 10 seconden op (timeout 8 seconden). Dit verkort de eigen vertraging, maar kan veroudering in HA of het apparaat niet oplossen. Geen extra besturing, plannertrigger of claim dat een opdracht is uitgevoerd.

Beide publicatieroutes vergelijken tijdzonebewuste waarnemingstijden. Oudere metingen kunnen nieuwere niet overschrijven. Leeftijd van de meting, onbeschikbaarheid en veroudering worden zichtbaar. Statuskaarten blijven bij invoer/tekstselectie verversen. Stand-by heeft een eigen amberkleur en legenda in de tijdlijn.

## Klokterugzetting

Diagnostiek 2026-10-24T201652.150: plan-ee207ea4b38b3a6c/revisie 13 bevat aaneengesloten UTC-segmenten door de terugzetting. 02:15 +02 naar 04:30 +01 is 3 uur 15 werkelijke tijd. Het NOM-venster kwam uit planrevisie 10, niet uit een UTC-gat. Geen tijdzonelogica gewijzigd.

## Verificatie

- Planner: 63 unieke gerichte tests geslaagd, inclusief twaalf nieuwe combinaties van bridge-intent, PV-balans en bescherming van actief laden.
- UI-agent: 78 tests geslaagd; één HTTP-test uitgesloten wegens socketbeperking.
- Finale gecombineerde observer/runtime/statusweergave: 16 tests geslaagd; één socket-HTTP-test uitgesloten. Deze set overlapt UI-tests; aantallen niet optellen.
- Nieuwe regressies faalden vóór hun reparatie: onterechte NOM zonder PV en terugval van nieuwere naar oudere status.
- Ruff op alle negen gewijzigde Python-bestanden geslaagd.
- Mypy op de vier gewijzigde productiebronbestanden geslaagd met Linux als doelplatform (de add-on draait op Linux).
- Onafhankelijke backendreview: gevonden timestamp-terugval gerepareerd en opnieuw gecontroleerd; geen resterende blokkerende bevinding.
- HTTP-sockettests kunnen lokaal niet binden (Windows sandbox WinError 10013). Echte HTTP/browser/HA-eindcontrole blijft nodig in CI/doelomgeving; geen liveprestatie bewezen.

## Ingebruikname en grens

Publicatie/installatie is nog niet uitgevoerd. Na installatie: Planning opnieuw berekenen om ook een reeds opgeslagen onjuist NOM-venster te vervangen. Persistente plannen worden niet stilzwijgend herschreven. Controleer vervolgens actuele modus/leeftijd, stand-bylegenda, invoer tijdens moduswisseling en het nachtplan. Geen wijziging aan Home Climate, gebruikersinstellingen of live Home Assistant.

## Releasecontrole dev.316

PR #726: Core en v2 (884 geslaagd, 1 overgeslagen) groen. Eerste volledige CI-run: 2584 geslaagd, 1 overgeslagen, 1 verouderde verwachting in test_small_predicted_recovery. Die fixture bevat nul PV in alle scenario's, maar verwachtte nog NOM in het vrijgegeven bridge-blok. De verwachting is aangescherpt tot slim ontladen met expliciet bewijs van nul PV; eigenaarschap, tijdgrens en afwezigheid van ongepland bijladen blijven getest. Productiecode is hiervoor niet gewijzigd. Volledige CI wordt opnieuw uitgevoerd vóór samenvoegen.
