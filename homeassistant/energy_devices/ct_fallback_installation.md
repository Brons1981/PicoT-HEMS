# CT regulation with independent RAW fallback

Use ct_regulation_fallback_fragment.yaml instead of the direct CT REST fragment, not alongside it. The complete delivered configuration also removes the obsolete household injection helpers and derived household sensors.

The selector checks every second. It accepts an Energy Devices response only when numeric, ready, from energy-devices:ev-regulation, and both its HA report and measured_at are no older than three seconds. Otherwise it selects a numeric physical Shelly report no older than three seconds. If neither qualifies, CT is unavailable; it never substitutes zero. RAW fallback stops EV correction. Home Assistant must itself be running.

## Migration

1. Back up the current configuration. Keep Energy Devices regulation_control_enabled false during installation and failure testing.
2. Rename the existing REST entity sensor.ct_shelly_pro_3em_api to sensor.ct_shelly_pro_3em_api_legacy_rest in its entity settings. This reserves the original ID for the new template entity. Complete replacement and restart together because regulation input is interrupted during migration.
3. Replace configuration.yaml with the delivered full file. Keep picot_ev_regulation_url in secrets.yaml pointing to the existing Energy Devices API.
4. Run Home Assistant configuration validation; restart only after it passes.
5. Verify the new template entity has exactly sensor.ct_shelly_pro_3em_api. If it received a numbered suffix, resolve the old registry ID and rename the new template entity to the original ID. Do not change the original Gielz automation.
6. Check physical REST sensor is sensor.picot_shelly_fysiek_vermogen and API transport is sensor.picot_energy_devices_regelvermogen. Preserve RAW sensor.ct_shelly_pro_3em_api_raw_2 as HEMS physical input. Keep Energy Devices regulation_raw_entity on the direct physical REST sensor.
7. Verify input_text.afwijkende_p1_sensor still contains sensor.ct_shelly_pro_3em_api.

## Failure test

With correction disabled, stop Energy Devices. At the first selector check after the API is unavailable or stale, selected_source must become shelly_raw, fallback_active true, and CT must equal fresh physical RAW. Restart Energy Devices; a qualifying response returns selected_source to energy_devices. Check Gielz continues normally. This does not prove live EV correction stability.

Offline evidence: YAML parsing and eleven Jinja scenarios passed: fresh correction, unavailable API, cached stale response, stale measurement, future timestamp, both stale, both missing during startup, not ready, nonfinite response, negative RAW export, and API recovery. Full HA schema validation and live stop/restart remain installation checks.

## RAW tolerance revision (2026-10-09 evening)

The physical Shelly request now waits up to five seconds. Existing RAW template unique_id is retained but becomes a one-second trigger-based buffer. The buffer retains a numeric reading for at most ten seconds from the original physical last_reported timestamp; cached output never refreshes measured_at. CT selects the RAW buffer using measured_at, not its own last_reported. held_value and measurement_delayed indicate buffering. CT raw_measurement_delayed indicates age above three seconds. API correction eligibility remains three seconds: expired corrections are not cached, and the independent RAW path provides temporary continuity. Energy Devices still uses direct physical REST input and can return 503 during failure; this intentionally switches CT to RAW rather than accepting an old correction.

For an installation already migrated to the CT template, replace the complete delivered configuration, validate in HA, and restart. No entity renaming, Gielz change, or Energy Devices release is required. Existing RAW entity must remain sensor.ct_shelly_pro_3em_api_raw_2. Keep correction disabled while testing. Twenty offline template scenarios pass (thirteen selector and seven buffer cases); full HA validation and live failure/recovery for this revision remain unverified.


## Offered-correction guard revision (2026-10-09)

For the authorized guard implementation, the existing selector's
`api_measurement_age` limit becomes ten seconds; keep `api_report_age` at three
seconds. Only the running Energy Devices producer can issue a bounded held
candidate, with original measurement time and `holding_measurement: true`.
A stopped producer still expires within three seconds. No entity migration or
Gielz modification is needed for an already migrated installation.

Keep correction disabled while installing the add-on and this selector change.
The add-on reads `regulation_offered_entity` (default the shared CT entity) and
latches correction off after a continuous mismatch or prolonged missing input.
See the add-on DOCS for timing and the explicit disable/restart reset. Older
three-second measurement eligibility above describes the previous revision.
