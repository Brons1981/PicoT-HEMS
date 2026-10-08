# Gecombineerde EV-testversie

Experimenteel: Energy Devices bezit de EV-meting en regelcorrectie. @gielz blijft
één regelaar; HEMS blijft fysieke RAW gebruiken en leest alleen het afzonderlijke
Energy Devices-beleid. Geen vooraf geplande EV-sessie in deze versie.

## Installatievolgorde

1. Installeer de Energy Devices- en HEMS-testversies met functies uitgeschakeld.
2. Energy Devices: `regulation_api_enabled: true`, `regulation_control_enabled:
   false`; controleer de drie bron-entiteiten. Poort 8101 serveert alleen GET
   `/rpc/EM.GetStatus?id=0`. De fysieke RAW-sensor blijft op Shelly.
3. Bewaar de bestaande CT REST-definitie en @gielz-automatisering als terugval.
   Vervang uitsluitend de shared CT REST-definitie volgens
   `ct_regulation_rest_fragment.yaml`. Voeg de URL van de HA-host op poort 8101
   toe aan secrets.yaml. Laat RAW ongemoeid. Gebruik geen tweede gelijknamige
   CT-sensor; behoud de bestaande REST unique_id. Verwijder de vaste testoffset.
4. Vervang de bestaande @gielz-automatisering door
   `zendure_ev_guarded_test.yaml`; voeg geen tweede actieve automatisering toe.
   Deze afgeleide versie behoudt alle originele takken en voegt alleen een
   versheidsblokkade voor NOM/slim laden/slim ontladen toe. Snelle modi blijven
   hun expliciete aansturing houden. De gebruikte bron is de bevestigde
   configuratie v20260824, GitHub commit 1c927332849b30a79f8e8e6cfdfb9fcde582210c.
5. Controleer dat `input_text.afwijkende_p1_sensor` ingesteld is op
   `sensor.ct_shelly_pro_3em_api`. Controleer bij uitgeschakelde correctie dat CT gelijk is aan RAW en @gielz
   normaal werkt. Controleer dat policy `disabled` is.
6. HEMS: fysieke `p1_power_entity` blijft RAW; zet
   `energy_device_policy_entity: sensor.picot_ev_regulation_policy` en
   `energy_device_policy_enabled: true`.
7. Activeer `regulation_control_enabled: true` in Energy Devices. Controleer
   eerst zonder EV, daarna met één gecontroleerde EV-sessie.

Door uitschakelen van de correctie retourneert de API weer RAW. Zet tevens de
HEMS-policyoptie uit om de bestaande prognosewerking te herstellen. Volledige
terugval: herstel de opgeslagen oorspronkelijke CT REST-definitie en vendor-
automatisering. Stop bij onverwachte herhaalde moduswisselingen of onbedoeld
batterij-netladen in NOM. Een geplande snelle laadactie is apart te beoordelen.

## Werking en beperkingen

Bij actieve correctie is de regelwaarde alleen beschikbaar met drie
achtereenvolgende bruikbare controles, bronnen maximaal 3 sec oud en maximaal 2 sec
uit elkaar. Meetverlies geeft HTTP 503, niet een verzonnen 0 W. De vendor-guard
stopt NOM binnen zijn volgende normale 5 sec-tick bij ontbrekende/stale feedback en
blokkeert de gewone NOM-takken. Op deze guard mag niet worden vertrouwd als een
andere automatisering of handmatige actie de batterij gelijktijdig aanstuurt.

Een ontbrekend policy-entity blokkeert de guarded NOM ook. Bewust uitschakelen
wordt expliciet gepubliceerd als `disabled`. Bij crash blijft `enabled` staan
met oude rapporttijd, wat tot blokkering leidt. Herstel wordt pas toegestaan na
opnieuw drie bruikbare Energy Devices-controles. De bestaande één-minuut-
noodstop is daarmee niet het enige vangnet voor actieve EV-correctie.

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

De guard controleert de directe CT-rapporttijd en de ingesloten brontijd. De
afgeleide `p1_aansturing_vermogen` mag bij constant vermogen een oude tijdstempel
hebben; dat is geen bewijs van verouderde fysieke meetdata.

De guard-template is met Jinja getest; firmware, HA-scheduling en de echte
installatie zijn nog niet live gevalideerd. Dit is een testversie, geen bewezen
productieversie. Leg RAW, regelwaarde, EV, Zendurevermogen, SOC, policy-status,
herplanredenen en moduswisselingen vast gedurende de sessie.

## Herkomst vendorvoorbeeld

@Gielz1986 / Michiel Hofker. Het meegeleverde vendorvoorbeeld bevat uitsluitend
bovenstaande freshness-wrapper als wijziging. De oorspronkelijke licentie
staat in LICENSE_zenSDK.txt en geldt voor dat voorbeeld. De generator kan ook
tegen de lokaal bewaarde originele YAML worden uitgevoerd:

```bash
python build_guarded_zendure.py originele_automatisering.yaml nieuwe_test.yaml
```
