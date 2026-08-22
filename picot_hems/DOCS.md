# PicoT HEMS

Deze add-on draait de eerste begrensde PicoT-validatie binnen Home Assistant OS.

## Eerste test

Laat `mode` op `dry_run` staan. Controleer daarna in de add-onlogs of:

- de ingestelde prijsentiteit wordt gelezen;
- een goedkoopste prijsvenster wordt geselecteerd;
- de huidige Zendure-modus wordt gelezen;
- de gewenste modus uitsluitend `Alleen slim ontladen` of `Nul op de meter` is;
- `dispatch_status` gelijk is aan `dry_run_only` of `skipped_already_active`.

## Live inschakelen

Zet `mode` pas op `live` nadat de dry-runuitvoer klopt. De add-on wijzigt uitsluitend:

`input_select.zendure_2400_ac_modus_selecteren`

De twee toegestane opties zijn:

- `Alleen slim ontladen`
- `Nul op de meter`

## Standaardconfiguratie

```yaml
mode: dry_run
price_entity: sensor.nordpool_kwh_nl_eur_2_10_021
target_entity: input_select.zendure_2400_ac_modus_selecteren
window_points: 1
interval_seconds: 60
```

De Home Assistant Supervisor-token wordt tijdens runtime geleverd en wordt niet opgeslagen in de repository of add-onconfiguratie.

## Observer-only energiecontract

V2ADR-054 gebruikt de bestaande dynamische prijsintervallen alleen als volledig
prijsbewijs voor het canonieke interval beschikbaar is. De volgende opties leggen
de contractrechten en directionele opslagverliezen expliciet vast:

```yaml
storage_charge_efficiency: 0.90
storage_discharge_efficiency: 0.90
energy_contract_permits_grid_import: true
energy_contract_permits_grid_export: true
energy_contract_permits_battery_export: false
```

Deze waarden voeden uitsluitend de passieve referentiesimulator. Ze wijzigen geen
kandidaatselectie, commitment, Zendure-modus of live uitvoering.
