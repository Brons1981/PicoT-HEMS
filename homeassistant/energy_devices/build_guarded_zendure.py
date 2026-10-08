"""Offline installer preparation: wrap existing NOM choose with a freshness guard.

Run against the user's confirmed @gielz YAML. Never changes a live automation.
Preserves the original branches; adds no watt calculation or second controller.
Requires PyYAML in this preparation environment, not the Energy Devices add-on.
"""

import argparse
from pathlib import Path

import yaml

GUARD = """{% set policy = states.sensor.picot_ev_regulation_policy %}
{% set enabled = policy is none or policy.state != 'disabled' %}
{% set p1 = states.sensor.p1_aansturing_vermogen %}
{% set ct = states.sensor.ct_shelly_pro_3em_api %}
{% set selected = states.input_text.afwijkende_p1_sensor %}
{% set battery = states.sensor.zendure_2400_ac_vermogen_aansturing %}
{% set now_s = as_timestamp(now()) %}
{% set valid = policy is not none and policy.state == 'enabled'
   and policy.attributes.get('status') == 'ready'
   and now_s - as_timestamp(policy.attributes.get('measured_at'), 0) >= 0
   and now_s - as_timestamp(policy.attributes.get('measured_at'), 0) <= 3
   and p1 is not none and p1.state not in ['unavailable', 'unknown']
   and selected is not none and selected.state == 'sensor.ct_shelly_pro_3em_api'
   and ct is not none and ct.state not in ['unavailable', 'unknown']
   and now_s - as_timestamp(ct.last_reported, 0) >= 0
   and now_s - as_timestamp(ct.last_reported, 0) <= 3
   and now_s - as_timestamp(ct.attributes.get('measured_at'), 0) >= 0
   and now_s - as_timestamp(ct.attributes.get('measured_at'), 0) <= 3
   and battery is not none and battery.state not in ['unavailable', 'unknown']
   and now_s - as_timestamp(battery.last_reported, 0) >= 0
   and now_s - as_timestamp(battery.last_reported, 0) <= 3 %}
{{ enabled and not valid }}"""


def guarded(document):
    if document.get("description", "").endswith(" + PicoT EV freshness guard v1"):
        raise ValueError("guard already installed")
    actions = document["actions"]
    index = next(i for i, a in enumerate(actions) if a.get("alias") == "NOM Aansturing")
    original = actions[index]
    actions[index] = {
        "alias": "NOM Aansturing",
        "choose": [
            {
                "alias": "PicoT EV stale feedback: stop delegated regulation",
                "conditions": [
                    {"condition": "trigger", "id": "aansturing_trigger"},
                    {
                        "condition": "state",
                        "entity_id": "input_select.zendure_2400_ac_modus_selecteren",
                        "state": ["Nul op de meter", "Alleen slim ontladen", "Alleen slim opladen"],
                    },
                    {"condition": "template", "value_template": GUARD},
                ],
                "sequence": [
                    {
                        "action": "rest_command.zendure_stop_met_alles",
                        "data": {"sn": "{{ states('sensor.zendure_2400_ac_serienummer') }}"},
                    },
                    {
                        "action": "logbook.log",
                        "data": {
                            "name": "PicoT EV meetbewaking",
                            "message": "NOM geblokkeerd: geen verse samenhangende regelmeting",
                            "entity_id": "sensor.picot_ev_regulation_policy",
                        },
                    },
                ],
            }
        ],
        "default": [original],
    }
    document["description"] = document.get("description", "") + " + PicoT EV freshness guard v1"
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    document = yaml.safe_load(Path(args.source).read_text())
    Path(args.output).write_text(
        yaml.safe_dump(guarded(document), allow_unicode=True, sort_keys=False)
    )
