# HA-aanvullingen bij PicoT dev.260

## Gielz: vijf foutgevende vergelijkingen

De volledige live-automatisering ontbreekt. Onderstaande vervangingen betreffen
uitsluitend de vijf templates uit het aangeleverde log. Ze zijn geen volledige
vervangende automatisering. Plaats ze in de bestaande templatecondities.
Beide waarden worden eenmaal gelezen. Alleen twee geldige numerieke waarden
worden vergeleken; `unavailable` en `unknown` geven false en geen fictieve nul.
Controleer in de volledige YAML ook andere conversies en acties. Een false
voorwaarde kan een bestaande default-tak activeren; die moet eveneens worden
nagekeken voordat de automatisering opnieuw geladen wordt.

### omvormer_max_ontlaadvermogen

```jinja
{% set actual = states('sensor.zendure_2400_ac_omvormer_max_ontlaadvermogen') %}
{% set requested = states('input_number.zendure_2400_ac_max_ontlaadvermogen') %}
{{ is_number(actual) and is_number(requested)
   and (actual | float) != (requested | float) }}
```

### minimale_laadpercentage

```jinja
{% set actual = states('sensor.zendure_2400_ac_minimale_laadpercentage') %}
{% set requested = states('input_number.zendure_2400_ac_minimaal_toegestaan_laadpercentage') %}
{{ is_number(actual) and is_number(requested)
   and (actual | float) != (requested | float) }}
```

### maximale_laadpercentage

```jinja
{% set actual = states('sensor.zendure_2400_ac_maximale_laadpercentage') %}
{% set requested = states('input_number.zendure_2400_ac_maximaal_toegestaan_laadpercentage') %}
{{ is_number(actual) and is_number(requested)
   and (actual | float) != (requested | float) }}
```

### ingesteld_oplaadvermogen

```jinja
{% set actual = states('sensor.zendure_2400_ac_ingesteld_oplaadvermogen') %}
{% set requested = states('input_number.zendure_2400_ac_max_oplaadvermogen') %}
{{ is_number(actual) and is_number(requested)
   and (actual | float) != (requested | float) }}
```

### ingesteld_ontlaadvermogen

```jinja
{% set actual = states('sensor.zendure_2400_ac_ingesteld_ontlaadvermogen') %}
{% set requested = states('input_number.zendure_2400_ac_max_ontlaadvermogen') %}
{{ is_number(actual) and is_number(requested)
   and (actual | float) != (requested | float) }}
```

## Recorder: eerst de bronconfiguratie

De 16.384-byte-melding beschrijft één te groot attributenpakket, niet de totale
databasegrootte. PicoT publiceert al begrensde attributen; volledige snapshots
blijven in de eigen diagnostiek. De twee externe prijssensoren vallen buiten de
add-on. Hun live YAML en de bestaande recorderfilters zijn nodig voor de definitieve
bronreparatie, met behoud van benodigde actuele prijslijsten en historie.

Een tijdelijke mogelijkheid, alleen wanneer deze twee sensorhistorieken niet
nodig zijn, is onderstaande lijst samenvoegen met de bestaande recorderconfiguratie:

```yaml
recorder:
  exclude:
    entities:
      - sensor.dynamisch_nordpool
      - sensor.dynamisch_goedkoopste_periode
```

Dit stopt ook de registratie van hun numerieke states, niet alleen attributen.
Actuele states en attributen blijven beschikbaar. Controleer bestaande expliciete
includes: die kunnen voorrang krijgen. Geen tweede recorder-blok toevoegen.
Sluit SOC, vermogen, energiemeters en PicoT-snapshots niet generiek uit.
Deze optie is nog niet toegepast en is geen bronreparatie.

Bestaande databasegegevens zijn niet verwijderd. Meet databaseomvang en vrije
ruimte en bekijk bewaartermijn/auto_purge/auto_repack voordat opschoning wordt
gekozen. De waarschuwing alleen bewijst geen buitensporig databasebestand.

## Livecontrole na installatie

1. Controleer versie dev.260 en download een nieuwe diagnose.
2. Vergelijk SOC-bronentiteit, beschikbaarheid en tijdstempel tussen planning,
   uitvoering en werkelijke grafieklijn; controleer snapshot/run/plan-identiteiten.
3. Controleer dat behouden plannen en geblokkeerde uitvoering op tegel 5 een
   verschillende, concrete reden tonen.
4. Controleer een normale segmentgrens: modusverandering zonder economische
   herplanning. Vergelijk vervolgens een werkelijk vrijgegeven herplanrun.
5. Controleer ontbrekende brondata en fouten zonder waarden te forceren op de
   liveaccu. Selectorbevestiging alleen is geen bewijs van batterijvermogen;
   vergelijk werkelijk batterijvermogen met huisvraag/PV en de actieve primitive.
6. Bij gelijkwaardige kosten: vergelijk de netlaadseconden en de beslisregel in
   het canonical EvaluationRecord. Dagdoel/reserve blijven geldig.

Dev.254 blijft de afgesproken terugvalbasis. Liveverificatie is nog niet gedaan.

Bronnen: [HA Recorder](https://www.home-assistant.io/integrations/recorder/)
en [HA templating](https://www.home-assistant.io/docs/templating/).
