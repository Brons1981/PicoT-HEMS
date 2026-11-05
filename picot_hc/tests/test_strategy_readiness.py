from types import SimpleNamespace

from picot_hc.cooling import Cooling
from picot_hc.core import Store
from picot_hc.energy_model import EnergyModel
from picot_hc.strategy_readiness import assess
from picot_hc.warmup_energy import WarmupEnergy


def test_counts_distinguish_stored_recent_and_matching_without_enabling_control(tmp_path):
    store = Store(tmp_path / 'hc.sqlite3')
    steady = EnergyModel(store)
    warmup = WarmupEnergy(store)
    startup = WarmupEnergy(store, cold_start=True)
    cooling = Cooling(store)
    now = 1800000000
    sample = dict(identity='room', source_id='meter', indoor=20, outdoor=10, target=20)
    steady.records = [dict(sample, measured_at=now-i*60, mean_power_w=500) for i in range(3)]
    steady.records.append(dict(sample, measured_at=now-8*86400, mean_power_w=900))
    steady.records.append(dict(sample, measured_at=now, mean_power_w=600, outdoor=-5))
    rt = SimpleNamespace(energy_proposals=SimpleNamespace(model=steady), warmup_energy=warmup,
        startup_energy=SimpleNamespace(model=startup), warmup_sample=None, startup_sample=None,
        heating=SimpleNamespace(learning=SimpleNamespace(cooling=cooling)))
    result = assess(rt, {'learning_context': None}, sample, now)
    status = result['models']['handhaven']
    assert (status['stored'], status['recent'], status['matching']) == (5, 4, 3)
    assert status['status'] == 'ready'
    assert result['models']['handhaven_18']['status'] == 'waiting'
    assert result['models']['start_uit']['status'] == 'waiting'
    assert result['execution_authorized'] is False
    assert result['status'] == 'development'
    assert len(result['scenarios']) == 3
    assert len(steady.records) == 5
