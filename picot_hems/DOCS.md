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

## MEP-marktinstellingen

Onder **Instellingen → Add-ons → PicoT HEMS → Configuratie** zijn de twee
financiële toelatingswaarden rechtstreeks door de gebruiker instelbaar:

- `market_daily_trading_margin_percent`: gewenste extra handelsmarge in procenten;
  standaard `10.0`.
- `market_daily_wear_eur_per_kwh`: toegerekende batterijslijtage per geëxporteerde
  kWh; standaard `0.05` euro.

Start de add-on na een wijziging opnieuw. In **PicoT Pipeline → Strategie** toont
iedere onderzochte marktroute de herstelprijs, RTE-correctie, handelsmarge,
slijtage en de daaruit volgende minimale exportprijs. Zo blijft zichtbaar waarom
de gewijzigde instelling een route wel of niet toelaat.

## Kleine topsessies

`micro_charge_suppression_percent` bepaalt vanaf welk resterend percentage PicoT
geen nieuwe afzonderlijke laadsessie meer start. De standaardwaarde is `2.0`.
De grens geldt voor CP, de etmaalsimulatie en MEP. Onderdrukking is alleen
toegestaan wanneer de minimumreserve zonder die topsessie in alle doorgerekende
scenario's veilig blijft. Een al lopende laadsessie wordt niet afgebroken.

## Herstel na export-eerst

Een export-eerst-marktroute hoeft de batterij na normaal huisverbruik niet
absoluut op 100% te laten eindigen. MEP vergelijkt het einde van ieder scenario
met hetzelfde scenario zonder handel. De route is fysiek toegestaan wanneer de
batterij minstens tot dat baseline-niveau wordt hersteld en de minimumreserve
gewaarborgd blijft. Daarna moet de volledige route, inclusief RTE, handelsmarge
en slijtage, nog steeds financieel positief zijn.
