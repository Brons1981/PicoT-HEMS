"""PicoT capability schema (Step 2.6.1)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Capability:
    id: str
    category: str
    kind: str
    description: str

CAPABILITIES=(
Capability("battery.observation.soc","battery","observation","Battery state of charge"),
Capability("battery.observation.power","battery","observation","Battery power"),
Capability("battery.observation.energy","battery","observation","Battery energy"),
Capability("battery.control.charge","battery","control","Charge battery"),
Capability("battery.control.discharge","battery","control","Discharge battery"),
Capability("battery.control.standby","battery","control","Standby battery"),
Capability("pv.observation.power","pv","observation","PV power"),
Capability("pv.observation.energy","pv","observation","PV energy"),
Capability("grid.observation.import_power","grid","observation","Grid import power"),
Capability("grid.observation.export_power","grid","observation","Grid export power"),
Capability("grid.observation.import_energy","grid","observation","Grid import energy"),
Capability("grid.observation.export_energy","grid","observation","Grid export energy"),
Capability("market.price.current","market","observation","Current energy price"),
Capability("market.price.forecast","market","observation","Forecast energy prices"),
Capability("weather.forecast","weather","observation","Weather forecast"),
Capability("device.switch","device","control","Switch control"),
Capability("device.number","device","control","Numeric control"),
Capability("device.select","device","control","Select control"),
Capability("device.button","device","control","Button control"),
)

def get_capabilities():
    return CAPABILITIES
