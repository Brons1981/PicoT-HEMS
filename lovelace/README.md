# PicoT Technical View v1

`picot_technical_view.yaml` is the first functional Home Assistant dashboard for PicoT HEMS.
It intentionally uses only standard Home Assistant cards.

## Purpose

The view follows the information structure of PEP-UI-001:

1. External world
2. PicoT brain
3. House and grid
4. History today
5. Runtime and future layers

It is a technical validation dashboard, not the final PicoT Explainable Energy Cockpit.

## Required entities

The view expects these PicoT entities:

- `sensor.picot_hems_status`
- `sensor.picot_current_price`
- `sensor.picot_grid_power`
- `sensor.picot_grid_import`
- `sensor.picot_grid_export`
- `sensor.picot_operating_mode`
- `sensor.picot_desired_mode`
- `sensor.picot_dispatch_status`
- `sensor.picot_active_price_window`

## Installation in Home Assistant

1. Go to **Settings -> Dashboards**.
2. Create a new dashboard named **PicoT Technical View**.
3. Open the dashboard and choose **Edit dashboard**.
4. Open the three-dot menu and choose **Raw configuration editor**.
5. Replace the contents with `picot_technical_view.yaml`.
6. Save the configuration.

The history cards use Home Assistant Recorder. Historical graphs will fill as Home Assistant records the PicoT sensor states.

## Current limitations

- Weather, PV, battery SoC, battery power, EV state, Safety Layer and User Rules are not yet connected.
- The current dashboard is functional and intentionally low on custom visuals.
- The future visual Energy Scene remains governed by PEP-UI-001.
