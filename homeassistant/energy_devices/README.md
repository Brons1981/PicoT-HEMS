# Gecombineerde EV-testversie

Experimenteel: Energy Devices bezit de EV-meting en regelcorrectie. @gielz blijft
volledig origineel, inclusief automatiseringen en beveiligingen. De enige
gewijzigde ingang is de bestaande CT REST-sensor; HEMS blijft fysieke RAW gebruiken en leest alleen het afzonderlijke
Energy Devices-beleid. Geen vooraf geplande EV-sessie in deze versie.

## Installatievolgorde

1. Installeer de Energy Devices- en HEMS-testversies met functies uitgeschakeld.
2. Energy Devices: `regulation_api_enabled: true`, `regulation_control_enabled:
   false`; controleer de drie bron-entiteiten. Poort 8101 serveert alleen GET
   `/rpc/EM.GetStatus?id=0`. De fysieke RAW-sensor blijft op Shelly.
3. Bewaar de bestaande CT REST-definitie als terugval.
   Vervang uitsluitend de shared CT REST-definitie volgens
   `ct_regulation_rest_fragment.yaml`. Voeg de URL van de HA-host op poort 8101
   toe aan secrets.yaml. Laat RAW ongemoeid. Gebruik geen tweede gelijknamige
   CT-sensor; behoud de bestaande REST unique_id. Verwijder de vaste testoffset.
4. Laat de bestaande @gielz-integratie en automatiseringen ongewijzigd.
   Neem `zendure_ev_guarded_test.yaml` uit de eerdere release niet over.
5. Controleer dat `input_text.afwijkende_p1_sensor` ingesteld is op
   `sensor.ct_shelly_pro_3em_api`. Controleer bij uitgeschakelde correctie dat CT gelijk is aan RAW en @gielz
   normaal werkt. Controleer dat policy `disabled` is.
6. HEMS: fysieke `p1_power_entity` blijft RAW; zet
   `energy_device_policy_entity: sensor.picot_ev_regulation_policy` en
   `energy_device_policy_enabled: true`.
7. Controleer met `regulation_control_enabled: false` eerst live de versheid
   van de drie bronnen en de gelijkheid CT/RAW. Activeer de correctie pas voor
   één gecontroleerde EV-sessie als de bronnen aan de versheidsgrenzen voldoen.

Door uitschakelen van de correctie retourneert de API weer RAW. Zet tevens de
HEMS-policyoptie uit om de bestaande prognosewerking te herstellen. Volledige
terugval: herstel de opgeslagen oorspronkelijke CT REST-definitie. Stop bij onverwachte herhaalde moduswisselingen of onbedoeld
batterij-netladen in NOM. Een geplande snelle laadactie is apart te beoordelen.

## Werking en beperkingen

Bij actieve correctie is de regelwaarde alleen beschikbaar met drie
achtereenvolgende bruikbare controles, bronnen maximaal 3 sec oud en maximaal 2 sec
uit elkaar. Meetverlies geeft HTTP 503, niet een verzonnen 0 W. Energy Devices
verstrekt dan geen gecorrigeerde regelwaarde. Dit is geen opdracht om de
batterij te stoppen: @gielz behoudt zijn oorspronkelijke reactie op een
ontbrekende P1-meting. Er is geen extra 5-secondenstop of vendor-blokkade.
De bestaande unavailable-noodstop wacht een minuut; bij meetverlies kan de vorige opdracht daardoor ongeveer een minuut blijven
werken. Als HomeWizard beschikbaar is, kan het origineel daarnaar terugvallen
en tijdelijk weer EV-verbruik uit de batterij ondersteunen. Deze reactie is
ongewijzigd; de correctie claimt tijdens die terugval geen EV-bescherming.

Bewust uitschakelen wordt expliciet als `disabled` gepubliceerd. De API geeft
bij uitgeschakelde correctie verse RAW door. Herstel van de gecorrigeerde waarde
vraagt drie achtereenvolgende bruikbare Energy Devices-controles. De policy-
entiteit is voor HEMS; de originele @gielz-integratie leest haar niet.

HEMS verwijdert uitsluitend geïdentificeerde EV-metingen uit de baseline/guard-
prognoseweergave, behoudt fysieke historie en voegt de actuele EV daarna één
keer toe met een expliciete 15 min-voortzettingsaanname. Onbekende sessieduur wordt
niet als 4 uur verzonnen. Stop/nieuwe snapshot vervangt die bijdrage. De MEP-
simulatie laat werkelijk PV eerst fysieke lasten voeden en ondersteunt alleen
het niet-uitgesloten huis vanuit opslag. Bewuste EV-netimport is geen
brugtekort, maar telt volledig mee in de kosten. EV-start/stop of minstens 100 W wijziging wordt na minstens 30 seconden
bevestiging via de bestaande Runtime Monitor verwerkt. De ingestelde HEMS-
pollinterval bepaalt de aanvullende detectietijd (standaard 60 seconden).
Meetversies en kleine fluctuaties veroorzaken op zichzelf geen herplanning.
SOC-tekort voor het 100%-dagdoel
kan nog steeds een terecht herstelplan veroorzaken.

De meetversheid wordt uitsluitend binnen Energy Devices gecontroleerd.
Firmware, HA-scheduling en het gedrag van de originele @gielz-automatisering
bij vertraagde metingen zijn nog niet live bewezen. Leg RAW, regelwaarde, EV,
Zendurevermogen, SOC, policy-status, herplanredenen en moduswisselingen vast.

## Correctie op de eerste testrelease

De eerste release bevatte onterecht een gewijzigde @gielz-automatisering en
instructies om deze over te nemen. Die toevoeging is verwijderd uit de
correctiekandidaat. De afspraak blijft: alleen een aangepaste P1-waarde
leveren; @gielz zelf blijft origineel. Als het eerdere YAML-voorbeeld handmatig
is geïnstalleerd, herstel dan de eigen opgeslagen originele automatisering.

## Offline toets van het origineel

Zestien scenario's combineren de werkelijke Energy Devices-observer/cache met
de oorspronkelijke vier NOM-takken en de oorspronkelijke noodstopvoorwaarden:
EV-start/stop, drie PV-niveaus, 1–2 s vertraging, 10 W ruis, trage batterijreactie,
5 s vertraging, stilgevallen RAW/EV/batterij, meetlusuitval en HomeWizard-terugval.
Met verse 1–2 s-bronnen waren er geen geconstateerde EV-ontlading of netlading in
de beoordeelde stabiele NOM-vensters. Bij 3000 W PV, 200 W huis en 2000 W EV
wordt 800 W overschot benut (750 W na de oorspronkelijke 50 W laadmarge).

De originele noodstop volgde in de uitvalproef na circa 62 s P1-onbeschikbaarheid
(afronding op de normale 5 s-tick), niet na 5 s. Tijdens een PV-daling vlak na
meetverlies kon de voorgaande laadopdracht tijdelijk uit het net blijven laden.
Met HomeWizard-terugval ontlaadde de batterij in het 1000 W PV-venster 1205 W
in plaats van neutraal te blijven. Dat is het oorspronkelijke gedrag.

De proef gebruikt een beperkte bron-template-interpreter en een synthetische
batterij. Zes aanvullende regressietests voeren de originele commandtemplates
met Jinja uit en controleren de oorspronkelijke noodstop en CT-beschikbaarheid.
Dit bewijst geen volledige HA-automatiseringsruntime of firmwarestabiliteit.
